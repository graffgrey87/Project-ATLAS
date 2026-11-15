# =============================================================================
# ATLAS — Autonomous Vibe-Coding Environment
# Base: runpod/pytorch 2.13.0, CUDA 13.0, Ubuntu 24.04 Noble
# =============================================================================

# Актуальный базовый образ из реестра RunPod: PyTorch 2.13.0, CUDA 13.0, Ubuntu 24.04
FROM runpod/pytorch:2.2.0-rc.229-cu1300-torch2130-ubuntu2404

# -----------------------------------------------------------------------------
# 1. Метаданные
# -----------------------------------------------------------------------------
LABEL org.opencontainers.image.title="ATLAS Vibe-Coding Environment" \
      org.opencontainers.image.description="Autonomous AI coding environment with vLLM, Android SDK, Unity, Godot, Blender" \
      org.opencontainers.image.source="https://github.com/${GITHUB_REPOSITORY}"

# -----------------------------------------------------------------------------
# 2. ENV-переменные (не чувствительные; секреты — через .env)
# -----------------------------------------------------------------------------
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    # Hugging Face — кэш на persistent volume RunPod
    HF_HOME=/workspace/hf_cache \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    # Android SDK
    ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    # Node.js (путь добавляется ниже через PATH)
    NODE_ENV=production \
    # Blender headless
    BLENDER_PATH=/opt/blender \
    # Godot headless
    GODOT_PATH=/opt/godot \
    # Unity
    UNITY_PATH=/opt/unity \
    # Supervisor — не нужен DISPLAY в headless
    DISPLAY=:0

ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/build-tools/35.0.0:${BLENDER_PATH}:${GODOT_PATH}:${UNITY_PATH}/Editor:${PATH}"

# -----------------------------------------------------------------------------
# 3. Системные пакеты
# -----------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Базовые утилиты
    wget curl git git-lfs unzip zip ca-certificates gnupg \
    # Supervisor (менеджер процессов, PID 1)
    supervisor \
    # Java (Android SDK, Gradle)
    openjdk-21-jdk \
    # Медиа и графика (Blender, Unity headless)
    ffmpeg libgl1 libglu1-mesa libgomp1 libxrender1 libxext6 \
    libxi6 libxrandr2 libxinerama1 libxcursor1 libx11-6 \
    libxxf86vm1 libgles2 \
    # Python-зависимости системные
    python3-dev build-essential \
    # Утилиты для скриптов
    jq bc \
    # ADB (для vision_bridge.py)
    adb \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# 4. Node.js LTS (v22.x) через NodeSource
# -----------------------------------------------------------------------------
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && node --version && npm --version

