#!/usr/bin/env python3
# =============================================================================
# ATLAS — src/usage_tracker.py
# Учёт запросов, токенов и расчётной стоимости LLM-провайдеров.
# Хранит накопительную статистику в sessions/usage_stats.json.
# =============================================================================
from dataclasses import dataclass
from datetime import date, datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("usage_tracker")

# Стоимость за 1M токенов (input_usd, output_usd)
MODEL_PRICING_PER_1M: Dict[str, Tuple[float, float]] = {
    "gemini-4-hydrogen": (0.0, 0.0),   # Google Free Tier
    "gemini-3.8-flash": (0.0, 0.0),    # Google Free Tier
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
}

GOOGLE_FREE_TIER_RPD = 250


def calculate_cost_usd(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Рассчитывает ориентировочную стоимость запроса в USD."""
    if provider in ("google", "local"):
        return 0.0
    in_price, out_price = MODEL_PRICING_PER_1M.get(model, (0.0, 0.0))
    return (prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000.0


@dataclass
class TaskUsage:
    """Статистика использования LLM в рамках одной задачи (сессии ответа)."""
    provider: str
    model: str
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, prompt_tokens: int, completion_tokens: int, total_tokens: int, cost_usd: float) -> None:
        self.requests += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.cost_usd += cost_usd

    def format_summary(self) -> str:
        return (
            f"📊 Затраты на задачу: Запросов (шагов): {self.requests} | "
            f"Вход: {self.prompt_tokens} ток. | Выход: {self.completion_tokens} ток. | "
            f"Провайдер: {self.model} | Оценка: ${self.cost_usd:.4f}"
        )


class UsageTracker:
    """Персистентный трекер расхода запросов, токенов и стоимости по дням и провайдерам."""

    def __init__(self, stats_path: Path):
        self.stats_path = stats_path
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.stats_path.exists():
            return {"daily": {}}
        try:
            with open(self.stats_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("daily"), dict):
                return loaded
        except Exception as ex:
            logger.warning(f"Не удалось прочитать {self.stats_path}: {ex}")
        return {"daily": {}}

    def _save(self) -> None:
        try:
            self.stats_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.stats_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            tmp_path.replace(self.stats_path)
        except Exception as ex:
            logger.warning(f"Не удалось сохранить {self.stats_path}: {ex}")

    @staticmethod
    def extract_usage(response: Any) -> Tuple[int, int, int]:
        """Безопасно извлекает (prompt_tokens, completion_tokens, total_tokens) из ответа AsyncOpenAI или dict."""
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        if usage is None:
            return 0, 0, 0

        if isinstance(usage, dict):
            pt = int(usage.get("prompt_tokens") or 0)
            ct = int(usage.get("completion_tokens") or 0)
            tt = int(usage.get("total_tokens") or (pt + ct))
        else:
            pt = int(getattr(usage, "prompt_tokens", 0) or 0)
            ct = int(getattr(usage, "completion_tokens", 0) or 0)
            tt = int(getattr(usage, "total_tokens", 0) or (pt + ct))
        return pt, ct, tt

    def record_call(
        self,
        provider: str,
        model: str,
        response: Any,
        task_usage: Optional[TaskUsage] = None,
    ) -> Tuple[int, int, int, float]:
        """Фиксирует один вызов LLM в задаче и в накопительной статистике на диске."""
        pt, ct, tt = self.extract_usage(response)
        cost = calculate_cost_usd(provider, model, pt, ct)

        if task_usage is not None:
            task_usage.provider = provider
            task_usage.model = model
            task_usage.add(pt, ct, tt, cost)

        today_key = date.today().isoformat()
        daily = self.data.setdefault("daily", {})
        day_bucket = daily.setdefault(today_key, {})
        prov_bucket = day_bucket.setdefault(
            provider,
            {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            },
        )
        prov_bucket["requests"] += 1
        prov_bucket["prompt_tokens"] += pt
        prov_bucket["completion_tokens"] += ct
        prov_bucket["total_tokens"] += tt
        prov_bucket["cost_usd"] = round(float(prov_bucket["cost_usd"]) + cost, 6)

        self._save()
        return pt, ct, tt, cost

    def _aggregate_period(self, period: str) -> Dict[str, Dict[str, Any]]:
        """Агрегирует статистику за 'day', 'week' или 'month' с разбивкой по провайдерам."""
        today = date.today()
        today_iso = today.isocalendar()[:2]
        result: Dict[str, Dict[str, Any]] = {}

        for day_str, providers in self.data.get("daily", {}).items():
            try:
                d = datetime.strptime(day_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            if period == "day" and d != today:
                continue
            elif period == "week" and d.isocalendar()[:2] != today_iso:
                continue
            elif period == "month" and (d.year != today.year or d.month != today.month):
                continue

            if not isinstance(providers, dict):
                continue

            for prov, stats in providers.items():
                if not isinstance(stats, dict):
                    continue
                agg = result.setdefault(
                    prov,
                    {
                        "requests": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "cost_usd": 0.0,
                    },
                )
                agg["requests"] += int(stats.get("requests", 0))
                agg["prompt_tokens"] += int(stats.get("prompt_tokens", 0))
                agg["completion_tokens"] += int(stats.get("completion_tokens", 0))
                agg["total_tokens"] += int(stats.get("total_tokens", 0))
                agg["cost_usd"] += float(stats.get("cost_usd", 0.0))

        return result

    @staticmethod
    def _format_period_block(title: str, agg: Dict[str, Dict[str, Any]]) -> str:
        if not agg:
            return f"*{title}:*\n  • _Нет данных_"

        total_req = sum(v["requests"] for v in agg.values())
        total_in = sum(v["prompt_tokens"] for v in agg.values())
        total_out = sum(v["completion_tokens"] for v in agg.values())
        total_cost = sum(v["cost_usd"] for v in agg.values())

        lines = [
            f"*{title}:* {total_req} запр. | {total_in + total_out:,} ток. (вх: {total_in:,} / вых: {total_out:,}) | `${total_cost:.4f}`"
        ]
        for prov in sorted(agg.keys()):
            v = agg[prov]
            lines.append(
                f"  • `{prov}`: {v['requests']} запр. | {v['total_tokens']:,} ток. | `${v['cost_usd']:.4f}`"
            )
        return "\n".join(lines)

    def format_stats_report(self) -> str:
        """Формирует полную сводку для Telegram-команды /stats (/usage)."""
        day_agg = self._aggregate_period("day")
        week_agg = self._aggregate_period("week")
        month_agg = self._aggregate_period("month")

        google_today_req = day_agg.get("google", {}).get("requests", 0)
        google_remaining = max(0, GOOGLE_FREE_TIER_RPD - google_today_req)

        sections = [
            "📊 *Статистика использования LLM*",
            "",
            self._format_period_block("Сегодня (Day)", day_agg),
            "",
            self._format_period_block("Текущая неделя (Week)", week_agg),
            "",
            self._format_period_block("Текущий месяц (Month)", month_agg),
            "",
            f"🔋 *Google Free Tier (250 RPD):* использовано `{google_today_req}/250`, осталось `{google_remaining}` запр.",
        ]
        return "\n".join(sections)
