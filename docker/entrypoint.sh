#!/usr/bin/env bash
# =============================================================================
# ATLAS — entrypoint.sh
# Точка входа контейнера. Реализует ZERO-CONFIG адаптацию GPU через PyTorch,
# выбор модели, управление дисковым кэшем Hugging Face и запуск supervisord.
# =============================================================================
set -euo pipefail

echo "======================================================================"
echo "          ATLAS — Autonomous Vibe-Coding Environment                  "
echo "======================================================================"

# -----------------------------------------------------------------------------
# 1. Подготовка базовых директорий и переменных окружения
# -----------------------------------------------------------------------------
export HF_HOME=/workspace/hf_cache
export HF_HUB_ENABLE_HF_TRANSFER=1

mkdir -p /workspace/hf_cache /workspace/logs /workspace/projects /workspace/hf_cache/hub

# Загрузка переменных из .env, если файл присутствует в /workspace или корне
if [ -f "/workspace/.env" ]; then
    echo "[ATLAS] Загрузка переменных окружения из /workspace/.env"
    set -a
    # shellcheck disable=SC1091
    source /workspace/.env
    set +a
elif [ -f "/.env" ]; then
    echo "[ATLAS] Загрузка переменных окружения из /.env"
    set -a
    # shellcheck disable=SC1091
    source /.env
    set +a
fi

# -----------------------------------------------------------------------------
# 1.1. Активация лицензии Unity CLI (при наличии переменной UNITY_LICENSE)
# -----------------------------------------------------------------------------
if [ -n "${UNITY_LICENSE:-}" ]; then
    echo "[ATLAS] Обнаружена переменная UNITY_LICENSE. Активация Unity..."
    UNITY_LIC_DIR="/root/.local/share/unity3d/Unity"
    mkdir -p "${UNITY_LIC_DIR}"
    echo "${UNITY_LICENSE}" > "${UNITY_LIC_DIR}/Unity_lic.ulf"
    chmod 644 "${UNITY_LIC_DIR}/Unity_lic.ulf"
    echo "[ATLAS] Лицензия Unity успешно активирована в ${UNITY_LIC_DIR}/Unity_lic.ulf"
fi