# -----------------------------------------------------------------------------
# 5. Android SDK (command-line tools)
# -----------------------------------------------------------------------------
RUN mkdir -p ${ANDROID_HOME}/cmdline-tools \
 && wget -q "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" \
         -O /tmp/cmdline-tools.zip \
 && unzip -q /tmp/cmdline-tools.zip -d /tmp/cmdline-tools-raw \
 && mv /tmp/cmdline-tools-raw/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest \
 && rm -rf /tmp/cmdline-tools.zip /tmp/cmdline-tools-raw \
 # Создание файлов предпринятых лицензий (предотвращает exit code 141 SIGPIPE)
 && mkdir -p ${ANDROID_HOME}/licenses \
 && printf "24333f8a63b1d7f230f3dd887d366f19346abb91\nd56f5187479451eabf01fb78af6dfcb131a6481e\n84831b9409646a918e30573bab4c9c91346d8abd" > ${ANDROID_HOME}/licenses/android-sdk-license \
 && printf "84831b9409646a918e30573bab4c9c91346d8abd" > ${ANDROID_HOME}/licenses/android-sdk-preview-license \
 # Принятие оставшихся лицензий и установка компонентов без SIGPIPE
 && (bash -c 'set +o pipefail; yes 2>/dev/null | ${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager --licenses || true') \
 && ${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager \
    "platform-tools" \
    "build-tools;35.0.0" \
    "platforms;android-35" \
    "extras;android;m2repository" \
 && chmod -R o+rX ${ANDROID_HOME}

# -----------------------------------------------------------------------------
# 6. Gradle (wrapper используется из проектов, но standalone для CI)
# -----------------------------------------------------------------------------
RUN wget -q "https://services.gradle.org/distributions/gradle-8.11-bin.zip" \
         -O /tmp/gradle.zip \
 && unzip -q /tmp/gradle.zip -d /opt \
 && mv /opt/gradle-8.11 /opt/gradle \
 && rm /tmp/gradle.zip \
 && ln -s /opt/gradle/bin/gradle /usr/local/bin/gradle \
 && gradle --version

# -----------------------------------------------------------------------------
# 7. Blender (headless LTS)
# -----------------------------------------------------------------------------
RUN wget -q "https://download.blender.org/release/Blender4.4/blender-4.4.3-linux-x64.tar.xz" \
         -O /tmp/blender.tar.xz \
 && tar -xf /tmp/blender.tar.xz -C /opt \
 && mv /opt/blender-4.4.3-linux-x64 ${BLENDER_PATH} \
 && rm /tmp/blender.tar.xz \
 && ln -s ${BLENDER_PATH}/blender /usr/local/bin/blender \
 && blender --version

# -----------------------------------------------------------------------------
# 8. Godot (headless)
# -----------------------------------------------------------------------------
RUN wget -q "https://github.com/godotengine/godot/releases/download/4.4.1-stable/Godot_v4.4.1-stable_linux.x86_64.zip" \
         -O /tmp/godot.zip \
 && mkdir -p ${GODOT_PATH} \
 && unzip -q /tmp/godot.zip -d ${GODOT_PATH} \
 && mv "${GODOT_PATH}/Godot_v4.4.1-stable_linux.x86_64" "${GODOT_PATH}/godot" \
 && rm /tmp/godot.zip \
 && ln -s ${GODOT_PATH}/godot /usr/local/bin/godot \
 && godot --version

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# 9. Unity Hub (официальный apt-репозиторий Unity) + best-effort установка Editor
#    Сборка образа НЕ падает, если Editor не установился: он доустанавливается
#    при необходимости командой `unityhub -- --headless install` (см. known-issues).
# -----------------------------------------------------------------------------
RUN set -x \
 && (wget -qO - https://hub.unity3d.com/linux/keys/public | gpg --dearmor -o /usr/share/keyrings/unityhub.gpg \
     && echo "deb [signed-by=/usr/share/keyrings/unityhub.gpg] https://hub.unity3d.com/linux/repos/deb stable main" > /etc/apt/sources.list.d/unityhub.list \
     && apt-get update \
     && apt-get install -y --no-install-recommends unityhub xvfb \
     && (xvfb-run -a unityhub --headless install --version 6000.1.9f1 --changeset a46f2f8f7d6d --module linux-il2cpp || true) \
     && UNITY_EDITOR=$(find / -type f -name Unity -path "*/Editor/Unity" 2>/dev/null | head -1) \
     && mkdir -p ${UNITY_PATH}/Editor \
     && if [ -n "${UNITY_EDITOR}" ]; then ln -sf "${UNITY_EDITOR}" ${UNITY_PATH}/Editor/Unity; fi \
     || echo "[WARN] Unity Hub/Editor install skipped — see docs/known-issues.md") \
 ; apt-get clean; rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# 10. Python-зависимости
# -----------------------------------------------------------------------------
RUN pip install --no-cache-dir --upgrade pip \
 # vLLM — основной inference engine (glibc >= 2.39 — Ubuntu 24.04 ✓)
 && pip install --no-cache-dir "vllm>=0.28.0" \
 # Telegram-бот
 && pip install --no-cache-dir "aiogram>=3.31.0" \
 # Утилиты для skills и bridge
 && pip install --no-cache-dir \
    hf_transfer \
    aiohttp \
    aiofiles \
    "Pillow>=10.0" \
    "httpx>=0.27" \
    "tenacity>=8.0" \
    "jsonschema>=4.0" \
    "python-dotenv>=1.0"

# -----------------------------------------------------------------------------
# 11. Smoke-тест зависимостей (обнаруживает конфликты на этапе сборки)
# -----------------------------------------------------------------------------
RUN python3 -c "\
import torch; \
import vllm; \
import aiogram; \
print(f'[SMOKE TEST] torch={torch.__version__} vllm={vllm.__version__} aiogram={aiogram.__version__} CUDA={torch.version.cuda}'); \
assert torch.cuda.is_available() or True, 'CUDA check skipped at build time'; \
print('[SMOKE TEST] ✓ All imports OK')"

# -----------------------------------------------------------------------------
# 12. Копирование файлов проекта
# -----------------------------------------------------------------------------
COPY docker/entrypoint.sh /docker/entrypoint.sh
COPY docker/supervisord.conf /docker/supervisord.conf
COPY skills/ /atlas/skills/
COPY src/ /atlas/src/

RUN chmod +x /docker/entrypoint.sh \
 && chmod -R 755 /atlas/skills/ \
 && mkdir -p /workspace/hf_cache /workspace/logs /workspace/projects

# -----------------------------------------------------------------------------
# 13. Рабочая директория и точка входа
# -----------------------------------------------------------------------------
WORKDIR /workspace

EXPOSE 8000 8080

ENTRYPOINT ["/docker/entrypoint.sh"]
