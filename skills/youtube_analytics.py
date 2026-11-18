#!/usr/bin/env python3
# =============================================================================
# ATLAS — skills/youtube_analytics.py
# Навык аналитики YouTube Data API v3 (trending_niche и channel_audit).
# Возвращает строго валидный JSON по контракту skills/_schema.json.
# =============================================================================
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_utils import SCHEMA_PATH, create_log_file, format_error, get_logs_dir, make_report, output_report, write_log

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def _get_api_key() -> str:
    return os.environ.get("YOUTUBE_API_KEY", "").strip()


def _trending_niche(
    client: httpx.Client,
    api_key: str,
    query: str,
    days: int,
    max_results: int,
    log_file: Path,
) -> Dict[str, Any]:
    days = max(1, min(30, days))
    published_after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_log(log_file, f"[trending_niche] query='{query}', days={days}, publishedAfter={published_after}")

    search_resp = client.get(
        f"{YOUTUBE_API_BASE}/search",
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "viewCount",
            "publishedAfter": published_after,
            "maxResults": min(50, max(max_results * 2, 20)),
            "key": api_key,
        },
    )
    search_resp.raise_for_status()
    search_items = search_resp.json().get("items", [])
    if not search_items:
        return {"topics": [], "count": 0}

    video_ids = [it["id"]["videoId"] for it in search_items if it.get("id", {}).get("videoId")]
    videos_resp = client.get(
        f"{YOUTUBE_API_BASE}/videos",
        params={
            "part": "snippet,statistics",
            "id": ",".join(video_ids),
            "key": api_key,
        },
    )
    videos_resp.raise_for_status()
    videos = videos_resp.json().get("items", [])

    channel_ids = list({v["snippet"]["channelId"] for v in videos if v.get("snippet", {}).get("channelId")})
    channels_map: Dict[str, Dict[str, Any]] = {}
    if channel_ids:
        ch_resp = client.get(
            f"{YOUTUBE_API_BASE}/channels",
            params={
                "part": "snippet,statistics",
                "id": ",".join(channel_ids[:50]),
                "key": api_key,
            },
        )
        ch_resp.raise_for_status()
        for ch in ch_resp.json().get("items", []):
            channels_map[ch["id"]] = ch

    scored: List[Dict[str, Any]] = []
    for v in videos:
        vid = v.get("id", "")
        snip = v.get("snippet", {})
        stats = v.get("statistics", {})
        ch_id = snip.get("channelId", "")
        ch_info = channels_map.get(ch_id, {})
        ch_stats = ch_info.get("statistics", {})

        views = int(stats.get("viewCount", 0) or 0)
        likes = int(stats.get("likeCount", 0) or 0)
        comments = int(stats.get("commentCount", 0) or 0)
        subs = int(ch_stats.get("subscriberCount", 0) or 0)
        virality_ratio = round(views / max(subs, 1), 2)

        scored.append({
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": snip.get("title", ""),
            "channel_title": snip.get("channelTitle", ""),
            "channel_id": ch_id,
            "published_at": snip.get("publishedAt", ""),
            "tags": snip.get("tags", [])[:15],
            "views": views,
            "likes": likes,
            "comments": comments,
            "subscribers": subs,
            "virality_ratio": virality_ratio,
        })

    scored.sort(key=lambda x: (x["virality_ratio"], x["views"]), reverse=True)
    top_topics = scored[:max_results]
    return {"query": query, "days": days, "count": len(top_topics), "topics": top_topics}


