# Архитектура ATLAS

## Обзор

ATLAS — автономная среда для vibe-кодинга. Один Docker-контейнер на RunPod,
управляемый локально через Cursor IDE (SSH) и удалённо через Telegram с Android.

## Диаграмма компонентов

```
┌─────────────────────────────────────────────────────────────┐
│  RunPod Pod (≥48 ГБ VRAM)                                   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Контейнер atlas (supervisor PID 1)                  │    │
│  │                                                     │    │
│  │  ┌──────────────┐    ┌────────────────────────┐     │    │
│  │  │  vLLM :8000  │    │  mobile_bridge.py      │     │    │
│  │  │  atlas-brain │◄───│  (aiogram, Telegram)   │     │    │
│  │  │  Qwen3.6     │    │  + Function Calling    │     │    │
│  │  └──────────────┘    └────────────────────────┘     │    │
│  │         ▲                       │                    │    │
│  │         │                       ▼                    │    │
│  │  ┌──────┴──────────────────────────────────────┐    │    │
│  │  │  /workspace (persistent volume)              │    │    │
│  │  │  ├── hf_cache/    (модели HF)               │    │    │
│  │  │  ├── projects/    (рабочие проекты)          │    │    │
│  │  │  └── logs/        (логи skills)              │    │    │
│  │  └─────────────────────────────────────────────┘    │    │
│  │                                                     │    │
│  │  Инструменты: Android SDK, Unity, Godot,            │    │
│  │               Blender, Node.js, Git                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
         ▲              ▲                    ▲
         │              │                    │
    SSH/Remote     Telegram API        GitHub Actions
    (Cursor IDE)   (Android)           (CI/CD → GHCR)
```

## Ключевые решения

### Один контейнер vs. несколько
Выбран **один контейнер** с supervisor. Причины:
- Модель RunPod: один Pod = один контейнер.
- Тривиальный доступ vLLM и bridge к общему `/workspace` и `localhost:8000`.
- Supervisor управляет процессами (autorestart, зависимости).

Fallback при конфликте vLLM/PyTorch: два контейнера с bridge-сетью `atlas-net`.

### Определение GPU
Строго через PyTorch (`torch.cuda.device_count()`, `get_device_capability`,
`mem_get_info`), а **не** через `nvidia-smi`. В контейнерах RunPod `nvidia-smi`
может показывать GPU физического хоста, что ведёт к неверному tensor-parallel-size.

### Выбор модели
| Архитектура GPU | Compute Cap | Модель | Квантизация | Мин. VRAM |
|-----------------|-------------|--------|-------------|-----------|
| Ada / Hopper / Blackwell | ≥ 8.9 | Qwen/Qwen3.6-35B-A3B-FP8 | FP8 + fp8 KV-cache | 44 ГБ |
| Ampere | < 8.9 | QuantTrio/Qwen3.6-35B-A3B-AWQ | AWQ 4-bit | 28 ГБ |

### Кэширование моделей
`HF_HOME=/workspace/hf_cache` — на persistent volume. Smart Cache Cleanup
удаляет неиспользуемые модели при недостатке места (<40 ГБ свободно).

## Потоки данных

### Cursor IDE → ATLAS
1. Пользователь подключается к Pod через SSH (Cursor Remote).
2. Cursor Rules (`.cursor/rules/*.mdc`) задают поведение агента.
3. Агент вызывает skills (`skills/*.py`) и получает JSON-отчёт.
4. Визуальная проверка через `vision_bridge.py` (скриншоты эмулятора/Unity).

### Telegram → ATLAS
1. Пользователь отправляет текст/фото в Telegram-бот.
2. `mobile_bridge.py` проверяет `ALLOWED_TELEGRAM_ID`.
3. Запрос передаётся в vLLM (`localhost:8000`, модель `atlas-brain`).
4. Ответ возвращается в Telegram. При сборке APK — файл или ссылка.

### CI/CD
1. Push в `main` → GitHub Actions.
2. Сборка Docker-образа → push в GHCR.
3. RunPod Pod использует свежий образ при следующем запуске.
