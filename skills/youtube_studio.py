#!/usr/bin/env python3
# =============================================================================
# ATLAS — skills/youtube_studio.py
# Полный конвейер сборки видео для безликого YouTube-канала:
# 1. TTS (edge-tts) -> voice.mp3 + vtt
# 2. ASR / Subtitles (faster-whisper или fallback из edge-tts vtt -> .srt/.ass)
# 3. Визуальный ряд (ComfyUI / локальные ассеты / процедурный фон)
# 4. FFmpeg (16:9 / 9:16, Ken Burns zoompan, sidechain ducking музыки, субтитры, h264_nvenc/libx264)
# =============================================================================
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_utils import SCHEMA_PATH, create_log_file, format_error, make_report, output_report, write_log


def _detect_video_encoder() -> str:
    """Определяет наличие аппаратного ускорения h264_nvenc (GPU), иначе libx264."""
    try:
        nvidia_ok = subprocess.run(
            ["nvidia-smi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3
        ).returncode == 0
        if not nvidia_ok:
            return "libx264"
        enc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        if "h264_nvenc" in (enc.stdout or ""):
            return "h264_nvenc"
    except Exception:
        pass
    return "libx264"


def _get_audio_duration(audio_path: Path) -> float:
    """Возвращает длительность аудиофайла в секундах через ffprobe."""
    res = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
    )
    try:
        return max(1.0, float((res.stdout or "0").strip()))
    except ValueError:
        return 10.0


async def _generate_tts_edge(
    text: str,
    audio_out: Path,
    vtt_out: Path,
    voice: str,
    rate: str,
    pitch: str,
) -> None:
    """Генерирует озвучку и VTT-субтитры через edge-tts (Python API или CLI)."""
    try:
        import edge_tts  # type: ignore

        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        submaker = edge_tts.SubMaker()
        with open(audio_out, "wb") as f_audio:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f_audio.write(chunk["data"])
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    submaker.feed(chunk)
        vtt_content = submaker.get_srt() if hasattr(submaker, "get_srt") else ""
        if not vtt_content and hasattr(submaker, "generate_subs"):
            vtt_content = submaker.generate_subs()
        vtt_out.write_text(vtt_content or "", encoding="utf-8")
    except ImportError:
        cmd = [
            "edge-tts",
            "--text", text,
            "--voice", voice,
            f"--rate={rate}",
            f"--pitch={pitch}",
            "--write-media", str(audio_out),
            "--write-subtitles", str(vtt_out),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(f"edge-tts CLI failed: {proc.stdout}")


def _format_srt_ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms_rem = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"


def _vtt_to_srt(vtt_text: str) -> str:
    """Конвертирует WebVTT (от edge-tts) в SRT."""
    lines = vtt_text.replace("\r\n", "\n").splitlines()
    blocks: List[str] = []
    idx = 1
    i = 0
    ts_re = re.compile(r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})")
    while i < len(lines):
        line = lines[i].strip()
        m = ts_re.search(line)
        if m:
            start = m.group(1).replace(".", ",")
            end = m.group(2).replace(".", ",")
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i].strip())
                i += 1
            if text_lines:
                blocks.append(f"{idx}\n{start} --> {end}\n" + "\n".join(text_lines))
                idx += 1
        i += 1
    return "\n\n".join(blocks)


