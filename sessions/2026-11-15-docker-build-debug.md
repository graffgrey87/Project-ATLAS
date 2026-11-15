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
- Текущая правка: подключение `uv` для быстрой установки vLLM, добавление `--extra-index-url https://download.pytorch.org/whl/cu130` (индекс CUDA 13.0) и включение `BUILDKIT_PROGRESS: plain` в workflow для полного развёрнутого лога сборки.

## Что осталось
- Дождаться сборки с `BUILDKIT_PROGRESS: plain`.
- Smoke-тест импортов в CI, затем первый запуск на RunPod.

## Ключевые решения
ADR-006.

## Замечание
В начале сессии PROJECT_MEMORY.md не был прочитан и не обновлялся до замечания пользователя.

## Следующий шаг
Проверить статус сборки в Actions.