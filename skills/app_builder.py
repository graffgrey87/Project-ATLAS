#!/usr/bin/env python3
# =============================================================================
# ATLAS — skills/app_builder.py
# Универсальный навык проверки и сборки приложений/игр (Android, Godot 4, Python).
# Возвращает строго валидный JSON по контракту skills/_schema.json.
# =============================================================================
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_utils import SCHEMA_PATH, create_log_file, format_error, make_report, output_report, write_log


def _detect_project_type(project_dir: Path) -> str:
    if (project_dir / "project.godot").exists():
        return "godot"
    if (
        (project_dir / "settings.gradle").exists()
        or (project_dir / "settings.gradle.kts").exists()
        or (project_dir / "gradlew").exists()
    ):
        return "android"
    if list(project_dir.rglob("*.py")):
        return "python"
    return "unknown"


def _build_android(project_dir: Path, artifacts_dir: Path, log_file: Path) -> Dict[str, Any]:
    required_any = [
        ("settings.gradle", "settings.gradle.kts"),
        ("build.gradle", "build.gradle.kts"),
    ]
    missing = [
        "/".join(pair)
        for pair in required_any
        if not any((project_dir / name).exists() for name in pair)
    ]
    if missing:
        return make_report(
            status="failed",
            summary=f"Нарушена структура Gradle проекта Android (отсутствуют: {', '.join(missing)}).",
            errors=[format_error(f"Отсутствуют файлы Gradle: {', '.join(missing)}", severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить структуру проекта Android и наличие settings.gradle(.kts) / build.gradle(.kts).",
        )

    gradlew_sh = project_dir / "gradlew"
    if gradlew_sh.exists() and os.name != "nt":
        if not os.access(gradlew_sh, os.X_OK):
            os.chmod(gradlew_sh, 0o755)
        gradle_cmd = [str(gradlew_sh)]
    elif gradlew_sh.exists():
        gradle_cmd = ["bash", str(gradlew_sh)]
    else:
        gradle_cmd = ["gradle"]

    cmd = gradle_cmd + ["assembleDebug", "testDebugUnitTest", "--stacktrace"]
    write_log(log_file, f"[Android] Executing: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(project_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    write_log(log_file, proc.stdout or "")

    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").splitlines()[-25:])
        return make_report(
            status="failed",
            summary="Сборка assembleDebug или тесты testDebugUnitTest завершились с ошибкой.",
            errors=[format_error(f"Gradle exited with {proc.returncode}: {tail[:500]}", severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Изучить full_log, исправить ошибки компиляции/тестов и перезапустить app_builder.",
        )

    apk_candidates = list((project_dir / "app" / "build" / "outputs" / "apk" / "debug").glob("*.apk"))
    if not apk_candidates:
        apk_candidates = list(project_dir.rglob("*.apk"))
    if not apk_candidates:
        return make_report(
            status="failed",
            summary="Сборка Gradle прошла, но файл .apk не найден.",
            errors=[format_error("APK не обнаружен в build/outputs/apk/debug", severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить конфигурацию app/build.gradle(.kts).",
        )

    src_apk = apk_candidates[0].resolve()
    has_dex = False
    with zipfile.ZipFile(src_apk, "r") as zf:
        has_dex = any(name == "classes.dex" or name.endswith("/classes.dex") or name.startswith("classes") and name.endswith(".dex") for name in zf.namelist())

    if not has_dex:
        return make_report(
            status="failed",
            summary=f"APK {src_apk.name} собран, но внутри отсутствует classes.dex.",
            errors=[format_error("classes.dex не найден внутри APK-архива", file=str(src_apk), severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить исходный код и конфигурацию AndroidManifest / Gradle.",
        )

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_name = f"{src_apk.stem}_{ts}.apk"
    dest_apk = (artifacts_dir / stamped_name).resolve()
    shutil.copy2(src_apk, dest_apk)
    write_log(log_file, f"[Android] APK скопирован с таймстампом: {dest_apk}")

    return make_report(
        status="success",
        summary=f"Android assembleDebug + testDebugUnitTest успешны, classes.dex подтверждён ({dest_apk.name}).",
        errors=[],
        warnings_count=0,
        artifacts={"full_log": str(log_file), "apk": str(dest_apk)},
        next_action="Передать собранный APK пользователю в Telegram.",
    )


def _build_godot(project_dir: Path, log_file: Path) -> Dict[str, Any]:
    if not (project_dir / "project.godot").exists():
        return make_report(
            status="failed",
            summary="Файл project.godot не найден.",
            errors=[format_error("Отсутствует project.godot", severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить путь к проекту Godot 4.",
        )

    godot_bin = shutil.which("godot4") or shutil.which("godot")
    if not godot_bin:
        gd_files = list(project_dir.rglob("*.gd"))
        return make_report(
            status="partial",
            summary=f"project.godot найден ({len(gd_files)} .gd файлов), но бинарник godot4/godot не установлен в PATH.",
            errors=[],
            warnings_count=1,
            artifacts={"full_log": str(log_file), "gd_files_count": len(gd_files)},
            next_action="Установить Godot 4 headless для полного прогона.",
        )

    proc = subprocess.run(
        [godot_bin, "--headless", "--quit", "--path", str(project_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
    )
    write_log(log_file, proc.stdout or "")
    if proc.returncode != 0:
        return make_report(
            status="failed",
            summary="Godot 4 headless прогон завершился с ошибкой.",
            errors=[format_error((proc.stdout or "")[-500:], severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Исправить ошибки скриптов/сцен в Godot проекте.",
        )

    return make_report(
        status="success",
        summary="Godot 4 headless-валидация проекта прошла успешно.",
        errors=[],
        warnings_count=0,
        artifacts={"full_log": str(log_file)},
        next_action="Проект Godot 4 готов к экспорту.",
    )


def _build_python(project_dir: Path, log_file: Path) -> Dict[str, Any]:
    py_files = [
        p for p in project_dir.rglob("*.py")
        if ".venv" not in p.parts and "__pycache__" not in p.parts
    ]
    errors: List[Dict[str, Any]] = []
    for p in py_files:
        res = subprocess.run(
            [sys.executable, "-m", "py_compile", str(p)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if res.returncode != 0:
            errors.append(format_error(res.stdout.strip(), file=str(p), severity="error"))

    if errors:
        return make_report(
            status="failed",
            summary=f"Обнаружены синтаксические ошибки в {len(errors)} Python-файлах.",
            errors=errors,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Исправить синтаксические ошибки в указанных Python-файлах.",
        )

    tests_ran = "py_compile only"
    if (project_dir / "tests").exists() or list(project_dir.rglob("test_*.py")):
        pytest_bin = shutil.which("pytest")
        cmd = [pytest_bin, "-q"] if pytest_bin else [sys.executable, "-m", "unittest", "discover"]
        t_proc = subprocess.run(cmd, cwd=str(project_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        write_log(log_file, t_proc.stdout or "")
        tests_ran = " ".join(cmd)
        if t_proc.returncode != 0 and t_proc.returncode != 5:
            return make_report(
                status="failed",
                summary="Автотесты Python завершились с ошибкой.",
                errors=[format_error((t_proc.stdout or "")[-500:], severity="error")],
                warnings_count=0,
                artifacts={"full_log": str(log_file)},
                next_action="Исправить падающие тесты Python.",
            )

    return make_report(
        status="success",
        summary=f"Проверено {len(py_files)} Python-файлов ({tests_ran}).",
        errors=[],
        warnings_count=0,
        artifacts={"full_log": str(log_file), "checked_files": len(py_files)},
        next_action="Python-проект готов к запуску.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="ATLAS Skill: Universal App & Game Builder (Android/Godot4/Python)")
    parser.add_argument("--project-dir", default=".", help="Путь к директории проекта")
    parser.add_argument("--type", dest="project_type", choices=["auto", "android", "godot", "python"], default="auto", help="Тип проекта")
    parser.add_argument("--artifacts-dir", default=os.environ.get("ATLAS_ARTIFACTS_DIR", "./artifacts"), help="Папка раздачи артефактов")
    parser.add_argument("--schema", action="store_true", help="Вывести JSON-схему контракта и выйти")
    parser.add_argument("--verbose", action="store_true", help="Подробный вывод в stderr")
    args = parser.parse_args()

    if args.schema:
        print(SCHEMA_PATH.read_text(encoding="utf-8"))
        return

    log_file = create_log_file("app_builder")
    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists():
        rep = make_report(
            status="failed",
            summary=f"Директория проекта не найдена: {project_dir}",
            errors=[format_error(f"Каталог не существует: {project_dir}", severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить путь к проекту.",
        )
        output_report(rep, verbose=args.verbose)
        return

    ptype = _detect_project_type(project_dir) if args.project_type == "auto" else args.project_type
    write_log(log_file, f"[app_builder] project_dir={project_dir}, type={ptype}")

    try:
        if ptype == "android":
            rep = _build_android(project_dir, Path(args.artifacts_dir).resolve(), log_file)
        elif ptype == "godot":
            rep = _build_godot(project_dir, log_file)
        elif ptype == "python":
            rep = _build_python(project_dir, log_file)
        else:
            rep = make_report(
                status="failed",
                summary=f"Не удалось определить тип проекта в {project_dir}.",
                errors=[format_error("Не найдены маркеры Android, Godot 4 или Python", severity="fatal")],
                warnings_count=0,
                artifacts={"full_log": str(log_file)},
                next_action="Указать тип проекта явно через --type android|godot|python.",
            )
        output_report(rep, verbose=args.verbose)
    except Exception as ex:
        write_log(log_file, f"ERROR: {ex}")
        rep = make_report(
            status="failed",
            summary=f"Критическая ошибка app_builder: {ex}",
            errors=[format_error(str(ex), severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить full_log и окружение сборки.",
        )
        output_report(rep, verbose=args.verbose)


if __name__ == "__main__":
    main()