def _generate_subtitles(
    audio_path: Path,
    vtt_fallback_path: Path,
    script_text: str,
    srt_out: Path,
    log_file: Path,
) -> str:
    """Генерирует .srt через faster-whisper (если доступен) либо из метаданных edge-tts."""
    try:
        from faster_whisper import WhisperModel  # type: ignore

        device = "cpu"
        compute_type = "int8"
        try:
            import torch  # type: ignore
            if torch.cuda.is_available():
                device = "cuda"
                compute_type = "float16"
        except Exception:
            pass

        write_log(log_file, f"[ASR] Запуск faster-whisper (device={device}, compute={compute_type})")
        model = WhisperModel("base", device=device, compute_type=compute_type)
        segments, _info = model.transcribe(str(audio_path), word_timestamps=True)
        srt_blocks: List[str] = []
        idx = 1
        for seg in segments:
            words = getattr(seg, "words", None) or []
            if words:
                # Группируем по 3-4 слова для динамичных субтитров
                chunk: List[Any] = []
                for w in words:
                    chunk.append(w)
                    if len(chunk) >= 4:
                        st = _format_srt_ts(chunk[0].start)
                        en = _format_srt_ts(chunk[-1].end)
                        txt = " ".join(x.word.strip() for x in chunk).strip()
                        if txt:
                            srt_blocks.append(f"{idx}\n{st} --> {en}\n{txt}")
                            idx += 1
                        chunk = []
                if chunk:
                    st = _format_srt_ts(chunk[0].start)
                    en = _format_srt_ts(chunk[-1].end)
                    txt = " ".join(x.word.strip() for x in chunk).strip()
                    if txt:
                        srt_blocks.append(f"{idx}\n{st} --> {en}\n{txt}")
                        idx += 1
            else:
                st = _format_srt_ts(seg.start)
                en = _format_srt_ts(seg.end)
                txt = (seg.text or "").strip()
                if txt:
                    srt_blocks.append(f"{idx}\n{st} --> {en}\n{txt}")
                    idx += 1
        if srt_blocks:
            srt_out.write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8")
            return "faster-whisper"
    except Exception as ex:
        write_log(log_file, f"[ASR] faster-whisper недоступен ({ex}), используется fallback из edge-tts")

    raw_sub = vtt_fallback_path.read_text(encoding="utf-8", errors="replace") if vtt_fallback_path.exists() else ""
    if "-->" in raw_sub:
        converted = _vtt_to_srt(raw_sub) if "WEBVTT" in raw_sub else raw_sub
        if converted.strip():
            srt_out.write_text(converted, encoding="utf-8")
            return "edge-tts-subtitles"

    # Последний резерв: равномерная разбивка текста по длительности аудио
    duration = _get_audio_duration(audio_path)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script_text.strip()) if s.strip()] or [script_text.strip()]
    step = duration / len(sentences)
    blocks = []
    for i, sent in enumerate(sentences):
        blocks.append(f"{i + 1}\n{_format_srt_ts(i * step)} --> {_format_srt_ts((i + 1) * step)}\n{sent}")
    srt_out.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return "uniform-fallback"


