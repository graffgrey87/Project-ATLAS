# ADR-005: Выбор официальных MCP-серверов (GitHub, Playwright, Blender Lab)

## Статус
Принято

## Контекст
Агенту в Cursor IDE требуются внешние инструменты (MCP — Model Context Protocol) для прямого взаимодействия с системой контроля версий GitHub, браузером для проверки веб-приложений и 3D-редактором Blender.
Многие ранние MCP-серверы 2024–2025 годов были заброшены или архивированы, поэтому требовалось выбрать исключительно официальные, актуальные и поддерживаемые решения на ноябрь 2026 года.

## Решение
1. **GitHub MCP:** использовать официальный `github/github-mcp-server` (доступен через Docker `ghcr.io/github/github-mcp-server` или hosted-эндпоинт).
2. **Браузер MCP:** использовать официальный `@playwright/mcp` от Microsoft через `npx` с флагом `--headless`.
3. **Blender MCP:** использовать официальный сервер Blender Foundation / Blender Lab (`projects.blender.org/lab/blender_mcp`) через `uvx`.

## Альтернативы
- **@modelcontextprotocol/server-github:** архивирован и объявлен deprecated на npm. Отклонён.
- **@modelcontextprotocol/server-puppeteer:** архивирован, зависит от устаревшего Chromium с известными уязвимостями, расходует много токенов на скриншоты. Отклонён в пользу Playwright accessibility snapshots.
- **ahujasid/blender-mcp:** сторонний неофициальный форк. Отклонён в пользу официального сервера Blender Lab.

## Последствия
- ✅ Использование поддерживаемых инструментов с регулярными обновлениями протокола MCP.
- ✅ Экономия токенов при взаимодействии с веб-страницами благодаря дереву доступности Playwright.
- ✅ Полная совместимость с экосистемой Cursor IDE через файл `.cursor/mcp.json`.
- ⚠️ Для локального запуска GitHub MCP требуется Docker Desktop либо указание удалённого эндпоинта Copilot MCP.
- ⚠️ Для Blender MCP требуется локально установленная утилита `uv` и включённый аддон в Blender.

## Дата
2026-11-14
