#!/usr/bin/env python3
# =============================================================================
# ATLAS — src/mobile_bridge.py
# Мобильный мост (Telegram-бот) на базе aiogram 3.x для автономного vibe-кодинга
# со смартфона: чат, Vision VLM, Function Calling и раздача собранных APK.
# =============================================================================
import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiofiles
import aiohttp
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

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

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace" if os.name != "nt" else ".")).resolve()
ARTIFACTS_DIR = WORKSPACE_DIR / "artifacts"
try:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

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
# 5. Интеграция с vLLM (OpenAI Compatible API + Tool Calling)
# -----------------------------------------------------------------------------
user_conversations: Dict[int, List[Dict[str, Any]]] = {}

SYSTEM_PROMPT = """Вы — ATLAS: автономная среда vibe-кодинга и персональный AI-инженер.
Вы работаете на мощном сервере RunPod с прямым доступом к файловой системе /workspace и навыкам сборки.
Вы общаетесь с владельцем через мобильный интерфейс Telegram.
Ваши ответы должны быть краткими, деловыми, конкретными и строго по делу.
При необходимости чтения, редактирования файлов, коммитов в Git или сборки проектов используйте доступные инструменты (Function Calling)."""


async def query_vllm(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Отправляет запрос к vLLM через aiohttp с поддержкой function calling и fallback."""
    payload = {
        "model": VLLM_MODEL,
        "messages": messages,
        "tools": TOOLS_SPEC,
        "tool_choice": "auto",
        "temperature": 0.3,
        "max_tokens": 2048
    }
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
    user_conversations[message.from_user.id] = []
    await message.answer("🧹 История контекста текущей сессии очищена.")


@dp.message(F.text | F.photo)
async def handle_user_input(message: Message, bot: Bot):
    chat_id = message.from_user.id
    history = user_conversations.setdefault(chat_id, [])

    # Инициализация истории с системным промптом
    if not history:
        history.append({"role": "system", "content": SYSTEM_PROMPT})

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

    # Ограничение глубины контекста в памяти бота
    if len(history) > 20:
        history = [history[0]] + history[-15:]
        user_conversations[chat_id] = history

    # 2. Интерактивный цикл вызовов vLLM и инструментов
    status_msg = await message.answer("🧠 _Обработка запроса..._", parse_mode=ParseMode.MARKDOWN)

    try:
        max_tool_iterations = 5
        iteration = 0
        apk_to_deliver: Optional[str] = None

        while iteration < max_tool_iterations:
            iteration += 1
            vllm_response = await query_vllm(history)
            choice = vllm_response["choices"][0]["message"]

            tool_calls = choice.get("tool_calls")
            if not tool_calls:
                # Финальный текстовый ответ получен
                final_text = choice.get("content", "Запрос выполнен.")
                history.append({"role": "assistant", "content": final_text})
                await status_msg.edit_text(final_text)
                break

            # Есть вызовы инструментов
            history.append(choice)
            for tool_call in tool_calls:
                func_name = tool_call["function"]["name"]
                args = json.loads(tool_call["function"]["arguments"])

                await status_msg.edit_text(f"⚙️ _Выполняю инструмент `{func_name}`..._", parse_mode=ParseMode.MARKDOWN)
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

        # 3. Доставка собранного APK (если был создан)
        if apk_to_deliver:
            apk_path_obj = Path(apk_to_deliver)
            file_size_bytes = apk_path_obj.stat().st_size
            file_size_mb = file_size_bytes / (1024 * 1024)

            if file_size_bytes <= 50 * 1024 * 1024:
                # До 50 МБ: отправка напрямую в чат
                await message.answer(f"📦 *Отправка APK* ({file_size_mb:.1f} МБ)...", parse_mode=ParseMode.MARKDOWN)
                doc = FSInputFile(str(apk_path_obj), filename=apk_path_obj.name)
                await message.answer_document(doc, caption=f"🚀 Сборка готова: `{apk_path_obj.name}`")
            else:
                # Более 50 МБ: копирование в artifacts и отдача через HTTP-сервер
                dest_file = ARTIFACTS_DIR / apk_path_obj.name
                shutil.copy2(apk_path_obj, dest_file)
                download_url = get_artifact_url(dest_file.name)
                dl_msg = (
                    f"📦 *APK файл превышает 50 МБ* ({file_size_mb:.1f} МБ)\n"
                    f"Прямая ссылка для загрузки и установки на смартфон:\n"
                    f"🔗 [Скачать APK]({download_url})"
                )
                await message.answer(dl_msg, parse_mode=ParseMode.MARKDOWN)

    except Exception as ex:
        logger.exception("Ошибка в обработчике сообщений")
        await status_msg.edit_text(f"❌ *Ошибка*: `{str(ex)}`", parse_mode=ParseMode.MARKDOWN)


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
