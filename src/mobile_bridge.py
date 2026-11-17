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
from typing import Any, Callable, Dict, List, Optional

import aiofiles
import aiohttp
from aiohttp import web
import httpx
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, FSInputFile, Message

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
VLLM_API_URL = os.environ.get("VLLM_API_URL", "http://localhost:8000/v1/chat/completions")
VLLM_MODEL = os.environ.get("VLLM_MODEL_NAME", "atlas-brain")
ENABLE_THINKING = os.environ.get("ATLAS_ENABLE_THINKING", "false").lower() in ("true", "1", "yes")

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace" if os.name != "nt" else ".")).resolve()
ARTIFACTS_DIR = WORKSPACE_DIR / "artifacts"
SESSIONS_DIR = WORKSPACE_DIR / "sessions"
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
            "description": "Создать или перезаписать файл в /workspace",
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
            
            # Автоматическая синхронизация с GitHub (защита от потери кода при Terminate)
            sync_res = git_sync_push(f"auto-save: update {target.name}")
            return {
                "status": "ok",
                "message": f"Файл {target} успешно записан ({len(arguments['content'])} символов).",
                "git_sync": sync_res.get("status"),
                "sha": sync_res.get("sha")
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

        elif name == "run_shell_command":
            cmd = arguments["command"]
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(WORKSPACE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60
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

ВАЖНЫЕ ПРАВИЛА:
1. Ваши встроенные знания ограничены 2024 годом. Для любых вопросов о событиях, версиях библиотек, SDK и API 2025–2026 годов ОБЯЗАТЕЛЬНО используйте инструменты `search_web` и `fetch_web_page`. Делайте 1–2 точных запроса вместо серии однотипных.
2. Вы работаете ВНУТРИ Docker-контейнера RunPod (утилиты `docker` нет; сервисы управляются через `supervisorctl -s unix:///tmp/supervisor.sock status`). Никогда не вызывайте `docker`.
3. Для чтения/записи файлов, коммитов в Git (`git_commit_all`) и сборки Android APK (`compile_android_project`, шаблон `/workspace/templates/android-hello`) используйте инструменты Function Calling.
4. Если в запросе пользователя несколько пунктов, в финальном ответе обязательно дайте чёткий ответ по КАЖДОМУ пункту."""


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


async def query_vllm(messages: List[Dict[str, Any]], use_tools: bool = True) -> Dict[str, Any]:
    """Отправляет запрос к vLLM через aiohttp с поддержкой function calling и fallback."""
    payload: Dict[str, Any] = {
        "model": VLLM_MODEL,
        "messages": messages,
        "chat_template_kwargs": {"enable_thinking": ENABLE_THINKING},
        "temperature": 0.3,
        "max_tokens": 2048
    }
    if use_tools:
        payload["tools"] = TOOLS_SPEC
        payload["tool_choice"] = "auto"
    timeout = aiohttp.ClientTimeout(total=180)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(VLLM_API_URL, json=payload) as resp:
            if resp.status == 400:
                text = await resp.text()
                if "tool choice requires" in text:
                    logger.warning("[vLLM] Сервер не поддерживает tool-call-parser, переключение на режим без инструментов...")
                    payload_no_tools = {
                        "model": VLLM_MODEL,
                        "messages": messages,
                        "chat_template_kwargs": {"enable_thinking": ENABLE_THINKING},
                        "temperature": 0.3,
                        "max_tokens": 2048
                    }
                    async with session.post(VLLM_API_URL, json=payload_no_tools) as resp_fallback:
                        if resp_fallback.status != 200:
                            fallback_err = await resp_fallback.text()
                            raise RuntimeError(f"vLLM API Error ({resp_fallback.status}): {fallback_err}")
                        return await resp_fallback.json()
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"vLLM API Error ({resp.status}): {text}")
            return await resp.json()


# -----------------------------------------------------------------------------
# 6. Обработчики сообщений Telegram
# -----------------------------------------------------------------------------
dp = Dispatcher()
dp.message.middleware(StrictUserAuthMiddleware())


@dp.message(CommandStart())
async def cmd_start(message: Message):
    welcome_text = (
        "⚡ *ATLAS Mobile Bridge активен*\n\n"
        f"• *Модель*: `{VLLM_MODEL}`\n"
        f"• *Сервер*: `RunPod`\n"
        f"• *Авторизованный ID*: `{message.from_user.id}`\n\n"
        "Отправьте текстовую инструкцию, код или скриншот со смартфона.\n"
        "Я могу читать и изменять файлы в `/workspace`, фиксировать изменения в Git и собирать Android APK.\n\n"
        "*Команды управления:*\n"
        "• `/save` (или `/push`) — выгрузить все изменения в GitHub перед удалением (Terminate) пода\n"
        "• `/clear` — сбросить контекст диалога"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.MARKDOWN)


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

    # 2. Интерактивный цикл вызовов vLLM и инструментов (скользящее окно 20 сообщений + системный промпт)
    status_msg = await message.answer("🧠 _Обработка запроса..._", parse_mode=ParseMode.MARKDOWN)

    try:
        max_tool_iterations = 10
        iteration = 0
        final_sent = False
        apk_to_deliver: Optional[str] = None

        while iteration < max_tool_iterations:
            iteration += 1
            request_messages = [{"role": "system", "content": get_system_prompt()}] + build_context_window(history)
            vllm_response = await query_vllm(request_messages)
            choice = vllm_response["choices"][0]["message"]

            tool_calls = choice.get("tool_calls")
            if not tool_calls:
                # Финальный текстовый ответ получен
                raw_text = choice.get("content", "Запрос выполнен.")
                final_text = clean_llm_response(raw_text) or "Запрос выполнен."
                history.append({"role": "assistant", "content": final_text})
                save_chat_history(chat_id, history)
                try:
                    await status_msg.edit_text(final_text[:4096])
                except Exception:
                    try:
                        await status_msg.edit_text(final_text[:4096], parse_mode=None)
                    except Exception:
                        pass
                final_sent = True
                break

            # Есть вызовы инструментов
            history.append(choice)
            for tool_call in tool_calls:
                func_name = tool_call["function"]["name"]
                args = json.loads(tool_call["function"]["arguments"])

                try:
                    await status_msg.edit_text(f"⚙️ Выполняю инструмент: `{func_name}`...", parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    try:
                        await status_msg.edit_text(f"⚙️ Выполняю инструмент: {func_name}...", parse_mode=None)
                    except Exception:
                        pass
                tool_result = await execute_tool(func_name, args)

                # Проверка на сгенерированный APK артефакт
                if func_name == "compile_android_project" and tool_result.get("status") == "success":
                    apk_path = tool_result.get("artifacts", {}).get("apk")
                    if apk_path and Path(apk_path).exists():
                        apk_to_deliver = apk_path

                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(tool_result, ensure_ascii=False)
                })
            save_chat_history(chat_id, history)

        # Если лимит итераций исчерпан, принудительно формируем финальный ответ без инструментов
        if not final_sent:
            request_messages = (
                [{"role": "system", "content": get_system_prompt()}]
                + build_context_window(history)
                + [{"role": "user", "content": "Лимит шагов инструментов исчерпан. Дай полный итоговый ответ по ВСЕМ пунктам моего исходного запроса на основе уже собранных данных."}]
            )
            vllm_response = await query_vllm(request_messages, use_tools=False)
            raw_text = vllm_response["choices"][0]["message"].get("content", "Запрос выполнен.")
            final_text = clean_llm_response(raw_text) or "Запрос выполнен."
            history.append({"role": "assistant", "content": final_text})
            save_chat_history(chat_id, history)
            try:
                await status_msg.edit_text(final_text[:4096])
            except Exception:
                try:
                    await status_msg.edit_text(final_text[:4096], parse_mode=None)
                except Exception:
                    pass

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
