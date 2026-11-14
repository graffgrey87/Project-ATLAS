# Известные проблемы и обходные пути

## Unity CLI: активация лицензии

**Проблема:** Unity в headless-режиме (`-batchmode -nographics`) требует
активированной лицензии. Без неё сборка падает с ошибкой:
```
No valid Unity Editor license found. Please activate your license.
```

**Решение:**
1. Заполнить переменные в `.env` (см. `.env.example`):
   - **Personal (бесплатная):** `UNITY_LICENSE` — содержимое `.ulf` файла,
     сгенерированного через Unity Hub → Manual Activation на машине с GUI.
   - **Plus/Pro:** `UNITY_SERIAL`, `UNITY_EMAIL`, `UNITY_PASSWORD`.
2. Скрипт `skills/unity_build.py` при первом запуске автоматически:
   - Проверяет наличие `~/.local/share/unity3d/Unity/Unity_lic.ulf`.
   - Если файла нет — активирует через CLI или копирует `.ulf` из env.
   - Только после этого запускает сборку.

**Статус:** Ожидает реализации (Шаг 4).

---

## vLLM + PyTorch: возможный конфликт зависимостей

**Проблема:** `pip install vllm` в базовом образе `runpod/pytorch` может
переустановить несовместимую версию PyTorch или CUDA-библиотек.

**Решение:**
1. Smoke-тест после сборки: `python -c "import vllm; import torch; print('OK')"`.
2. Если конфликт:
   - **Fallback A:** Multi-stage build (стадия 1 собирает vLLM, стадия 2 копирует).
   - **Fallback B:** Два контейнера с bridge-сетью и shared volume.

**Статус:** Будет проверено на Шаге 1.

---

## nvidia-smi в контейнерах RunPod

**Проблема:** `nvidia-smi` может показывать **все** GPU физического хоста,
а не только выделенные контейнеру. Это приводит к неверному
`--tensor-parallel-size` и падению NCCL.

**Решение:** Определять GPU **только** через PyTorch:
```python
import torch
num_gpus = torch.cuda.device_count()  # видит только выделенные карты
```

**Статус:** Заложено в архитектуру (ADR-002).
