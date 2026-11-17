#!/usr/bin/env python3
# =============================================================================
# ATLAS — skills/test_android.py
# Автономный навык тестирования Android проектов (Unit / Robolectric + Lint)
# с выдачей структурированного JSON-отчёта для мобильного агента.
# =============================================================================
import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_utils import create_log_file, format_error, make_report, output_report, write_log


def parse_junit_xml_reports(project_dir: Path):
    """Разбирает XML-отчёты JUnit/Robolectric из build/test-results."""
    results_dir = project_dir / "app" / "build" / "test-results" / "testDebugUnitTest"
    total = 0
    failed = 0
    skipped = 0
    failures = []

    if not results_dir.exists():
        return total, failed, skipped, failures

    for xml_file in results_dir.glob("TEST-*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
            total += int(root.attrib.get("tests", 0))
            failed += int(root.attrib.get("failures", 0)) + int(root.attrib.get("errors", 0))
            skipped += int(root.attrib.get("skipped", 0))

            for tc in root.findall("testcase"):
                for err_tag in ("failure", "error"):
                    node = tc.find(err_tag)
                    if node is not None:
                        cls = tc.attrib.get("classname", "")
                        name = tc.attrib.get("name", "")
                        msg = node.attrib.get("message", "") or (node.text or "")[:400]
                        failures.append(format_error(
                            message=f"{cls}.{name}: {msg.strip()[:300]}",
                            severity="error"
                        ))
        except Exception:
            continue

    return total, failed, skipped, failures


def run_android_tests(project_path: str, include_lint: bool = True, verbose: bool = False):
    log_file = create_log_file("test_android")
    project_dir = Path(project_path).resolve()

    write_log(log_file, f"=== ATLAS Android Test: {project_dir} ===")

    if not project_dir.exists():
        rep = make_report(
            status="failed",
            summary=f"Директория проекта не найдена: {project_dir}",
            errors=[format_error(f"Каталог не существует: {project_dir}", severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить путь к проекту Android."
        )
        output_report(rep, verbose=verbose)
        return

    gradlew_sh = project_dir / "gradlew"
    if gradlew_sh.exists() and os.name != "nt":
        gradle_cmd = [str(gradlew_sh)]
    elif gradlew_sh.exists():
        gradle_cmd = ["bash", str(gradlew_sh)]
    else:
        gradle_cmd = ["gradle"]

    tasks = ["testDebugUnitTest"]
    if include_lint:
        tasks.append("lintDebug")

    cmd = gradle_cmd + tasks + ["--continue", "--stacktrace"]
    write_log(log_file, f"Executing: {' '.join(cmd)}\n")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180
        )
        full_output = proc.stdout or ""
        write_log(log_file, full_output)
    except Exception as ex:
        rep = make_report(
            status="failed",
            summary=f"Ошибка запуска тестов Gradle: {ex}",
            errors=[format_error(str(ex), severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить наличие Gradle и корректность build.gradle.kts."
        )
        output_report(rep, verbose=verbose)
        return

    total, failed, skipped, test_failures = parse_junit_xml_reports(project_dir)
    passed = max(0, total - failed - skipped)

    if proc.returncode == 0 and failed == 0:
        summary = (
            f"Тестирование пройдено: {passed}/{total} тестов успешно "
            f"(пропущено: {skipped})."
        )
        if total == 0:
            summary += " Предупреждение: тесты в src/test/ не найдены — напиши Unit/Robolectric тесты!"
        rep = make_report(
            status="success",
            summary=summary,
            errors=[],
            warnings_count=0,
            artifacts={
                "full_log": str(log_file),
                "tests_total": total,
                "tests_passed": passed,
                "tests_failed": failed,
                "tests_skipped": skipped,
            },
            next_action=(
                "Запустить compile_android_project для финальной сборки APK."
                if total > 0
                else "Создать Unit/Robolectric тесты в app/src/test/ и повторить test_android_project."
            )
        )
    else:
        if not test_failures:
            tail_err = "\n".join(full_output.splitlines()[-15:])
            test_failures.append(format_error(
                message=f"Gradle завершился с кодом {proc.returncode}: {tail_err[-400:]}",
                severity="error"
            ))
        rep = make_report(
            status="failed",
            summary=f"Провалено тестов: {failed} из {total} (пройдено: {passed}).",
            errors=test_failures[:10],
            warnings_count=0,
            artifacts={
                "full_log": str(log_file),
                "tests_total": total,
                "tests_passed": passed,
                "tests_failed": failed,
            },
            next_action="Исправить найденные баги в коде/разметке и повторить test_android_project."
        )

    output_report(rep, verbose=verbose)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATLAS Android Test Skill")
    parser.add_argument("--project-dir", required=True, help="Путь к Android проекту")
    parser.add_argument("--no-lint", action="store_true", help="Пропустить lintDebug")
    parser.add_argument("--verbose", action="store_true", help="Подробный вывод")
    args = parser.parse_args()

    run_android_tests(project_path=args.project_dir, include_lint=not args.no_lint, verbose=args.verbose)
