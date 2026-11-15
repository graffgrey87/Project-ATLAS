# PROJECT_MEMORY.md — ATLAS

> Единственный источник истины о текущем состоянии проекта.
> Читается агентом в начале каждой сессии. Максимум 300 строк.

---

## 1. Что это за проект

**ATLAS** (Autonomous Vibe-Coding Environment) — автономная среда разработки,
работающая на RunPod (≥48 ГБ VRAM, CUDA 13.0). Единый Docker-контейнер содержит
LLM-мозг (Qwen3.6-35B-A3B через vLLM), инструменты сборки (Android SDK, Unity,
Godot, Blender, Node.js) и Telegram-бот для мобильного управления. Локальное
управление — через Cursor IDE по SSH.

---

## 2. Текущий фокус

| Поле           | Значение                                      |
|----------------|-----------------------------------------------|
| **Задача**     | Боевая эксплуатация и тестирование среды ATLAS на RunPod |
| **Статус**     | 🟢 Инстанс успешно развёрнут на RunPod (GPU NVIDIA L40, 48 ГБ VRAM). Модель `Qwen/Qwen3.6-35B-A3B-FP8` (`atlas-brain`) загружена и активна в vLLM на порту 8000. Telegram-бот `@my_atlas_dev_bot` онлайн. Сервер артефактов слушает порт 8080. |
| **Блокер**     | Отсутствует. Все сервисы работают штатно. |
| **Следующий**  | Тестирование команд в Telegram (`/start`, запрос кода, `/save`), сборка пробного Android APK через skills, проверка Cursor Remote-SSH. |

---

## 3. Архитектура

Подробная схема: [docs/architecture.md](docs/architecture.md)

**Краткая суть:** один контейнер `atlas` на RunPod Community Cloud (без платных сетевых дисков), supervisor как PID 1,
два управляемых процесса (vLLM на :8000, mobile_bridge.py). Входная точка entrypoint.sh автоматически восстанавливает
репозиторий из GitHub, определяет GPU, контролирует порог диска в 40 ГБ и загружает модель. GitHub является единственным
постоянным источником истины. Команда `/save` выгружает изменения перед Terminate пода.

---

## 4. Соглашения

Подробности: [docs/conventions.md](docs/conventions.md)

- **Ветки:** `main` (стабильный образ), `dev` (текущая работа), `feature/*`.
- **Коммиты:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`).
- **Язык кода:** английский (переменные, комментарии).
- **Язык документации:** русский.
- **Skills:** всегда возвращают JSON-контракт (см. `skills/_schema.json`).

---

## 5. Принятые решения (ADR)

Полные версии: [docs/adr/](docs/adr/)

| # | Решение | Дата | Статус |
|---|---------|------|--------|
| 001 | Один контейнер + supervisor вместо multi-container | 2026-11-14 | Принято |
| 002 | Определение GPU через PyTorch, не nvidia-smi | 2026-11-14 | Принято |
| 003 | Qwen3.6-35B-A3B: FP8 для Ada+, AWQ для Ampere | 2026-11-14 | Принято |
| 004 | Авторизация Telegram по числовому user ID | 2026-11-14 | Принято |
| 005 | Официальные MCP-серверы (GitHub, Playwright, Blender) | 2026-11-14 | Принято |
| 006 | Базовый образ `2.2.0-rc.229-cu1300-torch2130-ubuntu2404`, vLLM `>=0.28,<0.33`, torch зафиксирован constraint | 2026-11-15 | Принято |
| 007 | Эфемерный диск Community Cloud (75–80 ГБ) + авто-синхронизация с GitHub | 2026-11-15 | Принято |

---

## 6. Известные проблемы

Подробности: [docs/known-issues.md](docs/known-issues.md)

- **Unity CLI:** требует активации лицензии перед headless-сборкой.
  См. `.env.example` → `UNITY_LICENSE` / `UNITY_SERIAL`.
- **vLLM + PyTorch:** `vllm>=0.28.0` ставил 0.33.0 (нужен torch 2.14, в образе 2.13.0).
  Решено ограничением `<0.33` и constraint на torch (ADR-006). Не проверено сборкой.
  Fallback: multi-stage build или двухконтейнерная схема.
- **Теги RunPod:** тег `1.0.3-cu1300-torch2130-ubuntu2404` не существует; нужный тег
  сверять с Docker Hub (`runpod/pytorch`), а не брать из памяти.
- **Unity в образе:** URL `UnityHub.AppImage` отдаёт 404; Hub ставится из apt-репозитория
  Unity, установка Editor best-effort (может потребоваться доустановка в контейнере).
- **Android sdkmanager:** `yes | sdkmanager` падал с кодом 141 (SIGPIPE) — исправлено.
- **Реальный GPU на RunPod:** успешно проверено на NVIDIA L40 (48 ГБ VRAM).
- **vLLM Tool Calling:** добавлены флаги `--enable-auto-tool-choice --tool-call-parser hermes` в `docker/entrypoint.sh` и реализован graceful fallback в `src/mobile_bridge.py`.
- **Community Cloud Sync:** репозиторий автоматически восстанавливается из GitHub на старте; команда `/save` выполняет push изменений в репозиторий.

---

## 7. Структура репозитория

```
Project ATLAS/
├── .cursor/rules/          # Cursor IDE промпты (.mdc)
├── .github/workflows/      # CI/CD (GitHub Actions → GHCR)
├── docker/                 # Dockerfile, entrypoint.sh, supervisord.conf
├── skills/                 # Автономные скрипты для Function Calling
├── src/                    # mobile_bridge.py, vision_bridge.py
├── docs/                   # Архитектура, ADR, соглашения, known-issues
├── sessions/               # Журналы сессий (YYYY-MM-DD-тема.md)
├── .env.example            # Шаблон переменных окружения
├── docker-compose.yml      # Оркестрация контейнера
├── PROJECT_MEMORY.md       # ← ВЫ ЗДЕСЬ
└── README.md               # Инструкция по запуску
```

---

## 8. Как со мной работать (инструкции агенту)

1. **В начале сессии** — прочитай этот файл целиком.
2. **Поиск** — используй targeted search (`grep`, чтение конкретных файлов).
   НЕ делай `ls -R` и не читай все файлы подряд.
3. **Визуальная проверка** — один скриншот на итерацию, с crop при возможности.
4. **Контекст** — при приближении к лимиту предложи компакцию:
   сохрани состояние в `sessions/YYYY-MM-DD-тема.md`, обнови этот файл,
   продолжи с чистого окна.
5. **Skills** — вызывай скрипты из `skills/`, читай только JSON-вывод.
   Полные логи — в `/workspace/logs/`, запрашивай точечно через `grep`.
6. **Коммиты** — Conventional Commits, атомарные, с осмысленным сообщением.
7. **Обновление памяти** — после каждого значимого изменения обнови
   раздел «Текущий фокус» в этом файле.
8. **Передача между агентами** — чек-лист и шаблоны сообщений в [docs/handoff.md](docs/handoff.md). При смене агента или конце лимита выполняй его.
