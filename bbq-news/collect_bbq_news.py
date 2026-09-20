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

MAX_LIVE_ITEMS = 80
LIVE_RETENTION_HOURS = 72

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


def is_relevant(title):
    lowered = title.lower()
    return any(term.lower() in lowered for term in CORE_BBQ_TERMS)


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


def parse_entry(entry, query_label):
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

    if not is_relevant(headline):
        return None

    url = resolve_final_url(raw_url)

    if not validate_url(url):
        print(f"    (확실히 죽은 링크, 게시 제외: {headline[:30]}...)")
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


def fetch_all(config):
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
        found, rejected = 0, 0
        for entry in parsed.entries[: feed.get("max_items", 8)]:
            item = parse_entry(entry, label)
            if item:
                collected.append(item)
                found += 1
            else:
                rejected += 1
        print(f"  → {found}건 게시 / {rejected}건 제외")

    for feed in config.get("official_feeds", []):
        if not feed.get("url"):
            continue
        print(f"[공식 피드: {feed.get('label')}]")
        parsed = fetch_feed(feed["url"])
        for entry in parsed.entries[: feed.get("max_items", 10)]:
            item = parse_entry(entry, feed.get("label", "OFFICIAL"))
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

    seen_ids = {item["id"] for item in live}

    collected = fetch_all(config)
    live = merge(live, collected, seen_ids, MAX_LIVE_ITEMS)

    save_json(NEWS_PATH, live)

    print(
        f"[{datetime.now(timezone.utc).isoformat()}] "
        f"{len(collected)}건 게시 (현재 live={len(live)})"
    )


if __name__ == "__main__":
    main()
