#!/usr/bin/env python3
# =============================================================================
# ATLAS — src/vision_bridge.py
# Захват скриншотов Android-эмулятора (ADB) и окон Unity/X11, кадрирование
# и подготовка оптимизированных изображений для визуального контроля VLM.
# =============================================================================
import argparse
import base64
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None


def capture_adb_screenshot() -> Optional[bytes]:
    """Захватывает скриншот с подключенного по ADB устройства или эмулятора Android."""
    adb_bin = shutil.which("adb")
    if not adb_bin:
        return None

    # Проверка наличия подключенных устройств
    try:
        devices_res = subprocess.run([adb_bin, "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        lines = [line.strip() for line in devices_res.stdout.splitlines() if line.strip() and not line.startswith("List of devices")]
        if not lines:
            return None
    except Exception:
        return None

    # Получение байтов PNG напрямую через exec-out screencap -p
    try:
        cmd = [adb_bin, "exec-out", "screencap", "-p"]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if proc.returncode == 0 and len(proc.stdout) > 100:
            return proc.stdout
    except Exception as e:
        sys.stderr.write(f"[VisionBridge] Ошибка ADB screencap: {e}\n")
    return None


def capture_x11_screenshot(display: str = ":0") -> Optional[bytes]:
    """Захватывает скриншот виртуального X11-дисплея через ffmpeg."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return None

    temp_out = Path("/tmp/x11_capture.png")
    if temp_out.exists():
        temp_out.unlink()

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "x11grab",
        "-video_size", "1920x1080",
        "-i", display,
        "-vframes", "1",
        str(temp_out)
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if proc.returncode == 0 and temp_out.exists():
            data = temp_out.read_bytes()
            temp_out.unlink()
            return data
    except Exception as e:
        sys.stderr.write(f"[VisionBridge] Ошибка X11 capture: {e}\n")
    return None


def capture_screen(source: str = "auto") -> Tuple[Optional[bytes], str]:
    """Выполняет захват экрана в зависимости от выбранного источника."""
    if source == "adb":
        data = capture_adb_screenshot()
        return data, "adb"
    elif source == "x11":
        data = capture_x11_screenshot()
        return data, "x11"
    else:
        # Режим auto: приоритет ADB -> затем X11
        adb_data = capture_adb_screenshot()
        if adb_data:
            return adb_data, "adb"
        x11_data = capture_x11_screenshot()
        if x11_data:
            return x11_data, "x11"
        return None, "none"


def process_image(
    raw_bytes: bytes,
    crop_box: Optional[Tuple[int, int, int, int]] = None,
    max_size: Tuple[int, int] = (1280, 1280),
    quality: int = 85
) -> bytes:
    """
    Кадрирует изображение (если задан crop_box: x, y, width, height),
    масштабирует при превышении max_size и сохраняет в сжатом формате JPEG
    для минимизации количества входных токенов VLM модели.
    """
    if Image is None:
        # Если Pillow не установлен, возвращаем исходные байты
        return raw_bytes

    image = Image.open(io.BytesIO(raw_bytes))
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")

    # Кадрирование: (left, upper, right, lower)
    if crop_box:
        x, y, w, h = crop_box
        box = (x, y, x + w, y + h)
        image = image.crop(box)

    # Пропорциональное уменьшение разрешения, если изображение слишком велико
    image.thumbnail(max_size, Image.Resampling.LANCZOS)

    out_buf = io.BytesIO()
    image.save(out_buf, format="JPEG", quality=quality, optimize=True)
    return out_buf.getvalue()


def to_base64_data_uri(jpeg_bytes: bytes) -> str:
    """Преобразует JPEG байты в строку Data URI для передачи в API vLLM."""
    b64_str = base64.b64encode(jpeg_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64_str}"


def main():
    parser = argparse.ArgumentParser(description="ATLAS Vision Bridge: Screenshot Capture & Token Optimizer")
    parser.add_argument("--source", default="auto", choices=["auto", "adb", "x11"], help="Источник захвата экрана")
    parser.add_argument("--output", default="/workspace/logs/screenshot.jpg", help="Путь сохранения итогового изображения")
    parser.add_argument("--crop", default="", help="Кадрирование в формате x,y,width,height (например 0,100,1080,1820)")
    parser.add_argument("--base64", action="store_true", help="Вывести data-uri в stdout для vLLM API")
    args = parser.parse_args()

    crop_box = None
    if args.crop:
        try:
            parts = [int(p.strip()) for p in args.crop.split(",")]
            if len(parts) == 4:
                crop_box = tuple(parts)
        except ValueError:
            sys.stderr.write(f"[VisionBridge] Некорректный формат crop: '{args.crop}', ожидается x,y,w,h\n")

    raw_data, detected_source = capture_screen(source=args.source)
    if not raw_data:
        sys.stderr.write("[VisionBridge] Ошибка: не удалось захватить экран (устройства ADB и X11 не обнаружены).\n")
        # Создаем тестовую заглушку изображения, если устройства недоступны (для тестов вне контейнера)
        if Image is not None:
            img = Image.new("RGB", (640, 360), color=(40, 44, 52))
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            raw_data = buf.getvalue()
            detected_source = "placeholder"
        else:
            sys.exit(1)

    optimized_jpeg = process_image(raw_data, crop_box=crop_box)

    # Сохранение на диск
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(optimized_jpeg)
    sys.stderr.write(f"[VisionBridge] Скриншот сохранён ({detected_source}): {out_path} ({len(optimized_jpeg)} байт)\n")

    if args.base64:
        print(to_base64_data_uri(optimized_jpeg))


if __name__ == "__main__":
    main()
