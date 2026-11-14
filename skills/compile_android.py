#!/usr/bin/env python3
# =============================================================================
# ATLAS — skills/compile_android.py
# Автономный навык сборки Android проектов (Gradle) с выдачей JSON-отчёта.
# =============================================================================
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Подключение утилит контракта skills
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_utils import create_log_file, format_error, make_report, output_report, write_log


def parse_gradle_errors(log_content: str):
    """
    Извлекает ошибки компиляции Kotlin/Java и Gradle из логов сборки.
    Возвращает (errors_list, warnings_count).
    """
    errors = []
    warnings_count = 0

    # Шаблоны Kotlin/Java ошибок: e: /path/to/File.kt: (line, col): message
    kt_pattern = re.compile(r"^[eE]:\s+(?P<file>.+?):\s*\((?P<line>\d+),\s*\d+\):\s*(?P<msg>.+)$")
    # Шаблоны javac: /path/to/File.java:line: error: message
    java_pattern = re.compile(r"^(?P<file>.+?\.java):(?P<line>\d+):\s*error:\s*(?P<msg>.+)$")
    # Предупреждения: w: ...
    warn_pattern = re.compile(r"^[wW]:\s+.*|.*:\s*warning:\s*.*")

    for line in log_content.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        if warn_pattern.match(line_clean):
            warnings_count += 1
            continue

        kt_match = kt_pattern.match(line_clean)
        if kt_match:
            errors.append(format_error(
                message=kt_match.group("msg"),
                file=kt_match.group("file"),
                line=int(kt_match.group("line")),
                severity="error"
            ))
            continue

        java_match = java_pattern.match(line_clean)
        if java_match:
            errors.append(format_error(
                message=java_match.group("msg"),
                file=java_match.group("file"),
                line=int(java_match.group("line")),
                severity="error"
            ))
            continue

        if "FAILURE: Build failed with an exception" in line_clean:
            errors.append(format_error(
                message=line_clean,
                severity="fatal"
            ))

    # Если ошибки есть в выводе, но регулярки не захватили точные строки
    if not errors and ("BUILD FAILED" in log_content or "FAILURE:" in log_content):
        # Поиск последних 3-5 строк перед окончанием
        fail_lines = [l.strip() for l in log_content.splitlines() if "FAILURE:" in l or "What went wrong:" in l or "* Exception is:" in l]
        msg = "; ".join(fail_lines) if fail_lines else "Gradle build failed with unspecified error."
        errors.append(format_error(message=msg, severity="fatal"))

    return errors, warnings_count


def find_apk(project_dir: Path, build_type: str):
    """Ищет сгенерированный APK-файл в типичных каталогах Gradle."""
    search_dirs = [
        project_dir / "app" / "build" / "outputs" / "apk" / build_type,
        project_dir / "build" / "outputs" / "apk" / build_type,
        project_dir
    ]
    for d in search_dirs:
        if d.exists():
            for p in d.rglob("*.apk"):
                # Исключаем промежуточные unaligned/unsigned если есть финальный
                return str(p.resolve())
    return None


def run_android_build(project_path: str, build_type: str = "debug", verbose: bool = False):
    log_file = create_log_file("compile_android")
    project_dir = Path(project_path).resolve()

    write_log(log_file, f"=== ATLAS Android Build: {project_dir} (Build Type: {build_type}) ===")

    if not project_dir.exists():
        err = [format_error(f"Директория проекта не найдена: {project_dir}", severity="fatal")]
        rep = make_report(
            status="failed",
            summary=f"Каталог проекта Android {project_dir} не существует.",
            errors=err,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить путь к проекту и наличие исходных файлов Android."
        )
        output_report(rep, verbose=verbose)
        return

    # Определение gradle wrapper или системного gradle
    gradlew_sh = project_dir / "gradlew"
    gradlew_bat = project_dir / "gradlew.bat"
    if gradlew_sh.exists() and os.name != "nt":
        gradle_cmd = [str(gradlew_sh)]
    elif gradlew_bat.exists() and os.name == "nt":
        gradle_cmd = [str(gradlew_bat)]
    elif gradlew_sh.exists():
        gradle_cmd = ["bash", str(gradlew_sh)]
    else:
        gradle_cmd = ["gradle"]

    task_name = "assembleDebug" if build_type.lower() == "debug" else "assembleRelease"
    cmd = gradle_cmd + [task_name, "--stacktrace"]

    write_log(log_file, f"Executing: {' '.join(cmd)}\n")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        full_output = proc.stdout or ""
        write_log(log_file, full_output)
    except Exception as ex:
        err = [format_error(f"Ошибка вызова Gradle процесса: {ex}", severity="fatal")]
        rep = make_report(
            status="failed",
            summary="Не удалось запустить сборку Gradle из-за ошибки процесса.",
            errors=err,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Убедиться в наличии установленного JDK и прав на запуск gradlew."
        )
        output_report(rep, verbose=verbose)
        return

    errors, warnings_count = parse_gradle_errors(full_output)

    if proc.returncode == 0:
        apk_path = find_apk(project_dir, build_type.lower())
        artifacts = {"full_log": str(log_file)}
        if apk_path:
            artifacts["apk"] = apk_path
            next_act = "APK успешно собран. Передать файл через mobile_bridge.py пользователю или запустить тестирование."
            summary = f"Сборка Android ({build_type}) успешно завершена. APK сгенерирован."
        else:
            artifacts["apk"] = "Not found"
            next_act = "Сборка завершилась без ошибок, но APK файл не найден. Проверить настройки Gradle output."
            summary = f"Сборка Android ({build_type}) успешна, но артефакт APK не обнаружен в стандартном каталоге."

        rep = make_report(
            status="success",
            summary=summary,
            errors=[],
            warnings_count=warnings_count,
            artifacts=artifacts,
            next_action=next_act
        )
    else:
        first_err = errors[0]["message"] if errors else "Неизвестная ошибка сборки"
        target_file = f" в {errors[0]['file']}:{errors[0]['line']}" if errors and errors[0].get("file") else ""
        next_act = f"Исправить ошибку: '{first_err[:100]}'{target_file} и повторить сборку."

        rep = make_report(
            status="failed",
            summary=f"Сборка Android ({build_type}) завершилась с ошибкой. Найдено ошибок: {len(errors)}.",
            errors=errors,
            warnings_count=warnings_count,
            artifacts={"full_log": str(log_file)},
            next_action=next_act
        )

    output_report(rep, verbose=verbose)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATLAS Android Compile Skill")
    parser.add_argument("--project-dir", default=os.environ.get("ATLAS_PROJECT_DIR", "."), help="Путь к Android проекту")
    parser.add_argument("--build-type", default="debug", choices=["debug", "release"], help="Тип сборки (debug|release)")
    parser.add_argument("--verbose", action="store_true", help="Вывод расширенной сводки в stderr")
    args = parser.parse_args()

    run_android_build(project_path=args.project_dir, build_type=args.build_type, verbose=args.verbose)
