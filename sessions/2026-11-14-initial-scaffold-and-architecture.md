# Журнал сессии: 2026-11-14 — Архитектура и первоначальное развёртывание ATLAS

## 1. Цель сессии
Спроектировать и полностью реализовать инфраструктуру, конфигурации и кодовую базу системы **ATLAS**:
автономной среды vibe-кодинга на RunPod с управлением из Cursor IDE и Telegram на Android.

## 2. Что сделано
- **Шаг 0**: Создан скелет репозитория, `PROJECT_MEMORY.md`, соглашения `docs/conventions.md`, карта архитектуры `docs/architecture.md`, `docs/known-issues.md` и ADR-000..004.
- **Шаг 1**: Подготовлен `docker/Dockerfile` (PyTorch 2.13, CUDA 13.0, Ubuntu 24.04 Noble, Android SDK 35, Gradle 8.11, Blender 4.4.3, Godot 4.4.1, Unity 6, Node.js 22, vLLM, aiogram), `docker-compose.yml`, `.env.example`, `.dockerignore` и `.gitattributes`.
- **Шаг 2**: Развернут CI/CD pipeline в GitHub Actions (`.github/workflows/docker-build.yml`) для автосборки и публикации в GHCR с кэшированием слоев и smoke-тестом импортов.
- **Шаг 3**: Разработан `docker/entrypoint.sh` с **Zero-Config GPU адаптацией на PyTorch**:
  - `compute_cap >= 8.9` -> `Qwen/Qwen3.6-35B-A3B-FP8` + `--kv-cache-dtype fp8` (порог 44 ГБ VRAM).
  - `compute_cap < 8.9` -> `QuantTrio/Qwen3.6-35B-A3B-AWQ` + стандартный KV-кэш (порог 28 ГБ VRAM).
  - Smart Cache Cleanup при остатке места < 40 ГБ на `/workspace`.
  - Оповещение об ошибках VRAM в Telegram без зацикливания.
  - Менеджер процессов `docker/supervisord.conf` (PID 1).
- **Шаг 4**: Реализована библиотека навыков агента (`skills/`):
  - `_schema.json` (единый JSON-контракт отчёта).
  - `skill_utils.py` (валидация, изоляция логов, форматирование).
  - `compile_android.py` (Gradle сборка, поиск APK, парсинг ошибок Kotlin/Java).
  - `unity_build.py` (headless сборка с автоматической проверкой/активацией лицензии через `.env`).
  - `blender_render.py` (headless Cycles/EEVEE рендер, парсинг логов).
- **Шаг 5**: Создана система ролевых промптов в актуальном стандарте Cursor (`.cursor/rules/*.mdc`):
  - `context-management.mdc` (`alwaysApply: true`), `unity-senior.mdc`, `android-expert.mdc`, `researcher.mdc`, `blender-tech-artist.mdc`.
- **Шаг 6**: Разработан мобильный клиент и система визуального контроля:
  - `src/mobile_bridge.py`: aiogram 3.x, строгая авторизация по числовому `ALLOWED_TELEGRAM_ID`, vLLM Vision, Function Calling, доставка APK (<=50 МБ напрямую, >50 МБ через HTTP-сервер на `:8080` и RunPod Proxy).
  - `src/vision_bridge.py`: захват скриншотов Android по ADB и окон X11/Unity, кадрирование и экономия токенов VLM.
- **Шаг 7**: Настроены актуальные MCP-серверы в `.cursor/mcp.json` (`github`, `playwright`, `blender`) и составлено руководство `docs/mcp-setup.md`. Зафиксирован `docs/adr/005-mcp-integrations.md`.
- **Шаг 8**: Написана исчерпывающая документация `README.md` с диаграммами архитектуры, таблицей совместимости GPU, инструкцией запуска и структурой репозитория.

## 3. Ключевые решения и артефакты
- Все изменения синхронизированы с удалённым репозиторием [https://github.com/graffgrey87/Project-ATLAS](https://github.com/graffgrey87/Project-ATLAS).
- Оформлено 5 Architecture Decision Records в `docs/adr/`.
- Файл памяти `PROJECT_MEMORY.md` приведен в финальное состояние.

## 4. Следующий шаг
Аренда инстанса на RunPod (от 48 ГБ VRAM: 1× L40S или 2× RTX 4090), первый запуск контейнера, заполнение `.env` и верификация взаимодействия через Cursor IDE и Telegram со смартфона.
