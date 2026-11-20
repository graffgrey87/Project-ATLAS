import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _install_missing_stubs() -> None:
    """Подставляет минимальные заглушки для сторонних библиотек, если тест запущен вне Docker."""
    if "aiofiles" not in sys.modules:
        m = types.ModuleType("aiofiles")
        m.open = open  # type: ignore[attr-defined]
        sys.modules["aiofiles"] = m

    if "aiohttp" not in sys.modules:
        aiohttp_mod = types.ModuleType("aiohttp")
        web_mod = types.ModuleType("aiohttp.web")
        web_mod.Request = object  # type: ignore[attr-defined]
        web_mod.Response = MagicMock  # type: ignore[attr-defined]
        web_mod.FileResponse = MagicMock  # type: ignore[attr-defined]
        web_mod.Application = MagicMock  # type: ignore[attr-defined]
        web_mod.AppRunner = MagicMock  # type: ignore[attr-defined]
        web_mod.TCPSite = MagicMock  # type: ignore[attr-defined]
        aiohttp_mod.web = web_mod  # type: ignore[attr-defined]
        sys.modules["aiohttp"] = aiohttp_mod
        sys.modules["aiohttp.web"] = web_mod

    if "httpx" not in sys.modules:
        httpx_mod = types.ModuleType("httpx")
        httpx_mod.AsyncClient = MagicMock  # type: ignore[attr-defined]
        httpx_mod.HTTPStatusError = Exception  # type: ignore[attr-defined]
        httpx_mod.RequestError = Exception  # type: ignore[attr-defined]
        sys.modules["httpx"] = httpx_mod

    if "bs4" not in sys.modules:
        bs4_mod = types.ModuleType("bs4")
        bs4_mod.BeautifulSoup = MagicMock  # type: ignore[attr-defined]
        sys.modules["bs4"] = bs4_mod

    if "duckduckgo_search" not in sys.modules:
        ddg_mod = types.ModuleType("duckduckgo_search")
        ddg_mod.DDGS = MagicMock  # type: ignore[attr-defined]
        sys.modules["duckduckgo_search"] = ddg_mod

    if "openai" not in sys.modules:
        openai_mod = types.ModuleType("openai")

        class _BadRequestError(Exception):
            pass

        openai_mod.AsyncOpenAI = MagicMock  # type: ignore[attr-defined]
        openai_mod.BadRequestError = _BadRequestError  # type: ignore[attr-defined]
        sys.modules["openai"] = openai_mod

    if "aiogram" not in sys.modules:
        aiogram_mod = types.ModuleType("aiogram")

        class _BaseMiddleware:
            pass

        class _Dispatcher:
            def __init__(self):
                self.message = MagicMock()
                self.message.side_effect = lambda *a, **kw: (lambda fn: fn)

        class _F:
            text = "text"
            photo = "photo"

            class _Expr:
                def __or__(self, other):
                    return self

        aiogram_mod.BaseMiddleware = _BaseMiddleware  # type: ignore[attr-defined]
        aiogram_mod.Bot = MagicMock  # type: ignore[attr-defined]
        aiogram_mod.Dispatcher = _Dispatcher  # type: ignore[attr-defined]
        aiogram_mod.F = SimpleNamespace(text=_F._Expr(), photo=_F._Expr())  # type: ignore[attr-defined]
        aiogram_mod.types = SimpleNamespace(TelegramObject=object)  # type: ignore[attr-defined]

        client_default = types.ModuleType("aiogram.client.default")
        client_default.DefaultBotProperties = MagicMock  # type: ignore[attr-defined]
        enums_mod = types.ModuleType("aiogram.enums")
        enums_mod.ParseMode = SimpleNamespace(MARKDOWN="Markdown")  # type: ignore[attr-defined]
        exc_mod = types.ModuleType("aiogram.exceptions")
        exc_mod.TelegramConflictError = Exception  # type: ignore[attr-defined]
        filters_mod = types.ModuleType("aiogram.filters")
        filters_mod.Command = lambda *a, **kw: None  # type: ignore[attr-defined]
        filters_mod.CommandStart = lambda *a, **kw: None  # type: ignore[attr-defined]
        types_mod = types.ModuleType("aiogram.types")
        types_mod.BotCommand = MagicMock  # type: ignore[attr-defined]
        types_mod.FSInputFile = MagicMock  # type: ignore[attr-defined]
        types_mod.Message = object  # type: ignore[attr-defined]

        sys.modules["aiogram"] = aiogram_mod
        sys.modules["aiogram.client"] = types.ModuleType("aiogram.client")
        sys.modules["aiogram.client.default"] = client_default
        sys.modules["aiogram.enums"] = enums_mod
        sys.modules["aiogram.exceptions"] = exc_mod
        sys.modules["aiogram.filters"] = filters_mod
        sys.modules["aiogram.types"] = types_mod


_install_missing_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")
os.environ.setdefault("WORKSPACE_DIR", str(Path(__file__).resolve().parent.parent))

