#!/usr/bin/env python3
# =============================================================================
# ATLAS — src/mobile_bridge.py
# Мобильный мост (Telegram-бот) на базе aiogram 3.x для автономного vibe-кодинга
# со смартфона: чат, Vision VLM, Function Calling и раздача собранных APK.
# =============================================================================
import asyncio
import base64
from datetime import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiofiles
from aiohttp import web
import httpx
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from openai import AsyncOpenAI, BadRequestError
from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, FSInputFile, Message

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from src.usage_tracker import TaskUsage, UsageTracker
except ImportError:
    from usage_tracker import TaskUsage, UsageTracker

# -----------------------------------------------------------------------------
# 1. Логирование и конфигурация
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("mobile_bridge")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
raw_allowed_id = os.environ.get("ALLOWED_TELEGRAM_ID", "").strip()

try:
    ALLOWED_TELEGRAM_ID: Optional[int] = int(raw_allowed_id) if raw_allowed_id else None
except ValueError:
    logger.error(f"ALLOWED_TELEGRAM_ID должен быть числовым ID! Получено: '{raw_allowed_id}'")
    ALLOWED_TELEGRAM_ID = None

ARTIFACT_SERVER_PORT = int(os.environ.get("ARTIFACT_SERVER_PORT", "8080"))
RUNPOD_POD_ID = os.environ.get("RUNPOD_POD_ID", "").strip()
ENABLE_THINKING = os.environ.get("ATLAS_ENABLE_THINKING", "false").lower() in ("true", "1", "yes")

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace" if os.name != "nt" else ".")).resolve()
ARTIFACTS_DIR = WORKSPACE_DIR / "artifacts"
SESSIONS_DIR = WORKSPACE_DIR / "sessions"
ACTIVE_CONFIG_PATH = SESSIONS_DIR / "active_config.json"
USAGE_STATS_PATH = SESSIONS_DIR / "usage_stats.json"
MAX_SAVED_HISTORY = 100
CONTEXT_WINDOW_SIZE = 20

for _d in (ARTIFACTS_DIR, SESSIONS_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def clean_llm_response(content: str) -> str:
    """
    Очищает ответ модели от тегов рассуждений (<think>...</think>, Thinking Process)
    и предотвращает замусоривание чата черновиками и логами мышления.
    """
    if not content:
        return ""

    # 1. Если модель вернула закрывающий тег </think>, отрезаем всё до него
    if "</think>" in content:
        content = content.split("</think>")[-1]

    # 2. Удаление полных парных тегов <think>...</think>
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

    # 3. Удаление висячих тегов
    content = content.replace("<think>", "").replace("</think>", "")

    # 4. Если в начале осталась фраза рассуждений без тегов (Here's a thinking process: ...)
    if re.search(r"^(?:Here['’]s a thinking process:?|Thinking Process:?)", content.strip(), re.IGNORECASE):
        parts = re.split(r"\n\s*\n", content.strip())
        if len(parts) > 1:
            content = "\n\n".join(parts[1:])

    return content.strip()

# -----------------------------------------------------------------------------
# 2. Безопасность: Middleware строгой проверки числового ID
# -----------------------------------------------------------------------------
class StrictUserAuthMiddleware(BaseMiddleware):
    """
    Проверяет числовой ID пользователя Telegram.
    Сообщения от неавторизованных ID молча игнорируются (защита от GHSA-mj5r-hh7j-4gxf).
    """
    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Any],
        event: types.TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user or ALLOWED_TELEGRAM_ID is None:
            logger.warning("Отклонено: ALLOWED_TELEGRAM_ID не настроен в .env!")
            return

        if user.id != ALLOWED_TELEGRAM_ID:
            logger.warning(f"Попытка несанкционированного доступа от ID: {user.id} (@{user.username})")
            return

        return await handler(event, data)


# -----------------------------------------------------------------------------
# 3. Инструменты агента (Function Calling / Tool Execution)
# -----------------------------------------------------------------------------
TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Прочитать содержимое файла в /workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Относительный или абсолютный путь к файлу"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Создать или перезаписать ОДИН файл в /workspace (для 2 и более файлов используй write_files_batch)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"},
                    "content": {"type": "string", "description": "Содержимое файла"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_files_batch",
            "description": "Пакетно создать или перезаписать сразу несколько файлов за один вызов (обязательно при работе с 2 и более файлами)",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "description": "Список объектов {path, content}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"}
                            },
                            "required": ["path", "content"]
                        }
                    }
                },
                "required": ["files"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit_all",
            "description": "Автокоммит всех текущих изменений в Git для синхронизации с Cursor IDE",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Текст сообщения коммита"}
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compile_android_project",
            "description": "Собрать Android проект через Gradle с получением готового APK",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_dir": {"type": "string", "description": "Путь к директории проекта Android"},
                    "build_type": {"type": "string", "enum": ["debug", "release"], "description": "Тип сборки"}
                },
                "required": ["project_dir"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "test_android_project",
            "description": "Запустить автотесты Android проекта (Unit/Robolectric + lintDebug) для проверки логики, UI и поиска багов до сборки APK",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_dir": {"type": "string", "description": "Путь к директории проекта Android"},
                    "include_lint": {"type": "boolean", "description": "Включить проверку lintDebug (по умолчанию true)"}
                },
                "required": ["project_dir"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell_command",
            "description": "Выполнить безопасную shell-команду в директории /workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Команда shell"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Поиск актуальной информации в интернете через DuckDuckGo (документация 2025-2026, версии библиотек, новости, API)",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Поисковый запрос"},
                    "max_results": {"type": "integer", "description": "Максимум результатов (по умолчанию 5)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_web_page",
            "description": "Скачать веб-страницу по URL и извлечь чистый текст (без HTML/скриптов/навигации, до 6000 символов)",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Полный HTTP/HTTPS URL страницы"}
                },
                "required": ["url"]
            }
        }
    }
]


