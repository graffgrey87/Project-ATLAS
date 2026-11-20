#!/usr/bin/env python3
# =============================================================================
# ATLAS — skills/unity_build.py
# Автономный навык сборки проектов Unity в headless-режиме с автоматической
# проверкой и активацией лицензии (Personal / Plus / Pro).
# =============================================================================
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_utils import SCHEMA_PATH, create_log_file, format_error, make_report, output_report, write_log


def get_unity_license_path() -> Path:
    """Возвращает стандартный путь к файлу лицензии Unity в Linux."""
    home = Path.home()
    return home / ".local" / "share" / "unity3d" / "Unity" / "Unity_lic.ulf"


def ensure_unity_license(log_file: Path, verbose: bool = False) -> (bool, str):
    """
    Проверяет наличие лицензии Unity. При отсутствии активирует через .ulf
    или учетные данные CLI.
    Возвращает (is_activated, message).
    """
    lic_file = get_unity_license_path()
    if lic_file.exists() and lic_file.stat().st_size > 0:
        write_log(log_file, f"[Unity License] Лицензия найдена: {lic_file}\n")
        return True, "Лицензия Unity уже активирована."

    write_log(log_file, f"[Unity License] Файл лицензии {lic_file} отсутствует. Попытка активации...\n")

    # Вариант 1: активация через контент .ulf из переменной UNITY_LICENSE
    env_license = os.environ.get("UNITY_LICENSE", "").strip()
    if env_license:
        try:
            lic_file.parent.mkdir(parents=True, exist_ok=True)
            with open(lic_file, "w", encoding="utf-8") as f:
                f.write(env_license)
            write_log(log_file, f"[Unity License] Успешно записан .ulf из переменной UNITY_LICENSE ({len(env_license)} байт).\n")
            return True, "Лицензия Unity активирована через переменную UNITY_LICENSE (.ulf)."
        except Exception as e:
            msg = f"Не удалось записать файл лицензии: {e}"
            write_log(log_file, f"[Unity License Error] {msg}\n")
            return False, msg

    # Вариант 2: активация через серийный номер (Plus/Pro)
    serial = os.environ.get("UNITY_SERIAL", "").strip()
    email = os.environ.get("UNITY_EMAIL", "").strip()
    password = os.environ.get("UNITY_PASSWORD", "").strip()

    if serial and email and password:
        unity_bin = shutil.which("Unity") or "/opt/unity/Editor/Unity"
        act_cmd = [
            unity_bin,
            "-quit",
            "-batchmode",
            "-nographics",
            "-serial", serial,
            "-username", email,
            "-password", password,
            "-logFile", str(log_file)
        ]
        write_log(log_file, "[Unity License] Вызов активации по серийному номеру...\n")
        try:
            res = subprocess.run(act_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
            write_log(log_file, res.stdout or "")
            if lic_file.exists() and lic_file.stat().st_size > 0:
                return True, "Лицензия Unity успешно активирована по серийному номеру."
            else:
                return False, "Процесс активации Unity CLI завершился, но файл лицензии не создан. Проверьте учетные данные."
        except Exception as ex:
            return False, f"Ошибка при запуске команды активации Unity: {ex}"

    # Если ни один из способов не настроен
    missing_msg = (
        "Лицензия Unity не найдена. Требуется настроить переменные окружения в .env:\n"
        "1) Либо UNITY_LICENSE (содержимое .ulf файла для Personal)\n"
        "2) Либо UNITY_SERIAL, UNITY_EMAIL, UNITY_PASSWORD (для Plus/Pro)."
    )
    write_log(log_file, f"[Unity License Warning] {missing_msg}\n")
    return False, missing_msg


def parse_unity_errors(log_content: str):
    """Парсит журнал Unity на наличие ошибок компиляции C# и сбоев сборки."""
    errors = []
    warnings_count = 0

    # Ошибки компилятора C#: Assets/Scripts/Player.cs(12,25): error CS1002: ; expected
    cs_pattern = re.compile(r"^(?P<file>.+?\.[cC][sS])\((?P<line>\d+),\d+\):\s*error\s*(?P<code>CS\d+):\s*(?P<msg>.+)$")
    # Общие ошибки Unity: Error: ...
    unity_err_pattern = re.compile(r"^(?:\[Error\]|Error:|\*\*\*\* BuildFailedException:)\s*(?P<msg>.+)$")

    for line in log_content.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        if "warning CS" in line_clean or line_clean.startswith("[Warning]") or "Warning:" in line_clean:
            warnings_count += 1
            continue

        cs_match = cs_pattern.match(line_clean)
        if cs_match:
            errors.append(format_error(
                message=f"[{cs_match.group('code')}] {cs_match.group('msg')}",
                file=cs_match.group("file"),
                line=int(cs_match.group("line")),
                severity="error"
            ))
            continue

        err_match = unity_err_pattern.match(line_clean)
        if err_match:
            errors.append(format_error(
                message=err_match.group("msg"),
                severity="error"
            ))
            continue

        if "No valid Unity Editor license found" in line_clean:
            errors.append(format_error(
                message="No valid Unity Editor license found. Лицензия не активирована.",
                severity="fatal"
            ))

    return errors, warnings_count


def run_unity_build(
    project_path: str,
    build_target: str = "Android",
    execute_method: str = "",
    output_path: str = "",
    verbose: bool = False
):
    log_file = create_log_file("unity_build")
    project_dir = Path(project_path).resolve()

    write_log(log_file, f"=== ATLAS Unity Build: {project_dir} (Target: {build_target}) ===\n")

    # 1. Проверка директории проекта
    if not project_dir.exists():
        err = [format_error(f"Директория Unity проекта не найдена: {project_dir}", severity="fatal")]
        rep = make_report(
            status="failed",
            summary=f"Каталог проекта Unity {project_dir} не существует.",
            errors=err,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить путь к Unity проекту в /workspace/projects/."
        )
        output_report(rep, verbose=verbose)
        return

    # 2. Обязательная проверка и активация лицензии
    lic_ok, lic_msg = ensure_unity_license(log_file, verbose=verbose)
    if not lic_ok:
        err = [format_error(lic_msg, severity="fatal")]
        rep = make_report(
            status="failed",
            summary="Сборка Unity остановлена: отсутствует активная лицензия Unity Editor.",
            errors=err,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Сгенерировать .ulf через Unity Hub на локальном ПК и прописать в .env переменную UNITY_LICENSE."
        )
        output_report(rep, verbose=verbose)
        return

    # 3. Формирование команды Unity
    unity_bin = shutil.which("Unity") or "/opt/unity/Editor/Unity"
    cmd = [
        unity_bin,
        "-quit",
        "-batchmode",
        "-nographics",
        "-projectPath", str(project_dir),
        "-buildTarget", build_target,
        "-logFile", str(log_file)
    ]

    if execute_method:
        cmd += ["-executeMethod", execute_method]

    if output_path:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        # Передаем кастомный аргумент сборки, если поддерживается скриптом сборки проекта
        cmd += ["-customBuildPath", str(out_p)]

    write_log(log_file, f"Executing: {' '.join(cmd)}\n")

    # 4. Запуск сборки
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=1800  # До 30 минут на сложные Unity сборки
        )
    except subprocess.TimeoutExpired:
        err = [format_error("Сборка Unity превысила максимальный лимит времени (30 минут).", severity="fatal")]
        rep = make_report(
            status="failed",
            summary="Таймаут сборки Unity Editor.",
            errors=err,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить лог на наличие бесконечных циклов в OnPostProcessBuild или компиляции шейдеров."
        )
        output_report(rep, verbose=verbose)
        return
    except Exception as ex:
        err = [format_error(f"Не удалось запустить Unity Editor: {ex}", severity="fatal")]
        rep = make_report(
            status="failed",
            summary=f"Ошибка процесса Unity Editor: {ex}",
            errors=err,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить корректность установки Unity Editor CLI в /opt/unity."
        )
        output_report(rep, verbose=verbose)
        return

    # 5. Анализ лога
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            log_content = f.read()
    except Exception:
        log_content = proc.stdout or ""

    errors, warnings_count = parse_unity_errors(log_content)

    # 6. Формирование артефактов
    artifacts = {"full_log": str(log_file)}
    if output_path and Path(output_path).exists():
        artifacts["build_output"] = str(Path(output_path).resolve())
        if output_path.endswith(".apk"):
            artifacts["apk"] = artifacts["build_output"]

    if proc.returncode == 0 and not any(e["severity"] == "fatal" for e in errors):
        rep = make_report(
            status="success",
            summary=f"Сборка Unity ({build_target}) успешно завершена без критических ошибок.",
            errors=[],
            warnings_count=warnings_count,
            artifacts=artifacts,
            next_action="Проверить артефакты сборки или запустить визуальное тестирование через vision_bridge.py."
        )
    else:
        first_err = errors[0]["message"] if errors else "Unity Editor exited with non-zero status"
        target_file = f" в {errors[0]['file']}:{errors[0]['line']}" if errors and errors[0].get("file") else ""
        next_act = f"Исправить ошибку Unity: '{first_err[:100]}'{target_file}."

        rep = make_report(
            status="failed",
            summary=f"Сборка Unity ({build_target}) завершилась с ошибкой. Найдено ошибок: {len(errors)}.",
            errors=errors,
            warnings_count=warnings_count,
            artifacts=artifacts,
            next_action=next_act
        )

    output_report(rep, verbose=verbose)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATLAS Unity Headless Build Skill")
    parser.add_argument("--project-dir", default=os.environ.get("ATLAS_UNITY_DIR", "."), help="Путь к Unity проекту")
    parser.add_argument("--build-target", default="Android", help="Build Target (Android, StandaloneLinux64, etc.)")
    parser.add_argument("--execute-method", default="", help="Статический метод C# сборки (e.g. BuildScript.PerformBuild)")
    parser.add_argument("--output-path", default="", help="Путь к результирующему файлу (например build/game.apk)")
    parser.add_argument("--schema", action="store_true", help="Вывести JSON-схему контракта и выйти")
    parser.add_argument("--verbose", action="store_true", help="Вывод сводки в stderr")
    args = parser.parse_args()

    if args.schema:
        print(SCHEMA_PATH.read_text(encoding="utf-8"))
        sys.exit(0)

    run_unity_build(
        project_path=args.project_dir,
        build_target=args.build_target,
        execute_method=args.execute_method,
        output_path=args.output_path,
        verbose=args.verbose
    )
