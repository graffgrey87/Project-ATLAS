#!/usr/bin/env python3
# =============================================================================
# ATLAS — skills/skill_utils.py
# Вспомогательные утилиты и строгая валидация единого JSON-контракта Skills.
# =============================================================================
import os
import sys
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_PATH = Path(__file__).resolve().parent / "_schema.json"


def get_logs_dir() -> Path:
    """Возвращает путь к директории логов на persistent volume или локально."""
    logs_dir = Path(os.environ.get("ATLAS_LOGS_DIR", "/workspace/logs"))
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fallback на локальную директорию при разработке
        logs_dir = Path("./logs").resolve()
        logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def create_log_file(skill_name: str) -> Path:
    """Создаёт уникальный файл для полного лога операции."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_file = get_logs_dir() / f"{skill_name}_{timestamp}.log"
    log_file.touch(exist_ok=True)
    return log_file


def format_error(
    message: str,
    file: Optional[str] = None,
    line: Optional[int] = None,
    severity: str = "error"
) -> Dict[str, Any]:
    """Форматирует ошибку в соответствии с JSON Schema."""
    return {
        "file": file,
        "line": line,
        "message": message.strip(),
        "severity": "fatal" if severity == "fatal" else "error"
    }


def make_report(
    status: str,
    summary: str,
    errors: List[Dict[str, Any]],
    warnings_count: int,
    artifacts: Dict[str, Any],
    next_action: str
) -> Dict[str, Any]:
    """Формирует итоговый структурированный словарь отчёта."""
    if status not in ("success", "failed", "partial"):
        raise ValueError(f"Недопустимый статус: {status}")

    report = {
        "status": status,
        "summary": summary.strip(),
        "errors": errors,
        "warnings_count": max(0, int(warnings_count)),
        "artifacts": artifacts,
        "next_action": next_action.strip()
    }
    return report


def output_report(report: Dict[str, Any], verbose: bool = False) -> None:
    """
    Выводит только валидный JSON в stdout для потребления LLM-агентом.
    Если verbose=True, дополнительно выводит краткую человекочитаемую сводку в stderr.
    """
    if verbose:
        sys.stderr.write(f"\n[ATLAS Skill Report: {report['status'].upper()}]\n")
        sys.stderr.write(f"Summary: {report['summary']}\n")
        sys.stderr.write(f"Errors count: {len(report['errors'])}\n")
        sys.stderr.write(f"Warnings count: {report['warnings_count']}\n")
        sys.stderr.write(f"Full log: {report['artifacts'].get('full_log', 'N/A')}\n")
        sys.stderr.write(f"Next action: {report['next_action']}\n\n")

    # В stdout отдаётся исключительно чистый валидный JSON
    print(json.dumps(report, indent=2, ensure_ascii=False))


def write_log(log_path: Path, text: str) -> None:
    """Записывает строку или фрагмент вывода в файл полного лога."""
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")
