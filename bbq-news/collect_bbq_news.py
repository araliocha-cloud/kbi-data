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

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "feeds_config.json"
NEWS_PATH = BASE_DIR / "news.json"
QUEUE_PATH = BASE_DIR / "news_queue.json"

MAX_LIVE_ITEMS = 40
MAX_QUEUE_ITEMS = 100
LIVE_RETENTION_HOURS = 72
QUEUE_RETENTION_HOURS = 240

OFFICIAL_DOMAINS = {
    "kcbs.us",
    "memphisinmay.org",
    "americanroyal.com",
    "jackdanielsbbq.com",
    "worldbbqassociation.com",
    "grillstock.co.uk",
    "professionalbarbecuer.com",
}

# 구글 뉴스가 자동화된 요청을 걸러내지 않도록, 일반 브라우저처럼 신원을 밝힌다.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 10


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


def extract_domain(url):
    try:
        netloc = urlparse(url).netloc.lower()
        return re.sub(r"^www\.", "", netloc)
    except Exception:
        return ""


def fetch_feed(url):
    """requests로 먼저 받아온 뒤 feedparser로 해석한다.
    실패해도 예외를 던지지 않고 빈 결과를 돌려준다."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        print(f"  → HTTP {resp.status_code}, {len(resp.content)} bytes")
        if resp.status_code != 200:
            return feedparser.parse(b"")
        return feedparser.parse(resp.content)
    except Exception as e:
        print(f"  → 요청 실패: {e}")
        return feedparser.parse(b"")


def parse_entry(entry, query_label):
    url = entry.get("link", "")
    if not url:
        return None

    source_title = ""
    src = entry.get("source")
    if isinstance(src, dict):
        source_title = src.get("title", "")
    if not source_title:
        parts = entry.get("title", "").rsplit(" - ", 1)
        source_title = parts[-1] if len(parts) > 1 else query_label

    headline = entry.get("title", "").rsplit(" - ", 1)[0]

    published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if published_struct:
        published_at = datetime(*published_struct[:6], tzinfo=timezone.utc)
    else:
        published_at = datetime.now(timezone.utc)

    source_href = ""
    if isinstance(src, dict):
        source_href = src.get("href", "")
    domain = extract_domain(source_href) or extract_domain(url)
    tier = "official" if domain in OFFICIAL_DOMAINS else "general"

    return {
        "id": make_id(url),
        "source": source_title,
        "tier": tier,
        "title": headline.strip(),
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
        found = 0
        for entry in parsed.entries[: feed.get("max_items", 8)]:
            item = parse_entry(entry, label)
            if item:
                collected.append(item)
                found += 1
        print(f"  → {found}건 발견")

    for feed in config.get("official_feeds", []):
        if not feed.get("url"):
            continue
        print(f"[공식 피드: {feed.get('label')}]")
        parsed = fetch_feed(feed["url"])
        for entry in parsed.entries[: feed.get("max_items", 10)]:
            item = parse_entry(entry, feed.get("label", "OFFICIAL"))
            if item:
                item["tier"] = "official"
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
    queue = load_json(QUEUE_PATH, [])

    live = prune_expired(live, LIVE_RETENTION_HOURS)
    queue = prune_expired(queue, QUEUE_RETENTION_HOURS)

    seen_ids = {item["id"] for item in live} | {item["id"] for item in queue}

    collected = fetch_all(config)
    official_new = [i for i in collected if i["tier"] == "official"]
    general_new = [i for i in collected if i["tier"] == "general"]

    live = merge(live, official_new, seen_ids, MAX_LIVE_ITEMS)
    queue = merge(queue, general_new, seen_ids, MAX_QUEUE_ITEMS)

    save_json(NEWS_PATH, live)
    save_json(QUEUE_PATH, queue)

    print(
        f"[{datetime.now(timezone.utc).isoformat()}] "
        f"공식 {len(official_new)}건 게시 / 일반 {len(general_new)}건 대기열 적재 "
        f"(현재 live={len(live)}, queue={len(queue)})"
    )


if __name__ == "__main__":
    main()
