#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_bbq_news.py
professionalbarbecuer.com — 세계 바비큐 뉴스 실시간 수집기

동작 방식
  1. feeds_config.json에 등록된 여러 검색 쿼리로 구글 뉴스 RSS를 훑는다.
  2. 찾아온 기사 중, 제목에 실제 바비큐 핵심 단어(또는 관련 단체명)가
     있는 것만 통과시킨다.
  3. 구글 뉴스 RSS의 링크는 구글이 감싼 중계 주소라 googlenewsdecoder로
     실제 도착지 주소를 풀어낸다.
  4. 풀어낸 실제 주소가 "확실히 죽은 링크"(404, 410, 451)인지만
     확인한다. 봇 차단(403 등)이나 응답 지연은 실제로는 살아있는
     기사일 가능성이 높아 게시 목록에서 빼지 않는다.
  5. 통과한 기사는 전부 news.json에 바로 게시한다.
  6. 이미 실려 있는 기사는 URL 해시로 중복 제거한다.
  7. 게시 후 72시간이 지난 항목은 자동으로 걷어낸다.
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

# "페이지가 실제로 없다"는 확실한 신호로만 취급하는 상태 코드.
# 403, 999, 429 같은 코드는 자동화 요청을 막는 봇 차단일 뿐,
# 실제로는 살아있는 기사인 경우가 많아 게시 목록에서 빼지 않는다.
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
    """구글 뉴스가 감싼 중계 주소를 실제 기사 주소로 풀어낸다.
    실패하면 원래 주소를 그대로 돌려준다."""
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
    """실제 주소가 완전히 죽은 링크인지만 확인한다.
    확실히 죽은 경우(404 등)만 걸러내고, 그 외(봇 차단 포함)는 살려둔다."""
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
        # 요청 자체가 실패한 경우(시간 초과 등)는 판단 보류, 살려둔다.
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