# -----------------------------------------------------------------------------
# 1.2. Авто-синхронизация репозитория проекта в /workspace
# Восстанавливает код, PROJECT_MEMORY.md и sessions/ на эфемерном Container Disk
# -----------------------------------------------------------------------------
if [ -n "${PROJECT_REPO_URL:-}" ]; then
    echo "[ATLAS] Настройка и синхронизация репозитория проекта: ${PROJECT_REPO_URL}"
    AUTH_REPO_URL="${PROJECT_REPO_URL}"
    if [ -n "${GITHUB_TOKEN:-}" ] && [[ "${PROJECT_REPO_URL}" =~ ^https://github.com/ ]]; then
        AUTH_REPO_URL="https://${GITHUB_TOKEN}@${PROJECT_REPO_URL#https://}"
    fi

    if [ -d "/workspace/.git" ]; then
        echo "[ATLAS] Репозиторий уже присутствует в /workspace. Обновление из origin..."
        git -C /workspace remote set-url origin "${AUTH_REPO_URL}" || true
        git -C /workspace fetch origin || true
        git -C /workspace pull --rebase origin main || true
    else
        echo "[ATLAS] Первичное развёртывание репозитория в /workspace..."
        mkdir -p /tmp/atlas_repo_bootstrap
        if git clone "${AUTH_REPO_URL}" /tmp/atlas_repo_bootstrap; then
            cp -a /tmp/atlas_repo_bootstrap/. /workspace/
            rm -rf /tmp/atlas_repo_bootstrap
            git -C /workspace remote set-url origin "${AUTH_REPO_URL}"
            echo "[ATLAS] Репозиторий успешно развёрнут в /workspace."
        else
            echo "[ATLAS WARNING] Не удалось клонировать ${PROJECT_REPO_URL}. Проверьте токен доступа GITHUB_TOKEN."
        fi
    fi

    # Базовая конфигурация автора коммитов
    git -C /workspace config user.name "${GIT_USER_NAME:-ATLAS Mobile Bridge}"
    git -C /workspace config user.email "${GIT_USER_EMAIL:-atlas@project.local}"
fi

# -----------------------------------------------------------------------------
# 2. Inline Python: ZERO-CONFIG анализ GPU и формирование параметров
# -----------------------------------------------------------------------------
echo "[ATLAS] Определение доступного оборудования через PyTorch..."

python3 - << 'EOF'
import os
import sys
import shutil
import urllib.request
import urllib.parse
import json

def notify_telegram(message: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("ALLOWED_TELEGRAM_ID", "").strip()
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        print("[ATLAS] Уведомление об ошибке успешно отправлено в Telegram.")
    except Exception as e:
        print(f"[ATLAS] Предупреждение: не удалось отправить сообщение в Telegram: {e}", file=sys.stderr)

try:
    import torch
except ImportError:
    err = "Критическая ошибка: PyTorch не установлен в контейнере."
    print(f"[ATLAS] {err}", file=sys.stderr)
    notify_telegram(f"❌ *ATLAS Error*: {err}")
    sys.exit(1)

# 1. Проверка доступности GPU
if not torch.cuda.is_available():
    err_msg = (
        "❌ *Ошибка запуска ATLAS*: NVIDIA GPU не обнаружены!\n\n"
        "Контейнер запущен без доступа к видеокартам CUDA.\n"
        "Убедитесь, что в RunPod выбран GPU инстанс и передан флаг NVIDIA_VISIBLE_DEVICES."
    )
    print(f"[ATLAS] {err_msg}", file=sys.stderr)
    notify_telegram(err_msg)
    sys.exit(2)

num_gpus = torch.cuda.device_count()
if num_gpus < 1:
    err_msg = "❌ *Ошибка запуска ATLAS*: количество доступных GPU равно 0."
    print(f"[ATLAS] {err_msg}", file=sys.stderr)
    notify_telegram(err_msg)
    sys.exit(2)

# 2. Сбор характеристик всех выделенных GPU
gpu_names = [torch.cuda.get_device_name(i) for i in range(num_gpus)]
capabilities = [torch.cuda.get_device_capability(i) for i in range(num_gpus)]
vram_per_gpu_mb = [torch.cuda.mem_get_info(i)[1] // (1024 * 1024) for i in range(num_gpus)]
total_vram_mb = sum(vram_per_gpu_mb)

# Максимальная архитектурная версия среди выделенных карт
max_cap_major = max(c[0] for c in capabilities)
max_cap_minor = max(c[1] for c in capabilities if c[0] == max_cap_major)
max_cap = max_cap_major + (max_cap_minor / 10.0)

print(f"[ATLAS] Обнаружено выделенных GPU: {num_gpus}")
for i in range(num_gpus):
    print(f"  - GPU {i}: {gpu_names[i]} | Compute Cap: {capabilities[i][0]}.{capabilities[i][1]} | VRAM: {vram_per_gpu_mb[i]} МБ")
print(f"[ATLAS] Суммарно доступной VRAM: {total_vram_mb} МБ (~{total_vram_mb // 1024} ГБ)")

# 3. Выбор модели, квантизации и порогов VRAM
if max_cap >= 8.9:
    # Ada Lovelace / Hopper / Blackwell (L40, L40S, RTX 6000 Ada, 2x RTX 4090, H100)
    arch_type = "Ada/Hopper/Blackwell (Compute Cap >= 8.9)"
    model_name = "Qwen/Qwen3.6-35B-A3B-FP8"
    extra_flags = "--kv-cache-dtype fp8"
    min_vram_mb = 44000
    quant_label = "Official FP8 + fp8 KV-Cache"
else:
    # Ampere / Turing (A40, RTX A6000, A100, 2x RTX 3090)
    arch_type = "Ampere/Предыдущие (Compute Cap < 8.9)"
    model_name = "QuantTrio/Qwen3.6-35B-A3B-AWQ"
    extra_flags = ""
    min_vram_mb = 28000
    quant_label = "AWQ 4-bit (Standard KV-Cache)"

print(f"[ATLAS] Архитектура чипа: {arch_type}")
print(f"[ATLAS] Выбранная модель: {model_name} ({quant_label})")
print(f"[ATLAS] Минимальный порог VRAM: {min_vram_mb} МБ")

# 4. Проверка достаточности видеопамяти
if total_vram_mb < min_vram_mb:
    short_err = (
        f"Недостаточно VRAM для запуска ATLAS!\n"
        f"Доступно: {total_vram_mb} МБ (~{total_vram_mb // 1024} ГБ).\n"
        f"Требуется минимум: {min_vram_mb} МБ (~{min_vram_mb // 1024} ГБ) для модели {model_name}."
    )
    full_tg_msg = (
        f"❌ *Ошибка запуска ATLAS (Недостаточно VRAM)*\n\n"
        f"• *Выделено GPU*: {num_gpus} × {gpu_names[0]}\n"
        f"• *Доступно VRAM*: {total_vram_mb} МБ (~{total_vram_mb // 1024} ГБ)\n"
        f"• *Архитектура*: {arch_type}\n"
        f"• *Целевая модель*: `{model_name}`\n"
        f"• *Требуемый порог*: {min_vram_mb} МБ (~{min_vram_mb // 1024} ГБ)\n\n"
        f"⚠️ *Решение*: Выберите в RunPod инстанс с VRAM от 48 ГБ (L40, L40S, A40, RTX 6000 Ada) "
        f"либо связку 2× 24 ГБ (2× RTX 4090 / 2× RTX 3090)."
    )
    print(f"\n[ATLAS ERROR] {short_err}\n", file=sys.stderr)
    notify_telegram(full_tg_msg)
    # Завершаем скрипт корректно, чтобы supervisor не циклил рестарты vLLM
    sys.exit(10)

# 5. Определение длины контекста (max-model-len)
if total_vram_mb >= 75000:
    max_model_len = 65536
    print("[ATLAS] VRAM >= 75 ГБ: установлен расширенный контекст --max-model-len 65536")
else:
    max_model_len = 32768
    print("[ATLAS] VRAM < 75 ГБ: установлен базовый контекст --max-model-len 32768")

# 6. Smart Cache Cleanup и загрузка модели через hf_transfer
hf_cache_dir = os.environ.get("HF_HOME", "/workspace/hf_cache")
hub_dir = os.path.join(hf_cache_dir, "hub")
os.makedirs(hub_dir, exist_ok=True)

# Имя каталога модели в кэше HF: models--<org>--<repo>
target_cache_dir = f"models--{model_name.replace('/', '--')}"
target_full_path = os.path.join(hub_dir, target_cache_dir)
is_model_cached = os.path.exists(target_full_path) and len(os.listdir(target_full_path)) > 0

if not is_model_cached:
    print(f"[ATLAS] Модель {model_name} отсутствует в локальном кэше. Проверка дискового пространства...")
    free_bytes = shutil.disk_usage("/workspace").free
    free_gb = free_bytes / (1024 ** 3)
    print(f"[ATLAS] Свободное место на /workspace: {free_gb:.1f} ГБ")
    
    # 1. Если свободно менее 40 ГБ — сначала удаляем неактуальные модели
    if free_gb < 40.0:
        print("[ATLAS] Свободно менее 40 ГБ! Удаление неиспользуемых моделей из кэша...")
        for item in os.listdir(hub_dir):
            if item != target_cache_dir and item.startswith("models--"):
                item_path = os.path.join(hub_dir, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        print(f"[ATLAS] Удалена неиспользуемая модель: {item}")
                except Exception as clean_err:
                    print(f"[ATLAS] Предупреждение при удалении {item}: {clean_err}")
    
    # 2. Повторная проверка свободного места после очистки
    new_free_bytes = shutil.disk_usage("/workspace").free
    new_free_gb = new_free_bytes / (1024 ** 3)
    print(f"[ATLAS] Свободное место после проверки: {new_free_gb:.1f} ГБ")
    
    if new_free_gb < 40.0:
        err_disk_msg = (
            f"❌ *Ошибка запуска ATLAS (Недостаточно места на диске)*\n\n"
            f"• *Свободно на /workspace*: {new_free_gb:.1f} ГБ\n"
            f"• *Требуемый порог*: 40.0 ГБ для загрузки модели `{model_name}`\n\n"
            f"⚠️ *Решение*: При создании пода в RunPod Community Cloud укажите Container Disk не менее 75–80 ГБ."
        )
        print(f"\n[ATLAS ERROR] {err_disk_msg}\n", file=sys.stderr)
        notify_telegram(err_disk_msg)
        sys.exit(11)
        
    # 3. Скачивание целевой модели через hf_transfer
    print(f"[ATLAS] Запуск скачивания модели {model_name} через hf_transfer...")
    try:
        from huggingface_hub import snapshot_download
        hf_token = os.environ.get("HF_TOKEN", "").strip() or None
        snapshot_download(repo_id=model_name, token=hf_token)
        print(f"[ATLAS] Модель {model_name} успешно скачана и верифицирована в кэше.")
    except Exception as dl_err:
        err_dl_msg = (
            f"❌ *Ошибка загрузки модели Hugging Face*\n\n"
            f"• *Модель*: `{model_name}`\n"
            f"• *Ошибка*: `{str(dl_err)}`\n"
        )
        print(f"\n[ATLAS ERROR] {err_dl_msg}\n", file=sys.stderr)
        notify_telegram(err_dl_msg)
        sys.exit(12)
else:
    print(f"[ATLAS] Модель {model_name} уже присутствует в локальном кэше ({target_full_path}).")

# 7. Запись вычисленных параметров в файлы окружения
env_conf_path = "/tmp/vllm_env.sh"
with open(env_conf_path, "w", encoding="utf-8") as f:
    f.write(f"export VLLM_MODEL='{model_name}'\n")
    f.write(f"export VLLM_TP_SIZE={num_gpus}\n")
    f.write(f"export VLLM_MAX_CTX={max_model_len}\n")
    f.write(f"export VLLM_EXTRA_FLAGS='{extra_flags}'\n")

# Запись итоговой строки аргументов vLLM
args_conf_path = "/tmp/vllm_args.conf"
base_args = (
    f"--model {model_name} "
    f"--tensor-parallel-size {num_gpus} "
    f"--max-model-len {max_model_len} "
    f"--gpu-memory-utilization 0.90 "
    f"--max-num-seqs 4 "
    f"--enable-prefix-caching "
    f"--served-model-name atlas-brain "
    f"--host 0.0.0.0 "
    f"--port 8000 "
    f"--enable-auto-tool-choice "
    f"--tool-call-parser qwen3_xml"
)
if extra_flags:
    full_args = f"{base_args} {extra_flags}"
else:
    full_args = base_args

with open(args_conf_path, "w", encoding="utf-8") as f:
    f.write(full_args.strip() + "\n")

print("[ATLAS] Конфигурация vLLM успешно сохранена в /tmp/vllm_env.sh и /tmp/vllm_args.conf")
EOF

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "[ATLAS] Завершение работы entrypoint (код завершения: $EXIT_CODE)."
    # Если завершение произошло из-за недостатка VRAM или отсутствия GPU,
    # не запускаем supervisord во избежание бесконечного цикла рестартов.
    exit 0
fi

# -----------------------------------------------------------------------------
# 3. Экспорт параметров в текущую shell-сессию для supervisord
# -----------------------------------------------------------------------------
if [ -f "/tmp/vllm_env.sh" ]; then
    # shellcheck disable=SC1091
    source /tmp/vllm_env.sh
fi

echo "----------------------------------------------------------------------"
echo "[ATLAS] Итоговые параметры запуска vLLM:"
echo "  - Модель:               $VLLM_MODEL"
echo "  - Tensor Parallel:      $VLLM_TP_SIZE"
echo "  - Max Model Len:        $VLLM_MAX_CTX"
echo "  - Дополнительные флаги: ${VLLM_EXTRA_FLAGS:-нет}"
echo "----------------------------------------------------------------------"
echo "[ATLAS] Запуск supervisor (PID 1)..."

# -----------------------------------------------------------------------------
# 4. Запуск supervisor
# -----------------------------------------------------------------------------
exec supervisord -c /docker/supervisord.conf