def resolve_safe_path(target_path: str) -> Path:
    """Обеспечивает работу внутри /workspace или текущего проекта."""
    p = Path(target_path)
    if not p.is_absolute():
        p = WORKSPACE_DIR / p
    return p.resolve()


def git_sync_push(message: str) -> Dict[str, Any]:
    """
    Выполняет git add, git commit и автоматический git push в удалённый репозиторий.
    Обеспечивает непрерывную сохранность кода при внезапном Terminate пода в RunPod Community Cloud.
    """
    if not (WORKSPACE_DIR / ".git").exists():
        return {"status": "skipped", "message": "Директория /workspace не содержит инициализированного git-репозитория."}

    # Настройка автора коммитов по умолчанию
    subprocess.run(["git", "config", "user.name", os.environ.get("GIT_USER_NAME", "ATLAS Mobile Bridge")], cwd=str(WORKSPACE_DIR), capture_output=True)
    subprocess.run(["git", "config", "user.email", os.environ.get("GIT_USER_EMAIL", "atlas@project.local")], cwd=str(WORKSPACE_DIR), capture_output=True)

    # Аутентификация remote URL при наличии GITHUB_TOKEN и PROJECT_REPO_URL
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo_url = os.environ.get("PROJECT_REPO_URL", "").strip()
    if token and repo_url and repo_url.startswith("https://github.com/"):
        auth_url = f"https://{token}@{repo_url[len('https://'):]}"
        subprocess.run(["git", "remote", "set-url", "origin", auth_url], cwd=str(WORKSPACE_DIR), capture_output=True)

    # 1. git add
    subprocess.run(["git", "add", "-A"], cwd=str(WORKSPACE_DIR), capture_output=True)

    # 2. git commit
    commit_res = subprocess.run(["git", "commit", "-m", message], cwd=str(WORKSPACE_DIR), capture_output=True, text=True)
    commit_out = (commit_res.stdout or commit_res.stderr or "").strip()

    # 2.5. Автоподтягивание удалённых коммитов (защита от non-fast-forward при работе с IDE и подом)
    rebase_res = subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=str(WORKSPACE_DIR), capture_output=True, text=True)
    if rebase_res.returncode != 0:
        subprocess.run(["git", "rebase", "--abort"], cwd=str(WORKSPACE_DIR), capture_output=True)

    # 3. git push
    push_res = subprocess.run(["git", "push", "origin", "main"], cwd=str(WORKSPACE_DIR), capture_output=True, text=True)
    if push_res.returncode != 0:
        push_res = subprocess.run(["git", "push", "origin", "HEAD"], cwd=str(WORKSPACE_DIR), capture_output=True, text=True)

    push_out = (push_res.stdout or push_res.stderr or "").strip()

    # Текущий SHA
    sha_res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(WORKSPACE_DIR), capture_output=True, text=True)
    current_sha = sha_res.stdout.strip() if sha_res.returncode == 0 else "unknown"

    return {
        "status": "ok" if push_res.returncode == 0 else "push_warning",
        "sha": current_sha,
        "commit_output": commit_out,
        "push_output": push_out
    }


