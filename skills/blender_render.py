#!/usr/bin/env python3
# =============================================================================
# ATLAS — skills/blender_render.py
# Автономный навык рендера сцен Blender в headless CLI режиме.
# =============================================================================
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_utils import create_log_file, format_error, make_report, output_report, write_log


def parse_blender_errors(log_content: str):
    """Извлекает ошибки рендера Blender, шейдеров и Python API."""
    errors = []
    warnings_count = 0

    blender_err_pattern = re.compile(r"^(?:Error|Fra:\d+\s+Mem:\S+\s+\|\s+Error):\s*(?P<msg>.+)$")
    py_err_pattern = re.compile(r"^(?:Traceback|SyntaxError|RuntimeError|ValueError|AttributeError):\s*(?P<msg>.+)$")

    for line in log_content.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        if "Warning:" in line_clean or line_clean.startswith("Warning :"):
            warnings_count += 1
            continue

        b_match = blender_err_pattern.match(line_clean)
        if b_match:
            errors.append(format_error(
                message=b_match.group("msg"),
                severity="error"
            ))
            continue

        py_match = py_err_pattern.match(line_clean)
        if py_match:
            errors.append(format_error(
                message=line_clean,
                severity="error"
            ))
            continue

        if "CUDA out of memory" in line_clean or "OptiX error" in line_clean:
            errors.append(format_error(
                message=line_clean,
                severity="fatal"
            ))

    return errors, warnings_count


def run_blender_render(
    blend_file: str,
    output_path: str = "",
    frame: int = 1,
    engine: str = "CYCLES",
    python_script: str = "",
    verbose: bool = False
):
    log_file = create_log_file("blender_render")
    blend_p = Path(blend_file).resolve()

    write_log(log_file, f"=== ATLAS Blender Render: {blend_p} (Engine: {engine}, Frame: {frame}) ===\n")

    if not blend_p.exists():
        err = [format_error(f"Файл сцены Blender не найден: {blend_p}", severity="fatal")]
        rep = make_report(
            status="failed",
            summary=f"Файл .blend по пути {blend_p} не существует.",
            errors=err,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить путь к .blend файлу в /workspace/projects/."
        )
        output_report(rep, verbose=verbose)
        return

    blender_bin = shutil.which("blender") or "/opt/blender/blender"
    if not output_path:
        output_path = str(blend_p.parent / f"render_frame_{frame:04d}.png")

    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # Базовая команда Blender headless
    cmd = [
        blender_bin,
        "-b", str(blend_p),
        "-E", engine.upper(),
        "-o", str(out_p),
        "-f", str(frame)
    ]

    # Дополнительный python скрипт автоматизации
    if python_script:
        py_p = Path(python_script).resolve()
        if py_p.exists():
            cmd += ["-P", str(py_p)]
            write_log(log_file, f"Attached Python automation: {py_p}\n")
        else:
            write_log(log_file, f"[Warning] Python script {py_p} not found, proceeding without it.\n")

    write_log(log_file, f"Executing: {' '.join(cmd)}\n")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(blend_p.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600  # 10 минут на рендер кадра
        )
        full_output = proc.stdout or ""
        write_log(log_file, full_output)
    except subprocess.TimeoutExpired:
        err = [format_error("Рендер Blender превысил лимит времени (10 минут).", severity="fatal")]
        rep = make_report(
            status="failed",
            summary="Таймаут выполнения рендера в Blender.",
            errors=err,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Уменьшить количество семплов (samples) или разрешение сцены для ускорения рендера."
        )
        output_report(rep, verbose=verbose)
        return
    except Exception as ex:
        err = [format_error(f"Не удалось запустить Blender: {ex}", severity="fatal")]
        rep = make_report(
            status="failed",
            summary=f"Ошибка процесса Blender: {ex}",
            errors=err,
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Убедиться в наличии установленного Blender в /opt/blender."
        )
        output_report(rep, verbose=verbose)
        return

    errors, warnings_count = parse_blender_errors(full_output)

    # Проверка созданного артефакта изображения (Blender может добавлять номер кадра к имени)
    rendered_file = None
    if out_p.exists():
        rendered_file = str(out_p)
    else:
        # Поиск совпадений типа name0001.png
        possible_matches = list(out_p.parent.glob(f"{out_p.stem}*{out_p.suffix}"))
        if possible_matches:
            rendered_file = str(possible_matches[0].resolve())

    artifacts = {"full_log": str(log_file)}
    if rendered_file:
        artifacts["render_output"] = rendered_file

    if proc.returncode == 0 and rendered_file and not any(e["severity"] == "fatal" for e in errors):
        rep = make_report(
            status="success",
            summary=f"Рендер кадра {frame} сцены {blend_p.name} ({engine}) успешно завершён.",
            errors=[],
            warnings_count=warnings_count,
            artifacts=artifacts,
            next_action="Оценить качество рендера визуально или передать результат в mobile_bridge.py / vision_bridge.py."
        )
    else:
        first_err = errors[0]["message"] if errors else "Неизвестная ошибка рендера Blender"
        rep = make_report(
            status="failed",
            summary=f"Рендер Blender завершился с ошибкой: {first_err[:120]}",
            errors=errors,
            warnings_count=warnings_count,
            artifacts=artifacts,
            next_action="Исправить параметры сцены, проверить пути к материалам или текстурам и запустить рендер повторно."
        )

    output_report(rep, verbose=verbose)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATLAS Blender Headless Render Skill")
    parser.add_argument("--blend-file", required=True, help="Путь к файлу .blend")
    parser.add_argument("--output-path", default="", help="Путь для сохранения рендера")
    parser.add_argument("--frame", type=int, default=1, help="Номер кадра для рендера")
    parser.add_argument("--engine", default="CYCLES", choices=["CYCLES", "BLENDER_EEVEE"], help="Движок рендера")
    parser.add_argument("--python-script", default="", help="Опциональный python-скрипт")
    parser.add_argument("--verbose", action="store_true", help="Вывод сводки в stderr")
    args = parser.parse_args()

    run_blender_render(
        blend_file=args.blend_file,
        output_path=args.output_path,
        frame=args.frame,
        engine=args.engine,
        python_script=args.python_script,
        verbose=args.verbose
    )
