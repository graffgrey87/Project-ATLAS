# Сессия 2026-11-15 — отладка сборки Docker-образа

## Цель
Добиться успешной сборки образа в GitHub Actions (GHCR).

## Что сделано
- Заменён несуществующий базовый тег на `2.2.0-rc.229-cu1300-torch2130-ubuntu2404` (f2a9325).
- Исправлен SIGPIPE (код 141) в `sdkmanager --licenses` (f970a0b).
- Unity Hub: AppImage-URL отдаёт 404 → apt-репозиторий Unity, шаг не фатальный (4ccbc83).
- vLLM ограничен `<0.33`, torch зафиксирован constraint, добавлен `ARG GITHUB_REPOSITORY` (49e382a).

- Локальная проверка resolve (linux x86_64, py3.12): torch 2.13.0 + vllm 0.29.0 разрешаются без конфликта. Падение pip в CI (код 1) не объяснено; гипотеза: нехватка места на раннере.
- Коммит c94289d: шаг Free disk space в workflow, df -h и диагностика при падении pip install vllm.
- Коммит d4bfd87: docs/handoff.md (передача между агентами, экономия лимитов).
- Коммит 7a94101: финализация handoff notes.
- Сборка #43737516549 упала с exit code 2 на шаге `uv pip install`.
- Анализ причины exit code 2:
  1. В Ubuntu 24.04 (Noble) системный интерпретатор защищён PEP 668 (`EXTERNALLY-MANAGED`). Вызов `uv pip install --system` без `--break-system-packages` завершается с кодом 2.
  2. Файл ограничений создавался в `/tmp/pip-constraints.txt` в отдельном слое `RUN`, что создавало риск недоступности при кешировании или изоляции слоёв.
  3. В `docker-build.yml` параметр `BUILDKIT_PROGRESS` находился в секции `env`, а не `with: progress: plain` экшена `docker/build-push-action@v6`, из-за чего BuildKit скрывал подробный вывод ошибки.
- Реализованное решение:
  1. Объединение генерации ограничений, обновления pip/uv и установки зависимостей в единый атомарный шаг `RUN` в `docker/Dockerfile`.
  2. Добавлен флаг `--break-system-packages` для `uv pip install`.
  3. Файл ограничений перенесён в надёжный системный путь `/etc/pip-constraints.txt`.
  4. В `.github/workflows/docker-build.yml` добавлен `progress: plain` в секцию `with` для получения полного нескрытого вывода сборки.

## Что осталось
- Отправить изменения в ветку `main` и проконтролировать сборку в GitHub Actions.
- Выполнить smoke-тест импортов vLLM / PyTorch / aiogram.
- Произвести пробный запуск на RunPod.

## Ключевые решения
ADR-006.

## Замечание
В начале сессии PROJECT_MEMORY.md не был прочитан и не обновлялся до замечания пользователя.

## Следующий шаг
Проверить статус сборки в Actions.