async def execute_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Исполняет запрошенный LLM-инструмент и возвращает результат."""
    logger.info(f"[Tool Calling] Вызов инструмента: {name}({arguments})")
    try:
        if name == "read_file":
            target = resolve_safe_path(arguments["path"])
            if not target.exists():
                return {"error": f"Файл не найден: {target}"}
            async with aiofiles.open(target, mode="r", encoding="utf-8", errors="replace") as f:
                content = await f.read(50000)  # До 50KB текста за вызов
            return {"status": "ok", "path": str(target), "content": content}

        elif name == "write_file":
            target = resolve_safe_path(arguments["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(target, mode="w", encoding="utf-8") as f:
                await f.write(arguments["content"])
            return {
                "status": "ok",
                "message": f"Файл {target} записан ({len(arguments['content'])} символов)."
            }

        elif name == "write_files_batch":
            files_list = arguments.get("files", [])
            written = []
            for item in files_list:
                target = resolve_safe_path(item["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                async with aiofiles.open(target, mode="w", encoding="utf-8") as f:
                    await f.write(item["content"])
                written.append(f"{target.name} ({len(item['content'])} симв.)")
            return {
                "status": "ok",
                "count": len(written),
                "written": written
            }

        elif name == "git_commit_all":
            msg = arguments.get("message", "vibe-coding update via mobile_bridge")
            sync_res = git_sync_push(msg)
            return {
                "status": "ok",
                "sha": sync_res.get("sha"),
                "git_output": sync_res.get("commit_output") or "No changes",
                "push_output": sync_res.get("push_output") or "Synced"
            }

        elif name == "compile_android_project":
            pdir = resolve_safe_path(arguments["project_dir"])
            btype = arguments.get("build_type", "debug")
            skill_script = Path("/atlas/skills/compile_android.py")
            if not skill_script.exists():
                skill_script = Path(__file__).resolve().parent.parent / "skills" / "compile_android.py"

            proc = subprocess.run(
                [sys.executable, str(skill_script), "--project-dir", str(pdir), "--build-type", btype],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            try:
                report = json.loads(proc.stdout)
                if report.get("status") == "success":
                    git_sync_push(f"build(android): successful {btype} build")
                return report
            except Exception:
                return {"status": "failed", "raw_output": proc.stdout, "stderr": proc.stderr}

        elif name == "test_android_project":
            pdir = resolve_safe_path(arguments["project_dir"])
            include_lint = arguments.get("include_lint", True)
            skill_script = Path("/atlas/skills/test_android.py")
            if not skill_script.exists():
                skill_script = Path(__file__).resolve().parent.parent / "skills" / "test_android.py"

            cmd = [sys.executable, str(skill_script), "--project-dir", str(pdir)]
            if not include_lint:
                cmd.append("--no-lint")

            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                return json.loads(proc.stdout)
            except Exception:
                return {"status": "failed", "raw_output": proc.stdout, "stderr": proc.stderr}

        elif name == "run_shell_command":
            cmd = arguments["command"]
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(WORKSPACE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120
            )
            return {"returncode": proc.returncode, "output": (proc.stdout or "")[:4000]}

        elif name == "search_web":
            query = arguments["query"]
            max_results = int(arguments.get("max_results", 5))
            def _do_search():
                with DDGS() as ddgs:
                    res = list(ddgs.text(query, max_results=max_results, backend="html"))
                    if not res:
                        res = list(ddgs.text(query, max_results=max_results))
                    return res
            raw_results = await asyncio.to_thread(_do_search)
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                }
                for r in raw_results
            ]
            if not results:
                return {"status": "empty", "query": query, "results": [], "message": "Результаты не найдены."}
            return {"status": "ok", "query": query, "results": results}

        elif name == "fetch_web_page":
            url = arguments["url"]
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
                    resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 ATLAS-Bot/1.0"})
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
                        tag.decompose()
                    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
                    clean_text = "\n".join(line for line in lines if line)
                    return {
                        "status": "ok",
                        "url": str(resp.url),
                        "length": len(clean_text),
                        "content": clean_text[:6000]
                    }
            except httpx.HTTPStatusError as http_err:
                return {"status": "error", "url": url, "error": f"HTTP {http_err.response.status_code}: страница недоступна"}
            except httpx.RequestError as req_err:
                return {"status": "error", "url": url, "error": f"Ошибка соединения/таймаут: {req_err}"}

        else:
            return {"error": f"Неизвестный инструмент: {name}"}

    except Exception as ex:
        logger.exception(f"Исключение при вызове {name}: {ex}")
        return {"error": f"Ошибка выполнения: {str(ex)}"}


# -----------------------------------------------------------------------------
# 4. HTTP-сервер раздачи артефактов (> 50 МБ)
# -----------------------------------------------------------------------------
async def handle_artifact_download(request: web.Request) -> web.Response:
    filename = request.match_info.get("filename", "")
    target = (ARTIFACTS_DIR / filename).resolve()
    if not target.exists() or not str(target).startswith(str(ARTIFACTS_DIR)):
        return web.Response(status=404, text="Artifact not found")
    return web.FileResponse(target)


async def start_artifact_server() -> web.AppRunner:
    """Запускает фоновый легковесный HTTP-сервер для отдачи файлов APK > 50 МБ."""
    app = web.Application()
    app.router.add_get("/artifacts/{filename}", handle_artifact_download)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", ARTIFACT_SERVER_PORT)
    await site.start()
    logger.info(f"[Artifact Server] Запущен на порту {ARTIFACT_SERVER_PORT}")
    return runner


def get_artifact_url(filename: str) -> str:
    """Генерирует прямую ссылку на артефакт через RunPod Proxy или локальный порт."""
    if RUNPOD_POD_ID:
        return f"https://{RUNPOD_POD_ID}-{ARTIFACT_SERVER_PORT}.proxy.runpod.net/artifacts/{filename}"
    return f"http://localhost:{ARTIFACT_SERVER_PORT}/artifacts/{filename}"


# -----------------------------------------------------------------------------
# 5. Интеграция с vLLM и персистентная память диалогов
# -----------------------------------------------------------------------------
user_conversations: Dict[int, List[Dict[str, Any]]] = {}


def get_system_prompt() -> str:
    """Формирует системный промпт с текущей датой (2026 год) и инструкциями по поиску."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    return f"""Вы — ATLAS: автономная среда vibe-кодинга и персональный AI-инженер.