import src.mobile_bridge as mb  # noqa: E402


class TestMobileBridge(unittest.TestCase):
    def test_strict_user_auth_middleware(self):
        mw = mb.StrictUserAuthMiddleware()
        handler = AsyncMock(return_value="ok")

        async def _run():
            with patch.object(mb, "ALLOWED_TELEGRAM_ID", 386074947):
                # Разрешённый пользователь
                ev_ok = SimpleNamespace(from_user=SimpleNamespace(id=386074947, username="owner"))
                res_ok = await mw(handler, ev_ok, {})
                self.assertEqual(res_ok, "ok")

                # Чужой пользователь должен быть отклонён
                handler.reset_mock()
                ev_bad = SimpleNamespace(from_user=SimpleNamespace(id=999999, username="hacker"))
                res_bad = await mw(handler, ev_bad, {})
                self.assertIsNone(res_bad)
                handler.assert_not_called()

        asyncio.run(_run())

    def test_llm_router_switch_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "active_config.json"
            router = mb.LLMRouter(cfg_path)
            self.assertEqual((router.provider, router.model), ("google", "gemini-4-hydrogen"))

            router.switch_model("flash")
            self.assertEqual((router.provider, router.model), ("google", "gemini-3.8-flash"))

            router.switch_model("reasoner")
            self.assertEqual((router.provider, router.model), ("deepseek", "deepseek-reasoner"))

            router.switch_model("local")
            self.assertEqual(router.provider, "local")

            # Повторная загрузка из JSON
            router2 = mb.LLMRouter(cfg_path)
            self.assertEqual(router2.provider, "local")

    def test_cmd_model_and_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_router = mb.LLMRouter(Path(tmp) / "active_config.json")
            tmp_tracker = mb.UsageTracker(Path(tmp) / "usage_stats.json")

            async def _run():
                with patch.object(mb, "llm_router", tmp_router), patch.object(mb, "usage_tracker", tmp_tracker):
                    msg = SimpleNamespace(text="/model", answer=AsyncMock())
                    await mb.cmd_model(msg)
                    self.assertIn("gemini-4-hydrogen", msg.answer.call_args[0][0])

                    msg2 = SimpleNamespace(text="/model deepseek", answer=AsyncMock())
                    await mb.cmd_model(msg2)
                    self.assertEqual(tmp_router.provider, "deepseek")
                    self.assertEqual(tmp_router.model, "deepseek-chat")

                    msg3 = SimpleNamespace(text="/model unknown_xyz", answer=AsyncMock())
                    await mb.cmd_model(msg3)
                    self.assertIn("Неизвестный вариант", msg3.answer.call_args[0][0])

                    msg4 = SimpleNamespace(text="/stats", answer=AsyncMock())
                    await mb.cmd_stats(msg4)
                    self.assertIn("Google Free Tier (250 RPD)", msg4.answer.call_args[0][0])

            asyncio.run(_run())

    def test_handle_user_input_tool_loop_sleep_and_usage_footer(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_router = mb.LLMRouter(Path(tmp) / "active_config.json")
            tmp_tracker = mb.UsageTracker(Path(tmp) / "usage_stats.json")

            # Шаг 1: вызов tool read_file, Шаг 2: финальный ответ
            tc = SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name="read_file", arguments=json.dumps({"path": "README.md"})),
            )
            resp1 = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[tc]))],
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120),
            )
            resp2 = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Готово!", tool_calls=None))],
                usage=SimpleNamespace(prompt_tokens=150, completion_tokens=30, total_tokens=180),
            )

            status_msg = SimpleNamespace(edit_text=AsyncMock())
            user_msg = SimpleNamespace(
                from_user=SimpleNamespace(id=123456789),
                photo=None,
                text="Проверь README.md",
                answer=AsyncMock(return_value=status_msg),
            )
            bot = SimpleNamespace()

            async def _run():
                with (
                    patch.object(mb, "llm_router", tmp_router),
                    patch.object(mb, "usage_tracker", tmp_tracker),
                    patch.object(mb, "SESSIONS_DIR", Path(tmp)),
                    patch.object(mb, "user_conversations", {}),
                    patch.object(tmp_router, "chat_completion", AsyncMock(side_effect=[resp1, resp2])),
                    patch.object(mb, "execute_tool", AsyncMock(return_value={"status": "ok", "content": "ATLAS"})),
                    patch.object(mb.asyncio, "sleep", AsyncMock()) as mock_sleep,
                ):
                    await mb.handle_user_input(user_msg, bot)
                    # На 2-м шаге для google должна быть пауза 4 сек
                    mock_sleep.assert_awaited_once_with(4)
                    final_sent_text = status_msg.edit_text.call_args_list[-1][0][0]
                    self.assertIn("Готово!", final_sent_text)
                    self.assertIn("📊 Затраты на задачу: Запросов (шагов): 2 | Вход: 250 ток. | Выход: 50 ток.", final_sent_text)

            asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