def _collect_visual_assets(assets_dir: Optional[Path], work_dir: Path, width: int, height: int) -> List[Path]:
    """Собирает изображения/видео из assets_dir или создаёт процедурный фон."""
    exts = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mkv", ".webm"}
    found: List[Path] = []
    if assets_dir and assets_dir.exists():
        for p in sorted(assets_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in exts:
                found.append(p)
    if found:
        return found

    # Процедурный тёмный фон через FFmpeg, если ассетов нет
    bg_path = work_dir / "fallback_bg.png"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=#0f172a:s={width}x{height}:d=1",
            "-frames:v", "1", str(bg_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return [bg_path]


def _assemble_video_ffmpeg(
    assets: List[Path],
    audio_path: Path,
    srt_path: Path,
    output_path: Path,
    video_format: str,
    music_path: Optional[Path],
    encoder: str,
    work_dir: Path,
    log_file: Path,
) -> None:
    width, height = (1080, 1920) if video_format == "9:16" else (1920, 1080)
    fps = 30
    total_dur = _get_audio_duration(audio_path)
    clip_dur = max(2.0, total_dur / max(1, len(assets)))

    clip_paths: List[Path] = []
    img_exts = {".png", ".jpg", ".jpeg", ".webp"}
    for idx, asset in enumerate(assets):
        clip_out = work_dir / f"clip_{idx:03d}.mp4"
        if asset.suffix.lower() in img_exts:
            frames = max(30, int(clip_dur * fps))
            # Ken Burns (zoompan) с плавным зумом
            vf = (
                f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                f"crop={width * 2}:{height * 2},"
                f"zoompan=z='min(zoom+0.0012,1.15)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps},"
                f"format=yuv420p"
            )
            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", str(asset),
                "-vf", vf, "-t", f"{clip_dur:.2f}",
                "-c:v", encoder, "-an", str(clip_out),
            ]
        else:
            vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps={fps},format=yuv420p"
            )
            cmd = [
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(asset),
                "-vf", vf, "-t", f"{clip_dur:.2f}",
                "-c:v", encoder, "-an", str(clip_out),
            ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        write_log(log_file, f"[FFmpeg clip {idx}] rc={proc.returncode}")
        if proc.returncode != 0:
            raise RuntimeError(f"Ошибка подготовки клипа {asset.name}: {proc.stdout[-500:]}")
        clip_paths.append(clip_out)

    concat_txt = work_dir / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in clip_paths), encoding="utf-8")
    merged_video = work_dir / "merged_video.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-t", f"{total_dur:.2f}", "-c", "copy", str(merged_video),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )

    # Экранирование пути субтитров для FFmpeg filtergraph
    srt_escaped = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
    sub_style = "FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1"
    vf_sub = f"subtitles='{srt_escaped}':force_style='{sub_style}'"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if music_path and music_path.exists():
        # Sidechain ducking: приглушаем фоновую музыку под голосом
        filter_complex = (
            "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,asplit=2[voice][sc];"
            "[2:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=0.22[music];"
            "[music][sc]sidechaincompress=threshold=0.02:ratio=6:attack=50:release=300[ducked];"
            "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        final_cmd = [
            "ffmpeg", "-y",
            "-i", str(merged_video),
            "-i", str(audio_path),
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex", filter_complex,
            "-vf", vf_sub,
            "-map", "0:v:0", "-map", "[aout]",
            "-c:v", encoder, "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(output_path),
        ]
    else:
        final_cmd = [
            "ffmpeg", "-y",
            "-i", str(merged_video),
            "-i", str(audio_path),
            "-vf", vf_sub,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", encoder, "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(output_path),
        ]

    proc = subprocess.run(final_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    write_log(log_file, f"[FFmpeg final] rc={proc.returncode}\n{proc.stdout[-1500:]}")
    if proc.returncode != 0:
        raise RuntimeError(f"Ошибка финального рендера FFmpeg: {proc.stdout[-600:]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ATLAS Skill: Faceless YouTube Video Assembly Pipeline")
    parser.add_argument("--script", default="", help="Путь к текстовому файлу сценария")
    parser.add_argument("--text", default="", help="Текст сценария напрямую (если не передан --script)")
    parser.add_argument("--output", default="./artifacts/youtube_output.mp4", help="Путь к итоговому .mp4")
    parser.add_argument("--format", dest="video_format", choices=["16:9", "9:16"], default="16:9", help="Формат видео")
    parser.add_argument("--assets-dir", default="", help="Папка с локальными изображениями/видео")
    parser.add_argument("--music", default="", help="Путь к фоновой музыке (опционально)")
    parser.add_argument("--voice", default="ru-RU-DmitryNeural", help="Голос edge-tts")
    parser.add_argument("--rate", default="+0%", help="Скорость речи edge-tts")
    parser.add_argument("--pitch", default="+0Hz", help="Тон голоса edge-tts")
    parser.add_argument("--schema", action="store_true", help="Вывести JSON-схему контракта и выйти")
    parser.add_argument("--verbose", action="store_true", help="Подробный вывод в stderr")
    args = parser.parse_args()

    if args.schema:
        print(SCHEMA_PATH.read_text(encoding="utf-8"))
        return

    log_file = create_log_file("youtube_studio")

    if not args.script and not args.text.strip():
        rep = make_report(
            status="failed",
            summary="Не передан сценарий (--script или --text).",
            errors=[format_error("Укажите --script <file.txt> или --text <string>", severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Передать текстовый сценарий и повторить запуск.",
        )
        output_report(rep, verbose=args.verbose)
        return

    try:
        script_text = Path(args.script).read_text(encoding="utf-8") if args.script else args.text.strip()
        out_mp4 = Path(args.output).resolve()
        width, height = (1080, 1920) if args.video_format == "9:16" else (1920, 1080)
        encoder = _detect_video_encoder()
        write_log(log_file, f"[Studio] Format={args.video_format}, Encoder={encoder}, Voice={args.voice}")

        with tempfile.TemporaryDirectory(prefix="atlas_yt_") as tmp:
            work_dir = Path(tmp)
            voice_mp3 = work_dir / "voice.mp3"
            voice_vtt = work_dir / "voice.vtt"
            subs_srt = out_mp4.with_suffix(".srt")
            out_mp4.parent.mkdir(parents=True, exist_ok=True)

            asyncio.run(_generate_tts_edge(script_text, voice_mp3, voice_vtt, args.voice, args.rate, args.pitch))
            asr_engine = _generate_subtitles(voice_mp3, voice_vtt, script_text, subs_srt, log_file)

            assets_dir = Path(args.assets_dir).resolve() if args.assets_dir else None
            assets = _collect_visual_assets(assets_dir, work_dir, width, height)
            music_path = Path(args.music).resolve() if args.music else None

            _assemble_video_ffmpeg(
                assets=assets,
                audio_path=voice_mp3,
                srt_path=subs_srt,
                output_path=out_mp4,
                video_format=args.video_format,
                music_path=music_path,
                encoder=encoder,
                work_dir=work_dir,
                log_file=log_file,
            )

        rep = make_report(
            status="success",
            summary=f"Видео {out_mp4.name} ({args.video_format}, {encoder}, ASR={asr_engine}) успешно собрано.",
            errors=[],
            warnings_count=0,
            artifacts={
                "full_log": str(log_file),
                "video": str(out_mp4),
                "subtitles": str(subs_srt),
                "encoder": encoder,
                "asr_engine": asr_engine,
            },
            next_action="Проверить итоговый ролик и опубликовать на канале.",
        )
        output_report(rep, verbose=args.verbose)

    except Exception as ex:
        write_log(log_file, f"ERROR: {ex}")
        rep = make_report(
            status="failed",
            summary=f"Ошибка сборки видео в youtube_studio: {ex}",
            errors=[format_error(str(ex), severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить наличие ffmpeg, edge-tts и входных ассетов в логе.",
        )
        output_report(rep, verbose=args.verbose)


if __name__ == "__main__":
    main()
