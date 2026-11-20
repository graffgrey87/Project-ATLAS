import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.usage_tracker import GOOGLE_FREE_TIER_RPD, TaskUsage, UsageTracker, calculate_cost_usd


class TestUsageTracker(unittest.TestCase):
    def test_calculate_cost_usd(self):
        self.assertEqual(calculate_cost_usd("google", "gemini-4-hydrogen", 1_000_000, 1_000_000), 0.0)
        self.assertEqual(calculate_cost_usd("local", "atlas-brain", 500_000, 500_000), 0.0)
        cost_ds = calculate_cost_usd("deepseek", "deepseek-chat", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost_ds, 1.37, places=4)
        cost_r = calculate_cost_usd("deepseek", "deepseek-reasoner", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost_r, 2.74, places=4)

    def test_task_usage_format(self):
        tu = TaskUsage(provider="google", model="gemini-4-hydrogen")
        tu.add(120, 45, 165, 0.0)
        tu.add(80, 55, 135, 0.0)
        summary = tu.format_summary()
        self.assertEqual(
            summary,
            "📊 Затраты на задачу: Запросов (шагов): 2 | Вход: 200 ток. | Выход: 100 ток. | Провайдер: gemini-4-hydrogen | Оценка: $0.0000",
        )

    def test_record_call_and_periods(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats_path = Path(tmp) / "usage_stats.json"
            tracker = UsageTracker(stats_path)
            tu = TaskUsage("google", "gemini-4-hydrogen")

            resp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150))
            tracker.record_call("google", "gemini-4-hydrogen", resp, task_usage=tu)
            tracker.record_call("deepseek", "deepseek-chat", {"usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}})

            self.assertTrue(stats_path.exists())
            day_agg = tracker._aggregate_period("day")
            self.assertEqual(day_agg["google"]["requests"], 1)
            self.assertEqual(day_agg["google"]["total_tokens"], 150)
            self.assertEqual(day_agg["deepseek"]["requests"], 1)
            self.assertEqual(day_agg["deepseek"]["total_tokens"], 300)

            report = tracker.format_stats_report()
            self.assertIn("Сегодня (Day)", report)
            self.assertIn("Текущая неделя (Week)", report)
            self.assertIn("Текущий месяц (Month)", report)
            self.assertIn(f"1/{GOOGLE_FREE_TIER_RPD}", report)
            self.assertIn(f"осталось `{GOOGLE_FREE_TIER_RPD - 1}`", report)

    def test_corrupt_json_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats_path = Path(tmp) / "usage_stats.json"
            stats_path.write_text("{broken json", encoding="utf-8")
            tracker = UsageTracker(stats_path)
            self.assertEqual(tracker.data, {"daily": {}})


if __name__ == "__main__":
    unittest.main()
