#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_bbq_news.py
professionalbarbecuer.com — 세계 바비큐 뉴스 실시간 수집기
"""

import json
import hashlib
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
from googlenewsdecoder import gnewsdecoder

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "feeds_config.json"
NEWS_PATH = BASE_DIR / "news.json"
CACHE_PATH = BASE_DIR / "resolve_cache.json"

MAX_LIVE_ITEMS = 120
LIVE_RETENTION_HOURS = 168  # 7일
CACHE_RETENTION_DAYS = 30

# feeds_config.json에 적힌 max_items에 이 배율을 곱해서 실제로 가져온다.
# 이 숫자 하나만 바꾸면 전체 검색어의 수집량이 한꺼번에 조절된다.
MAX_ITEMS_MULTIPLIER = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 10
RESOLVE_TIMEOUT = 8
VALIDATE_TIMEOUT = 6

DEFINITELY_DEAD = {404, 410, 451}

CORE_BBQ_TERMS = [
    "바비큐", "바베큐",
    "barbecue", "bbq", "barbeque",
    "asado", "barbacoa",
    "churrasco", "braai",
    "grillweltmeisterschaft",
    "バーベキュー",
    "烧烤",
    "باربكيو",
    "บาร์บีคิว",
    "iobsf", "kooba", "kbri", "kcbs",
    "korea barbecue university",
    "aobe",
    "户外厨房",
]


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
    return default


def save_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def make_id(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def raw_key(raw_url):
    return hashlib.sha1(raw_url.encode("utf-8")).hexdigest()[:16]


def strip_html(text):
    """요약 필드에 섞인 HTML 태그를 제거한다."""
    return re.sub(r"<[^>]+>", " ", text or "")


def is_relevant(title, summary=""):
    """제목이나 요약 중 하나라도 핵심 단어를 포함하면 통과시킨다."""
    haystack = (title + " " + strip_html(summary)).lower()
    return any(term.lower() in haystack for term in CORE_BBQ_TERMS)


def fetch_feed(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        print(f"  → HTTP {resp.status_code}, {len(resp.content)} bytes")
        if resp.status_code != 200:
            return feedparser.parse(b"")
        return feedparser.parse(resp.content)
    except Exception as e:
        print(f"  → 요청 실패: {e}")
        return feedparser.parse(b"")


def resolve_final_url(url):
    if "news.google.com" not in url:
        return url
    try:
        result = gnewsdecoder(url, interval=1)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
        return url
    except Exception as e:
        print(f"    (링크 해석 실패, 원본 유지: {e})")
        return url


def validate_url(url):
    try:
        resp = requests.head(
            url, headers=HEADERS, timeout=VALIDATE_TIMEOUT, allow_redirects=True
        )
        if resp.status_code in DEFINITELY_DEAD:
            return False
        if resp.status_code < 400:
            return True
        resp = requests.get(
            url, headers=HEADERS, timeout=VALIDATE_TIMEOUT, allow_redirects=True, stream=True
        )
        return resp.status_code not in DEFINITELY_DEAD
    except Exception:
        return True


def resolve_and_validate(raw_url, cache):
    key = raw_key(raw_url)
    cached = cache.get(key)
    if cached:
        return cached.get("url"), cached.get("alive", True)

    url = resolve_final_url(raw_url)
    alive = validate_url(url)
    cache[key] = {
        "url": url,
        "alive": alive,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return url, alive


def parse_entry(entry, query_label, cache):
    raw_url = entry.get("link", "")
    if not raw_url:
        return None

    source_title = ""
    src = entry.get("source")
    if isinstance(src, dict):
        source_title = src.get("title", "")
    if not source_title:
        parts = entry.get("title", "").rsplit(" - ", 1)
        source_title = parts[-1] if len(parts) > 1 else query_label

    headline = entry.get("title", "").rsplit(" - ", 1)[0].strip()
    summary = entry.get("summary", "")

    if not is_relevant(headline, summary):
        return None

    url, alive = resolve_and_validate(raw_url, cache)
    if not alive:
        return None

    published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if published_struct:
        published_at = datetime(*published_struct[:6], tzinfo=timezone.utc)
    else:
        published_at = datetime.now(timezone.utc)

    return {
        "id": make_id(url),
        "source": source_title,
        "title": headline,
        "url": url,
        "query": query_label,
        "published_at": published_at.isoformat(),
        "time": published_at.strftime("%H:%M"),
        "date": published_at.strftime("%Y-%m-%d"),
    }


def fetch_all(config, cache):
    collected = []
    for feed in config.get("queries", []):
        query = feed["query"]
        label = feed.get("label", query)
        rss_url = (
            "https://news.google.com/rss/search?q="
            + query.replace(" ", "+")
            + "&hl=" + feed.get("hl", "ko")
            + "&gl=" + feed.get("gl", "KR")
            + "&ceid=" + feed.get("ceid", "KR:ko")
        )
        print(f"[검색어: {label}]")
        parsed = fetch_feed(rss_url)
        limit = feed.get("max_items", 8) * MAX_ITEMS_MULTIPLIER
        found, rejected = 0, 0
        for entry in parsed.entries[:limit]:
            item = parse_entry(entry, label, cache)
            if item:
                collected.append(item)
                found += 1
            else:
                rejected += 1
        print(f"  → {found}건 게시 / {rejected}건 제외 (조회 상한 {limit}건)")

    for feed in config.get("official_feeds", []):
        if not feed.get("url"):
            continue
        print(f"[공식 피드: {feed.get('label')}]")
        parsed = fetch_feed(feed["url"])
        limit = feed.get("max_items", 10) * MAX_ITEMS_MULTIPLIER
        for entry in parsed.entries[:limit]:
            item = parse_entry(entry, feed.get("label", "OFFICIAL"), cache)
            if item:
                item["source"] = feed.get("label", item["source"])
                collected.append(item)

    return collected


def prune_expired(items, hours):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    kept = []
    for item in items:
        try:
            ts = datetime.fromisoformat(item["published_at"])
        except Exception:
            kept.append(item)
            continue
        if ts >= cutoff:
            kept.append(item)
    return kept


def prune_cache(cache, days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept = {}
    for key, entry in cache.items():
        try:
            ts = datetime.fromisoformat(entry.get("checked_at", ""))
        except Exception:
            continue
        if ts >= cutoff:
            kept[key] = entry
    return kept


def merge(existing, new_items, seen_ids, max_len):
    for item in new_items:
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        existing.append(item)
    existing.sort(key=lambda x: x["published_at"], reverse=True)
    return existing[:max_len]


def main():
    config = load_json(CONFIG_PATH, {"queries": [], "official_feeds": []})
    print(f"등록된 검색어 수: {len(config.get('queries', []))}")

    live = load_json(NEWS_PATH, [])
    live = prune_expired(live, LIVE_RETENTION_HOURS)

    cache = load_json(CACHE_PATH, {})
    cache = prune_cache(cache, CACHE_RETENTION_DAYS)
    print(f"캐시된 링크 수: {len(cache)}")

    seen_ids = {item["id"] for item in live}

    collected = fetch_all(config, cache)
    live = merge(live, collected, seen_ids, MAX_LIVE_ITEMS)

    save_json(NEWS_PATH, live)
    save_json(CACHE_PATH, cache)

    print(
        f"[{datetime.now(timezone.utc).isoformat()}] "
        f"{len(collected)}건 게시 (현재 live={len(live)}, 캐시={len(cache)})"
    )


if __name__ == "__main__":
    main()
