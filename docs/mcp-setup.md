# Настройка MCP-серверов в Cursor IDE

В проекте ATLAS настроены три актуальных MCP-сервера (Model Context Protocol), предоставляющих агенту Cursor доступ к GitHub, браузеру и 3D-редактору Blender.

Файл конфигурации для Cursor: [`.cursor/mcp.json`](file:///F:/Project%20ATLAS/.cursor/mcp.json).

---

## 1. GitHub MCP Server (`github`)

- **Репозиторий:** [`github/github-mcp-server`](https://github.com/github/github-mcp-server) (официальный поддерживаемый сервер).
- **Статус аналогов:** Старый пакет `@modelcontextprotocol/server-github` в npm архивирован и объявлен deprecated.
- **Возможности:**
  - Поиск по коду, чтение репозиториев, коммитов и веток.
  - Управление Issues, Pull Requests и Sub-issues.
  - Просмотр логов запусков CI/CD GitHub Actions и оповещений безопасности.

### Варианты запуска:

#### Вариант A (По умолчанию в `.cursor/mcp.json` — Docker):
```json
{
  "command": "docker",
  "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server:latest"],
  "env": {
    "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}"
  }
}
```

#### Вариант B (Remote Hosted Endpoint без Docker):
Если на локальной машине не запущен Docker Desktop, в настройках Cursor (Features → MCP) можно указать remote SSE-эндпоинт:
- **URL:** `https://api.githubcopilot.com/mcp/`
- **Заголовок Authorization:** `Bearer <ВАШ_GITHUB_TOKEN>`

---

## 2. Playwright MCP Server (`playwright`)

- **Пакет:** [`@playwright/mcp`](https://www.npmjs.com/package/@playwright/mcp) (официальная рекомендация Microsoft).
- **Статус аналогов:** Устаревший сервер `@modelcontextprotocol/server-puppeteer` архивирован и использует уязвимые версии Chromium.
- **Возможности:**
  - Навигация по веб-страницам, клики, заполнение форм.
  - Использование структурированных accessibility snapshots (дерево доступности) вместо тяжелых скриншотов, что кардинально экономит токены контекста.
  - Эмуляция мобильных устройств и адаптивной верстки.

### Конфигурация:
```json
{
  "command": "npx",
  "args": ["-y", "@playwright/mcp@latest", "--headless"]
}
```

*Для запуска в видимом окне (для отладки) удалите флаг `--headless`.*

---

## 3. Blender Lab MCP Server (`blender`)

- **Репозиторий:** [`projects.blender.org/lab/blender_mcp`](https://projects.blender.org/lab/blender_mcp) (официальная разработка Blender Foundation / Blender Lab).
- **Статус аналогов:** Не путать со сторонним форком `ahujasid/blender-mcp`.
- **Возможности:**
  - Прямое управление 3D-сценой через Python API (`bpy`).
  - Процедурное создание мешей, назначение материалов и настройка камер/света.
  - Экспорт моделей в glTF/FBX и автоматизация рендеринга.

### Требования и установка:
1. **Blender 4.2+ / 5.x**:
   - Перейдите на страницу [blender.org/lab/mcp-server](https://www.blender.org/lab/mcp-server/).
   - Перетащите ссылку установки в окно Blender для установки официального аддона `BlenderMCP`.
   - В меню **Edit → Preferences → Add-ons** включите аддон и нажмите **Start MCP Server**.
2. **Менеджер пакетов `uv`**:
   - Убедитесь, что утилита `uv` установлена в системе (`pip install uv` или `winget install astral-sh.uv`).
   - Запуск сервера выполняется командой `uvx --from git+https://projects.blender.org/lab/blender_mcp.git blender-mcp`.

---

## Проверка работы в Cursor

1. Откройте Cursor IDE.
2. Перейдите в **Settings → Features → MCP Servers**.
3. Убедитесь, что все три сервера горят зеленым индикатором готовности.
4. В чате агента Cursor доступны инструменты с префиксами `github_*`, `playwright_*` и `blender_*`.