Текущая дата: {today_str} (сейчас 2026 год).
Вы работаете на сервере RunPod с прямым доступом к файловой системе /workspace и навыкам сборки.
Вы общаетесь с владельцем через мобильный интерфейс Telegram.
Ваши ответы должны быть краткими, деловыми, конкретными и строго по делу.

ВАЖНЫЕ ПРАВИЛА ПОЛНОЙ АВТОНОМИИ:
1. **Полная автономия**: пользователь ставит конечную цель (например, «создай и собери приложение»). ЗАПРЕЩЕНО останавливаться на полпути, спрашивать подтверждение на установку пакетов или просить команду «продолжай». Доводи задачу до конечного результата самостоятельно.
2. **Самообслуживание окружения**: если для сборки или работы не хватает системного пакета (`apt-get`), Python-библиотеки (`pip`), компонента Android SDK (`sdkmanager`), плагина Gradle или настройки в `gradle.properties` (например, `android.useAndroidX=true`), ты ОБЯЗАН сам установить недостающее через `run_shell_command`, поправить конфиги и перезапустить сборку.
3. **Тестирование и работа до финального артефакта**: при разработке Android-приложения ОБЯЗАТЕЛЬНО пиши Unit/Robolectric тесты (`app/src/test/`), запускай `test_android_project` для проверки логики и кликов по интерфейсу, исправляй все найденные баги и собирай APK через `compile_android_project` (шаблон `/workspace/templates/android-hello`). В финальном ответе в Telegram всегда добавляй блок «Отчёт о тестировании» (что работает, какие баги исправлены, рекомендации по улучшению). Отправляй финальный ответ только когда `.apk` успешно собран.
4. **Пакетная запись и поиск**: при создании или изменении **2 и более файлов** ОБЯЗАТЕЛЬНО используй `write_files_batch` вместо серии `write_file`. Для API/библиотек 2025–2026 годов используй `search_web` и `fetch_web_page` (максимум 2 поисковых запроса на задачу).
5. **Среда выполнения**: ты работаешь ВНУТРИ Docker-контейнера RunPod (утилиты `docker` нет; сервисы управляются через `supervisorctl -s unix:///tmp/supervisor.sock status`). Никогда не вызывай `docker`. Экономь контекст — не читай огромные логи целиком (`tail -n 30`).
6. Если в запросе несколько пунктов — в финальном ответе дай отчёт по КАЖДОМУ пункту."""


def _history_file_path(chat_id: int) -> Path:
    return SESSIONS_DIR / f"chat_history_{chat_id}.json"


def _sanitize_msg_for_disk(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Удаляет тяжёлые base64-изображения при сохранении истории на диск/в Git."""
    content = msg.get("content")
    if isinstance(content, list):
        sanitized_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                sanitized_parts.append({"type": "text", "text": "[Изображение приложено пользователем]"})
            else:
                sanitized_parts.append(part)
        copy_msg = dict(msg)
        copy_msg["content"] = sanitized_parts
        return copy_msg
    return msg


def load_chat_history(chat_id: int) -> List[Dict[str, Any]]:
    """Загружает сохранённую историю диалога (до 100 сообщений) из JSON."""
    path = _history_file_path(chat_id)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict) and m.get("role") != "system"][-MAX_SAVED_HISTORY:]
    except Exception as ex:
        logger.warning(f"Не удалось загрузить историю {path}: {ex}")
    return []