def _resolve_channel_id(client: httpx.Client, api_key: str, channel_ref: str) -> Optional[str]:
    ref = channel_ref.strip()
    if ref.startswith("UC") and len(ref) >= 20:
        return ref
    if ref.startswith("@"):
        resp = client.get(
            f"{YOUTUBE_API_BASE}/channels",
            params={"part": "id", "forHandle": ref, "key": api_key},
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if items:
            return items[0]["id"]
    search_resp = client.get(
        f"{YOUTUBE_API_BASE}/search",
        params={"part": "snippet", "q": ref, "type": "channel", "maxResults": 1, "key": api_key},
    )
    search_resp.raise_for_status()
    items = search_resp.json().get("items", [])
    if items:
        return items[0]["id"]["channelId"]
    return None


def _channel_audit(
    client: httpx.Client,
    api_key: str,
    channel_ref: str,
    max_results: int,
    log_file: Path,
) -> Dict[str, Any]:
    channel_id = _resolve_channel_id(client, api_key, channel_ref)
    if not channel_id:
        raise ValueError(f"Канал '{channel_ref}' не найден в YouTube API.")

    write_log(log_file, f"[channel_audit] resolved channel_id={channel_id}")
    ch_resp = client.get(
        f"{YOUTUBE_API_BASE}/channels",
        params={"part": "snippet,statistics,contentDetails", "id": channel_id, "key": api_key},
    )
    ch_resp.raise_for_status()
    ch_items = ch_resp.json().get("items", [])
    if not ch_items:
        raise ValueError(f"Статистика канала {channel_id} недоступна.")

    ch = ch_items[0]
    ch_snip = ch.get("snippet", {})
    ch_stats = ch.get("statistics", {})

    # Лучшие видео канала по просмотрам
    top_search = client.get(
        f"{YOUTUBE_API_BASE}/search",
        params={
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "viewCount",
            "maxResults": min(25, max_results),
            "key": api_key,
        },
    )
    top_search.raise_for_status()
    top_ids = [it["id"]["videoId"] for it in top_search.json().get("items", []) if it.get("id", {}).get("videoId")]

    top_videos: List[Dict[str, Any]] = []
    if top_ids:
        v_resp = client.get(
            f"{YOUTUBE_API_BASE}/videos",
            params={"part": "snippet,statistics", "id": ",".join(top_ids), "key": api_key},
        )
        v_resp.raise_for_status()
        for v in v_resp.json().get("items", []):
            st = v.get("statistics", {})
            top_videos.append({
                "video_id": v.get("id", ""),
                "title": v.get("snippet", {}).get("title", ""),
                "published_at": v.get("snippet", {}).get("publishedAt", ""),
                "views": int(st.get("viewCount", 0) or 0),
                "likes": int(st.get("likeCount", 0) or 0),
                "comments": int(st.get("commentCount", 0) or 0),
            })

    total_views = int(ch_stats.get("viewCount", 0) or 0)
    total_videos = int(ch_stats.get("videoCount", 0) or 0)
    avg_views = round(total_views / max(total_videos, 1), 1)

    return {
        "channel_id": channel_id,
        "title": ch_snip.get("title", ""),
        "subscribers": int(ch_stats.get("subscriberCount", 0) or 0),
        "total_views": total_views,
        "video_count": total_videos,
        "avg_views_per_video": avg_views,
        "top_videos": top_videos,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ATLAS Skill: YouTube Data API v3 Analytics")
    parser.add_argument("--action", choices=["trending_niche", "channel_audit"], help="Режим аналитики")
    parser.add_argument("--query", default="", help="Ключевое слово / ниша (для trending_niche)")
    parser.add_argument("--days", type=int, default=14, help="Глубина поиска в днях (7-30)")
    parser.add_argument("--channel-id", default="", help="ID канала, @handle или название (для channel_audit)")
    parser.add_argument("--max-results", type=int, default=10, help="Максимум результатов (по умолчанию 10)")
    parser.add_argument("--output", default="", help="Путь для сохранения JSON-отчёта аналитики")
    parser.add_argument("--schema", action="store_true", help="Вывести JSON-схему контракта и выйти")
    parser.add_argument("--verbose", action="store_true", help="Подробный вывод в stderr")
    args = parser.parse_args()

    if args.schema:
        print(SCHEMA_PATH.read_text(encoding="utf-8"))
        return

    if not args.action:
        parser.error("Требуется --action (trending_niche или channel_audit) или --schema")

    log_file = create_log_file("youtube_analytics")
    api_key = _get_api_key()
    if not api_key:
        rep = make_report(
            status="failed",
            summary="YOUTUBE_API_KEY не задан в .env.",
            errors=[format_error("Отсутствует переменная окружения YOUTUBE_API_KEY", severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Добавить YOUTUBE_API_KEY в .env и повторить запуск.",
        )
        output_report(rep, verbose=args.verbose)
        return

    try:
        with httpx.Client(timeout=20.0) as client:
            if args.action == "trending_niche":
                if not args.query.strip():
                    raise ValueError("Для режима trending_niche требуется параметр --query")
                data = _trending_niche(client, api_key, args.query.strip(), args.days, args.max_results, log_file)
                summary = f"Найдено {data['count']} трендовых роликов по нише '{args.query}' за {data['days']} дн."
            else:
                if not args.channel_id.strip():
                    raise ValueError("Для режима channel_audit требуется параметр --channel-id")
                data = _channel_audit(client, api_key, args.channel_id.strip(), args.max_results, log_file)
                summary = (
                    f"Аудит канала '{data['title']}': {data['subscribers']:,} подп., "
                    f"{data['total_views']:,} просм., ср. {data['avg_views_per_video']}/видео."
                )

        out_path = Path(args.output) if args.output else (get_logs_dir() / f"youtube_{args.action}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        write_log(log_file, json.dumps(data, ensure_ascii=False, indent=2))

        rep = make_report(
            status="success",
            summary=summary,
            errors=[],
            warnings_count=0,
            artifacts={
                "full_log": str(log_file),
                "analytics_report": str(out_path.resolve()),
                "data": data,
            },
            next_action="Использовать отобранные темы и теги для генерации сценария в youtube_studio.py.",
        )
        output_report(rep, verbose=args.verbose)

    except httpx.HTTPStatusError as http_err:
        msg = f"YouTube API HTTP {http_err.response.status_code}: {http_err.response.text[:300]}"
        write_log(log_file, msg)
        rep = make_report(
            status="failed",
            summary="Ошибка запроса к YouTube Data API v3.",
            errors=[format_error(msg, severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить валидность YOUTUBE_API_KEY и квоту YouTube Data API.",
        )
        output_report(rep, verbose=args.verbose)
    except Exception as ex:
        write_log(log_file, f"ERROR: {ex}")
        rep = make_report(
            status="failed",
            summary=f"Ошибка выполнения youtube_analytics: {ex}",
            errors=[format_error(str(ex), severity="fatal")],
            warnings_count=0,
            artifacts={"full_log": str(log_file)},
            next_action="Проверить аргументы запуска и сетевое соединение.",
        )
        output_report(rep, verbose=args.verbose)


if __name__ == "__main__":
    main()
