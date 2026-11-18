#!/usr/bin/env python3
# =============================================================================
# ATLAS — skills/comfyui_client.py
# Клиент для внешнего ComfyUI на RunPod (ping + /prompt + polling + download).
# При недоступности сервера не падает, а возвращает offline/local_assets fallback.
# =============================================================================
import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import uuid

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore
    import urllib.request
    import urllib.error

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_utils import SCHEMA_PATH, create_log_file, format_error, make_report, output_report, write_log


def get_comfyui_url(override_url: str = "") -> str:
    url = (override_url or os.environ.get("COMFYUI_API_URL", "")).strip()
    return url.rstrip("/")


def ping_comfyui(api_url: str, timeout: float = 5.0) -> Dict[str, Any]:
    """Проверяет доступность сервера ComfyUI. При недоступности возвращает offline-статус."""
    if not api_url:
        return {"status": "offline", "fallback": "local_assets", "reason": "COMFYUI_API_URL не задан"}
    try:
        if httpx is not None:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(f"{api_url}/system_stats")
                if resp.status_code == 200:
                    return {"status": "online", "url": api_url, "system_stats": resp.json()}
                return {
                    "status": "offline",
                    "fallback": "local_assets",
                    "reason": f"HTTP {resp.status_code}",
                }
        else:
            req = urllib.request.Request(f"{api_url}/system_stats")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return {"status": "online", "url": api_url, "system_stats": json.loads(resp.read().decode("utf-8"))}
                return {"status": "offline", "fallback": "local_assets", "reason": f"HTTP {resp.status}"}
    except Exception as ex:
        return {"status": "offline", "fallback": "local_assets", "reason": str(ex)}


def _build_default_txt2img_workflow(prompt_text: str, width: int = 1280, height: int = 720) -> Dict[str, Any]:
    """Минимальный стандартный ComfyUI API-воркфлоу для генерации кадра по текстовому промпту."""
    seed = int(time.time()) % 2_147_483_647
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 20,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, watermark, text, low quality", "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "atlas_comfy", "images": ["8", 0]}},
    }