def save_chat_history(chat_id: int, history: List[Dict[str, Any]]) -> None:
    """Сохраняет до 100 последних сообщений (без system) в sessions/chat_history_{user_id}.json."""
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        clean_items = [
            _sanitize_msg_for_disk(m)
            for m in history
            if isinstance(m, dict) and m.get("role") != "system"
        ][-MAX_SAVED_HISTORY:]
        with open(_history_file_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(clean_items, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        logger.warning(f"Не удалось сохранить историю для {chat_id}: {ex}")


def archive_chat_history(chat_id: int) -> Optional[Path]:
    """Архивирует текущую историю в sessions/archive/ перед сбросом контекста."""
    src = _history_file_path(chat_id)
    if not src.exists():
        return None
    try:
        archive_dir = SESSIONS_DIR / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = archive_dir / f"chat_history_{chat_id}_{ts}.json"
        shutil.move(str(src), str(dst))
        return dst
    except Exception as ex:
        logger.warning(f"Не удалось архивировать историю {chat_id}: {ex}")
        return None


def build_context_window(history: List[Dict[str, Any]], max_items: int = CONTEXT_WINDOW_SIZE) -> List[Dict[str, Any]]:
    """
    Формирует скользящее окно контекста (до max_items сообщений),
    гарантируя, что окно начинается с сообщения user и не отрезает
    исходный запрос во время длинных цепочек tool calling.
    """
    if not history:
        return []
    start_idx = max(0, len(history) - max_items)
    # Расширяем окно назад до ближайшего сообщения user, если старт попал на assistant/tool
    while start_idx > 0 and history[start_idx].get("role") != "user":
        start_idx -= 1
    window = history[start_idx:]
    # На случай если в начале истории вообще нет user (повреждённый файл), ищем первый user вперёд
    if window and window[0].get("role") != "user":
        for i, m in enumerate(window):
            if m.get("role") == "user":
                return window[i:]
    return window


def truncate_tool_output(raw_str: str, max_len: int = 3500) -> str:
    """Уровень 1: обрезает вывод инструмента до 3500 символов (500 начало + 3000 конец со стектрейсом)."""
    if len(raw_str) <= max_len:
        return raw_str
    return raw_str[:500] + "\n...[truncated]...\n" + raw_str[-3000:]


def compress_turn_tools(history: List[Dict[str, Any]], start_idx: int) -> None:
    """Уровень 2: после завершения запроса сжимает role='tool' до 300 символов для компактного JSON-кэша."""
    for i in range(start_idx, len(history)):
        msg = history[i]
        if isinstance(msg, dict) and msg.get("role") == "tool":
            c = str(msg.get("content", ""))
            if len(c) > 300:
                msg["content"] = c[:297] + "..."


def _should_think_on_start(user_content: Any) -> bool:
    """Определяет, нужна ли глубокая проработка архитектуры на первом шаге."""
    text = user_content if isinstance(user_content, str) else " ".join(
        p.get("text", "") for p in user_content if isinstance(p, dict)
    )
    low = text.lower()
    keywords = ("создай", "разработай", "сделай прилож", "новый проект", "с нуля", "архитектур", "create app", "build app")
    return len(text) > 250 or any(k in low for k in keywords)


MODEL_PRESETS: Dict[str, Tuple[str, str]] = {
    "google": ("google", "gemini-4-hydrogen"),
    "flash": ("google", "gemini-3.8-flash"),
    "deepseek": ("deepseek", "deepseek-chat"),
    "reasoner": ("deepseek", "deepseek-reasoner"),
    "local": ("local", os.environ.get("LOCAL_MODEL_NAME") or os.environ.get("VLLM_MODEL_NAME", "atlas-brain")),
}


class LLMRouter:
    """Гибкий роутер LLM-провайдеров на базе AsyncOpenAI с горячим переключением."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.provider = "google"
        self.model = "gemini-4-hydrogen"
        self._clients: Dict[str, AsyncOpenAI] = {}
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            prov = cfg.get("provider")
            mod = cfg.get("model")
            if prov in ("google", "deepseek", "local") and isinstance(mod, str) and mod:
                self.provider = prov
                self.model = mod
        except Exception as ex:
            logger.warning(f"Не удалось загрузить {self.config_path}: {ex}")

    def _save_config(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({"provider": self.provider, "model": self.model}, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            logger.warning(f"Не удалось сохранить {self.config_path}: {ex}")

    @staticmethod
    def _provider_settings(provider: str) -> Tuple[str, str]:
        if provider == "google":
            return (
                "https://generativelanguage.googleapis.com/v1beta/openai/",
                os.environ.get("GEMINI_API_KEY", "").strip(),
            )
        elif provider == "deepseek":
            return (
                "https://api.deepseek.com/v1",
                os.environ.get("DEEPSEEK_API_KEY", "").strip(),
            )
        else:
            return (
                os.environ.get("LOCAL_BASE_URL", "http://localhost:8000/v1").strip(),
                "EMPTY",
            )

    def get_client(self, provider: Optional[str] = None) -> AsyncOpenAI:
        prov = provider or self.provider
        if prov not in self._clients:
            base_url, api_key = self._provider_settings(prov)
            self._clients[prov] = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key or "MISSING_API_KEY",
                timeout=180.0,
            )
        return self._clients[prov]

    def has_valid_key(self, provider: Optional[str] = None) -> bool:
        prov = provider or self.provider
        if prov == "local":
            return True
        _, api_key = self._provider_settings(prov)
        return bool(api_key)

    def switch_model(self, alias: str) -> Tuple[str, str]:
        key = alias.strip().lower()
        if key not in MODEL_PRESETS:
            raise ValueError(f"Неизвестный пресет модели: {alias}")
        prov, mod = MODEL_PRESETS[key]
        if key == "local":
            mod = os.environ.get("LOCAL_MODEL_NAME") or os.environ.get("VLLM_MODEL_NAME", "atlas-brain")
        self.provider = prov
        self.model = mod
        # Сбрасываем кэш клиента, чтобы подхватить актуальный ключ из окружения
        self._clients.pop(prov, None)
        self._save_config()
        return prov, mod

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        use_tools: bool = True,
        enable_thinking: Optional[bool] = None,
    ) -> Any:
        client = self.get_client(self.provider)
        use_thinking = ENABLE_THINKING if enable_thinking is None else enable_thinking

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2048,
        }
        if self.model != "deepseek-reasoner":
            kwargs["temperature"] = 0.3

        if use_tools:
            kwargs["tools"] = TOOLS_SPEC
            kwargs["tool_choice"] = "auto"

        if self.provider == "local":
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": use_thinking}}

        try:
            return await client.chat.completions.create(**kwargs)
        except BadRequestError as ex:
            if "tool choice requires" in str(ex) and use_tools:
                logger.warning(f"[{self.provider}] Сервер не поддерживает tool-call-parser, переключение без инструментов...")
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                return await client.chat.completions.create(**kwargs)
            raise


llm_router = LLMRouter(ACTIVE_CONFIG_PATH)
usage_tracker = UsageTracker(USAGE_STATS_PATH)


# -----------------------------------------------------------------------------
# 6. Обработчики сообщений Telegram
# -----------------------------------------------------------------------------
dp = Dispatcher()
dp.message.middleware(StrictUserAuthMiddleware())


@dp.message(CommandStart())
async def cmd_start(message: Message):
    welcome_text = (
        "⚡ *ATLAS Mobile Bridge активен*\n\n"
        f"• *Провайдер*: `{llm_router.provider}`\n"
        f"• *Модель*: `{llm_router.model}`\n"
        f"• *Сервер*: `RunPod`\n"
        f"• *Авторизованный ID*: `{message.from_user.id}`\n\n"
        "Отправьте текстовую инструкцию, код или скриншот со смартфона.\n"
        "Я могу читать и изменять файлы в `/workspace`, фиксировать изменения в Git и собирать Android APK.\n\n"
        "*Команды управления:*\n"
        "• `/model` — просмотр и горячее переключение LLM-провайдера\n"
        "• `/stats` (или `/usage`) — статистика токенов, стоимости и лимитов\n"
        "• `/save` (или `/push`) — выгрузить все изменения в GitHub перед удалением (Terminate) пода\n"
        "• `/clear` — сбросить контекст диалога"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("model"))
async def cmd_model(message: Message):
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        status_text = (
            "🤖 *Текущий LLM-роутер*\n\n"
            f"• *Провайдер*: `{llm_router.provider}`\n"
            f"• *Модель*: `{llm_router.model}`\n\n"
            "*Доступные команды переключения:*\n"
            "• `/model google` — Google `gemini-4-hydrogen` (Free Tier)\n"
            "• `/model flash` — Google `gemini-3.8-flash` (Free Tier)\n"
            "• `/model deepseek` — DeepSeek `deepseek-chat`\n"
            "• `/model reasoner` — DeepSeek `deepseek-reasoner`\n"
            "• `/model local` — Локальный vLLM (`LOCAL_MODEL_NAME`)"
        )
        await message.answer(status_text, parse_mode=ParseMode.MARKDOWN)
        return

    alias = parts[1].strip().lower()
    if alias not in MODEL_PRESETS:
        await message.answer(
            f"❌ Неизвестный вариант `{alias}`.\n"
            "Доступно: `google`, `flash`, `deepseek`, `reasoner`, `local`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    prov, mod = llm_router.switch_model(alias)
    warn = ""
    if not llm_router.has_valid_key(prov):
        env_name = "GEMINI_API_KEY" if prov == "google" else "DEEPSEEK_API_KEY"
        warn = f"\n\n⚠️ *Внимание:* переменная `{env_name}` не задана в `.env`!"

    await message.answer(
        f"✅ *Активная модель переключена*\n\n"
        f"• *Провайдер*: `{prov}`\n"
        f"• *Модель*: `{mod}`\n"
        f"• *Сохранено в*: `sessions/active_config.json`{warn}",
        parse_mode=ParseMode.MARKDOWN,
    )


@dp.message(Command("stats", "usage"))
async def cmd_stats(message: Message):
    report = usage_tracker.format_stats_report()
    await message.answer(report, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("save", "push"))
async def cmd_save(message: Message):
    status_msg = await message.answer("💾 _Синхронизация проекта с GitHub..._", parse_mode=ParseMode.MARKDOWN)
    res = git_sync_push("manual /save via telegram bot")
    if res.get("status") == "ok":
        text = (
            "✅ *Все изменения успешно сохранены на GitHub!*\n\n"
            f"• *SHA коммита*: `{res.get('sha')}`\n"
            f"• *Результат*: `{res.get('commit_output')[:200]}`\n\n"
            "Код, `PROJECT_MEMORY.md` и история сессий зафиксированы в репозитории. "
            "Теперь вы можете безопасно завершить работу пода (Terminate)."
        )
    elif res.get("status") == "skipped":
        text = "ℹ️ Директория `/workspace` не содержит Git-репозитория. Убедитесь, что задана переменная `PROJECT_REPO_URL`."
    else:
        text = (
            f"⚠️ *Коммит создан (`{res.get('sha')}`), но при push возникло предупреждение:*\n"
            f"```\n{res.get('push_output')[:300]}\n```\n"
            "Проверьте права вашего токена `GITHUB_TOKEN`."
        )
    await status_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    chat_id = message.from_user.id
    archived_path = archive_chat_history(chat_id)
    user_conversations[chat_id] = []
    if archived_path:
        await message.answer(f"🧹 Контекст сброшен. Предыдущая история заархивирована в `{archived_path.name}`.")
    else:
        await message.answer("🧹 История контекста текущей сессии очищена.")


@dp.message(F.text | F.photo)
async def handle_user_input(message: Message, bot: Bot):
    chat_id = message.from_user.id
    if chat_id not in user_conversations:
        user_conversations[chat_id] = load_chat_history(chat_id)
    history = user_conversations[chat_id]

    # 1. Формирование контента пользователя (текст / фото)
    user_content: Any = ""
    if message.photo:
        photo = message.photo[-1]
        file_io = await bot.download(photo.file_id)
        if file_io:
            raw_bytes = file_io.read()
            b64_img = base64.b64encode(raw_bytes).decode("utf-8")
            caption = message.caption or "Проанализируй этот экран и скажи, что нужно исправить."
            user_content = [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
            ]
    else:
        user_content = message.text

    history.append({"role": "user", "content": user_content})
    if len(history) > MAX_SAVED_HISTORY:
        history = history[-MAX_SAVED_HISTORY:]
        user_conversations[chat_id] = history

    turn_start_idx = len(history) - 1
    # 2. Интерактивный цикл вызовов vLLM и инструментов
    status_msg = await message.answer("🧠 _Обработка запроса..._", parse_mode=ParseMode.MARKDOWN)

    try:
        max_tool_iterations = 45
        iteration = 0
        final_sent = False
        apk_to_deliver: Optional[str] = None
        last_tool_sig: Optional[str] = None
        repeat_count = 0
        search_web_count = 0
        files_modified = False
        next_thinking = _should_think_on_start(user_content)
        task_usage = TaskUsage(provider=llm_router.provider, model=llm_router.model)

        while iteration < max_tool_iterations:
            iteration += 1
            step_thinking = next_thinking
            next_thinking = False  # Включается только на 1 шаг (старт архитектуры или после ошибки)

            if iteration > 1 and llm_router.provider == "google":
                await asyncio.sleep(4)

            request_messages = [{"role": "system", "content": get_system_prompt()}] + build_context_window(history)
            llm_response = await llm_router.chat_completion(request_messages, enable_thinking=step_thinking)
            usage_tracker.record_call(llm_router.provider, llm_router.model, llm_response, task_usage=task_usage)

            msg = llm_response.choices[0].message
            raw_content = msg.content or ""
            cleaned_content = clean_llm_response(raw_content)
            raw_tool_calls = msg.tool_calls

            if not raw_tool_calls:
                # Финальный текстовый ответ получен
                final_text = cleaned_content or "Запрос выполнен."
                history.append({"role": "assistant", "content": final_text})
                footer = task_usage.format_summary()
                max_body = 4096 - len(footer) - 2
                body = final_text if len(final_text) <= max_body else (final_text[: max(0, max_body - 3)] + "...")
                display_text = f"{body}\n\n{footer}"
                try:
                    await status_msg.edit_text(display_text)
                except Exception:
                    try:
                        await status_msg.edit_text(display_text, parse_mode=None)
                    except Exception:
                        pass
                final_sent = True
                break

            # Есть вызовы инструментов
            tool_calls_dicts = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in raw_tool_calls
            ]
            assistant_entry: Dict[str, Any] = {
                "role": "assistant",
                "content": cleaned_content or None,
                "tool_calls": tool_calls_dicts,
            }
            history.append(assistant_entry)

            for tool_call in tool_calls_dicts:
                func_name = tool_call["function"]["name"]
                args = json.loads(tool_call["function"]["arguments"] or "{}")

                # Защита от зацикливания на 3 идентичных вызовах подряд
                tool_sig = f"{func_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                if tool_sig == last_tool_sig:
                    repeat_count += 1
                else:
                    last_tool_sig = tool_sig
                    repeat_count = 1

                # Ограничение search_web до 2 вызовов за один запрос
                if func_name == "search_web" and search_web_count >= 2:
                    tool_content = "[SYSTEM: Search limit reached (2/2). Proceed with coding using gathered info]"
                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_content
                    })
                    continue

                if func_name == "search_web":
                    search_web_count += 1

                try:
                    await status_msg.edit_text(f"⚙️ Шаг {iteration}/{max_tool_iterations}: `{func_name}`...", parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    try:
                        await status_msg.edit_text(f"⚙️ Шаг {iteration}/{max_tool_iterations}: {func_name}...", parse_mode=None)
                    except Exception:
                        pass

                tool_result = await execute_tool(func_name, args)

                if func_name in ("write_file", "write_files_batch", "run_shell_command"):
                    files_modified = True

                # Dynamic Thinking Router: включаем thinking на 1 шаг после ошибки сборки/тестов
                if func_name in ("compile_android_project", "test_android_project", "run_shell_command") and isinstance(tool_result, dict):
                    is_err = (
                        tool_result.get("status") == "failed"
                        or (tool_result.get("returncode") not in (None, 0))
                        or bool(tool_result.get("error"))
                    )
                    if is_err:
                        next_thinking = True

                if repeat_count >= 3 and isinstance(tool_result, dict):
                    tool_result["loop_warning"] = (
                        "ВНИМАНИЕ: Ты вызвал абсолютно идентичный инструмент с теми же аргументами 3 раза подряд. "
                        "НЕМЕДЛЕННО смени подход: проверь конфигурацию Gradle (gradle.properties, build.gradle.kts), "
                        "переключись с Kotlin на Java или изучи лог ошибки через run_shell_command."
                    )

                # Проверка на сгенерированный APK артефакт
                if func_name == "compile_android_project" and tool_result.get("status") == "success":
                    apk_path = tool_result.get("artifacts", {}).get("apk")
                    if apk_path and Path(apk_path).exists():
                        apk_to_deliver = apk_path

                # Уровень 1 очистки контекста: обрезка вывода инструмента до 3500 символов
                raw_tool_str = json.dumps(tool_result, ensure_ascii=False)
                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": truncate_tool_output(raw_tool_str, max_len=3500)
                })

        # Если лимит итераций исчерпан, принудительно формируем финальный ответ без инструментов
        if not final_sent:
            if llm_router.provider == "google":
                await asyncio.sleep(4)
            request_messages = (
                [{"role": "system", "content": get_system_prompt()}]
                + build_context_window(history)
                + [{"role": "user", "content": "Лимит шагов инструментов исчерпан. Дай полный итоговый ответ по ВСЕМ пунктам моего исходного запроса на основе уже собранных данных."}]
            )
            llm_response = await llm_router.chat_completion(request_messages, use_tools=False, enable_thinking=False)
            usage_tracker.record_call(llm_router.provider, llm_router.model, llm_response, task_usage=task_usage)
            raw_text = llm_response.choices[0].message.content or "Запрос выполнен."
            final_text = clean_llm_response(raw_text) or "Запрос выполнен."
            history.append({"role": "assistant", "content": final_text})
            footer = task_usage.format_summary()
            max_body = 4096 - len(footer) - 2
            body = final_text if len(final_text) <= max_body else (final_text[: max(0, max_body - 3)] + "...")
            display_text = f"{body}\n\n{footer}"
            try:
                await status_msg.edit_text(display_text)
            except Exception:
                try:
                    await status_msg.edit_text(display_text, parse_mode=None)
                except Exception:
                    pass

        # Уровень 2 очистки контекста: сжимаем tool-сообщения этого хода до 300 символов и сохраняем JSON
        compress_turn_tools(history, turn_start_idx)
        save_chat_history(chat_id, history)

        # Отложенный единый Git-пуш в конце цикла (если файлы менялись)
        if files_modified:
            await asyncio.to_thread(git_sync_push, "auto-save: batch task completed")

        # 3. Доставка собранного APK (всегда в artifacts на порт 8080 + файл в Telegram при <= 50 МБ)
        if apk_to_deliver:
            apk_path_obj = Path(apk_to_deliver)
            file_size_bytes = apk_path_obj.stat().st_size
            file_size_mb = file_size_bytes / (1024 * 1024)

            ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
            dest_file = ARTIFACTS_DIR / apk_path_obj.name
            shutil.copy2(apk_path_obj, dest_file)
            download_url = get_artifact_url(dest_file.name)

            dl_msg = (
                f"📦 *APK собран* (`{dest_file.name}`, {file_size_mb:.1f} МБ)\n"
                f"🔗 [Скачать через HTTP-сервер (порт {ARTIFACT_SERVER_PORT})]({download_url})"
            )
            await message.answer(dl_msg, parse_mode=ParseMode.MARKDOWN)

            if file_size_bytes <= 50 * 1024 * 1024:
                doc = FSInputFile(str(dest_file), filename=dest_file.name)
                await message.answer_document(doc, caption=f"🚀 Сборка готова: `{dest_file.name}`")

    except Exception as ex:
        logger.exception("Ошибка в обработчике сообщений")
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(ex)[:3900]}", parse_mode=None)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# 7. Главный запуск с защитой от конфликтов Telegram (Long Polling)
# -----------------------------------------------------------------------------
async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан! Бот остановлен.")
        return

    if ALLOWED_TELEGRAM_ID is None:
        logger.error("ALLOWED_TELEGRAM_ID не задан или некорректен! Бот остановлен.")
        return

    logger.info(f"Инициализация Telegram бота для пользователя ID: {ALLOWED_TELEGRAM_ID}")

    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )

    # Запуск фонового сервера отдачи больших файлов
    artifact_runner = await start_artifact_server()

    try:
        # Сброс вебхуков и зависших обновлений для чистого старта
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands([
            BotCommand(command="start", description="Статус ATLAS и справка"),
            BotCommand(command="model", description="Просмотр и переключение LLM-провайдера"),
            BotCommand(command="stats", description="Статистика токенов, стоимости и лимитов"),
            BotCommand(command="save", description="Сохранить код и память в GitHub"),
            BotCommand(command="clear", description="Архивировать и сбросить контекст"),
        ])
        logger.info("Long polling запущен...")

        # Защита от конфликтов при перезапусках контейнера
        while True:
            try:
                await dp.start_polling(bot, handle_signals=False)
            except TelegramConflictError:
                logger.warning("TelegramConflictError (409 Conflict): ожидание 5 секунд перед переподключением...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Неожиданная ошибка polling: {e}")
                await asyncio.sleep(3)

    finally:
        await artifact_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
