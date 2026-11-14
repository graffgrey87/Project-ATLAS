# Соглашения проекта ATLAS

## Git

### Ветки
- `main` — стабильная версия, автоматически собирает Docker-образ через CI/CD.
- `dev` — текущая разработка.
- `feature/<название>` — отдельные функции.
- `fix/<название>` — исправления.

### Коммиты
Формат: [Conventional Commits](https://www.conventionalcommits.org/)
```
<тип>(<область>): <описание>

feat(docker): add Android SDK to Dockerfile
fix(bridge): handle TelegramConflictError on restart
docs(memory): update current focus after session
chore(ci): cache Docker layers in GitHub Actions
```

Допустимые типы: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`.

## Язык

| Контекст | Язык |
|----------|------|
| Код (переменные, функции, классы) | Английский |
| Комментарии в коде | Английский |
| Документация (docs/, README, PROJECT_MEMORY) | Русский |
| Сообщения коммитов | Английский |
| Логи и ошибки для пользователя | Русский |
| Cursor Rules (.mdc) | Русский (описание) + Английский (промпт) |

## Код

### Python
- Версия: 3.11+.
- Форматирование: совместимо с `ruff` (настройки по умолчанию).
- Type hints: обязательны для публичных функций.
- Docstrings: Google-стиль.

### Skills (навыки агента)
- Каждый скрипт — самодостаточный `__main__`.
- Аргументы — через `argparse`.
- Вывод в stdout — **только** JSON по контракту `skills/_schema.json`.
- Полные логи — в файл `/workspace/logs/<skill>-<timestamp>.log`.
- По умолчанию `errors-only`; `--verbose` для полного вывода.
- Поле `next_action` — всегда заполнено.

### Docker
- Объединять RUN-инструкции для уменьшения слоёв.
- Удалять кэши apt/pip в конце каждого RUN.
- Использовать `.dockerignore`.

## Структура директорий проектов

Рабочие проекты пользователя размещаются в `/workspace/projects/` на RunPod.
Репозиторий ATLAS (docker/, skills/, src/) — инфраструктурный и не содержит
пользовательских проектов.