def generate_via_comfyui(
    api_url: str,
    workflow: Dict[str, Any],
    output_dir: Path,
    timeout_sec: int = 300,
    log_file: Optional[Path] = None,
) -> List[str]:
    """Отправляет JSON-воркфлоу в ComfyUI (/prompt), ждёт завершения и скачивает результаты."""
    output_dir.mkdir(parents=True, exist_ok=True)
    client_id = str(uuid.uuid4())
    downloaded: List[str] = []

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        submit_resp = client.post(
            f"{api_url}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        submit_resp.raise_for_status()
        prompt_id = submit_resp.json()["prompt_id"]
        if log_file:
            write_log(log_file, f"[ComfyUI] Запущен prompt_id={prompt_id}")

        deadline = time.time() + timeout_sec
        history_entry: Optional[Dict[str, Any]] = None
        while time.time() < deadline:
            hist_resp = client.get(f"{api_url}/history/{prompt_id}")
            if hist_resp.status_code == 200:
                hist_json = hist_resp.json()
                if prompt_id in hist_json:
                    history_entry = hist_json[prompt_id]
                    break
            time.sleep(2.0)

        if history_entry is None:
            raise TimeoutError(f"Таймаут ожидания генерации ComfyUI ({timeout_sec}s) для prompt_id={prompt_id}")

        outputs = history_entry.get("outputs", {})
        for _node_id, node_out in outputs.items():
            for media_key in ("images", "videos", "gifs"):
                for item in node_out.get(media_key, []):
                    fname = item.get("filename")
                    if not fname:
                        continue
                    params = {
                        "filename": fname,
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    }
                    file_resp = client.get(f"{api_url}/view", params=params)
                    file_resp.raise_for_status()
                    dest = output_dir / fname
                    dest.write_bytes(file_resp.content)
                    downloaded.append(str(dest.resolve()))
                    if log_file:
                        write_log(log_file, f"[ComfyUI] Скачан файл: {dest}")

    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description="ATLAS Skill: Внешний ComfyUI клиент (RunPod)")
    parser.add_argument("--action", choices=["ping", "generate"], default="ping", help="Действие: ping или generate")
    parser.add_argument("--url", default="", help="Переопределить COMFYUI_API_URL")
    parser.add_argument("--workflow", default="", help="Путь к JSON-файлу воркфлоу ComfyUI")
    parser.add_argument("--prompt", default="", help="Текстовый промпт (если не передан --workflow)")
    parser.add_argument("--output-dir", default="./artifacts/comfyui", help="Папка сохранения результатов")
    parser.add_argument("--timeout", type=int, default=300, help="Таймаут генерации (сек)")
    parser.add_argument("--schema", action="store_true", help="Вывести JSON-схему контракта и выйти")
    parser.add_argument("--verbose", action="store_true", help="Подробный вывод в stderr")
    args = parser.parse_args()

    if args.schema:
        print(SCHEMA_PATH.read_text(encoding="utf-8"))
        return

    log_file = create_log_file("comfyui_client")
    api_url = get_comfyui_url(args.url)
    ping_res = ping_comfyui(api_url)
    write_log(log_file, f"[ping] {json.dumps(ping_res, ensure_ascii=False)}")

    if ping_res["status"] != "online":
        rep = make_report(
            status="partial",
            summary="Сервер ComfyUI офлайн; активирован fallback на локальные ассеты.",
            errors=[],
            warnings_count=1,
            artifacts={
                "full_log": str(log_file),
                "comfyui_status": {"status": "offline", "fallback": "local_assets"},
                "reason": ping_res.get("reason", ""),
            },
            next_action="Использовать локальные фоны/ассеты с эффектом Ken Burns в youtube_studio.py.",
        )
        output_report(rep, verbose=args.verbose)
        return

    if args.action == "ping":
        rep = make_report(
            status="success",
            summary=f"Сервер ComfyUI онлайн: {api_url}",
            errors=[],
            warnings_count=0,
            artifacts={
                "full_log": str(log_file),
                "comfyui_status": ping_res,
            },
            next_action="Можно отправлять воркфлоу генерации через --action generate.",
        )
        output_report(rep, verbose=args.verbose)
        return

    # action == "generate"
    try:
        if args.workflow:
            wf_path = Path(args.workflow)
            if not wf_path.exists():
                raise FileNotFoundError(f"Файл воркфлоу не найден: {wf_path}")
            workflow = json.loads(wf_path.read_text(encoding="utf-8"))
        elif args.prompt.strip():
            workflow = _build_default_txt2img_workflow(args.prompt.strip())
        else:
            raise ValueError("Для --action generate требуется --workflow <file.json> или --prompt <text>")

        out_dir = Path(args.output_dir).resolve()
        files = generate_via_comfyui(api_url, workflow, out_dir, timeout_sec=args.timeout, log_file=log_file)
        rep = make_report(
            status="success" if files else "partial",
            summary=f"ComfyUI сгенерировал {len(files)} файл(ов).",
            errors=[],
            warnings_count=0 if files else 1,
            artifacts={
                "full_log": str(log_file),
                "output_dir": str(out_dir),
                "generated_files": files,
                "comfyui_status": {"status": "online", "url": api_url},
            },
            next_action="Передать output_dir в youtube_studio.py для монтажа видео.",
        )
        output_report(rep, verbose=args.verbose)

    except Exception as ex:
        write_log(log_file, f"ERROR: {ex}")
        rep = make_report(
            status="failed",
            summary=f"Ошибка генерации ComfyUI: {ex}",
            errors=[format_error(str(ex), severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить JSON воркфлоу или использовать локальные ассеты (fallback).",
        )
        output_report(rep, verbose=args.verbose)


if __name__ == "__main__":
    main()
