#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_bbq_news.py
professionalbarbecuer.com — 세계 바비큐 뉴스 실시간 수집기

동작 방식
  1. feeds_config.json에 등록된 여러 검색 쿼리로 구글 뉴스 RSS를 훑는다.
  2. 제목이나 요약에 실제 바비큐 핵심 단어(또는 관련 단체명)가
     있는 것만 통과시킨다.
  3. 구글 뉴스 링크는 실제 도착지 주소로 풀어낸다(googlenewsdecoder).
     못 풀리면 구글 링크 그대로 게시한다. 누르면 원문으로 넘어간다.
     실패는 캐시에 남기지 않아 다음 실행 때 다시 풀어본다.
  4. 확실히 죽은 링크(404, 410, 451)만 걸러내고, 봇 차단(403 등)이나
     응답 지연은 실제로는 살아있는 기사일 가능성이 높아 살려둔다.
  5. 한 번 확인한 기사는 resolve_cache.json에 결과를 저장해두고,
     다음 실행부터는 그 결과를 재사용해 반복 확인을 건너뛴다.
  6. 같은 사건을 여러 매체가 다룬 경우 한 줄만 남기고 news.json에 게시한다.
  7. 발행 후 48시간 안의 기사만 게시한다. 그런 기사가 20건이 안 되면
     7일 안의 최신 기사로 채운다. 7일이 지난 기사는 게시하지 않는다.
  8. 캐시는 30일 넘은 항목을 자동으로 정리한다.
"""

import json
import hashlib
import re
import unicodedata
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
LIVE_RETENTION_HOURS = 48  # 이틀 — 최신 소식 위주로 유지
# 48시간 안의 기사가 이 수보다 적으면, 7일 안의 최신 기사로 모자란 만큼 채운다.
MIN_LIVE_ITEMS = 20
POOL_RETENTION_DAYS = 7    # 이보다 오래된 기사는 어떤 경우에도 게시하지 않는다
CACHE_RETENTION_DAYS = 14  # 죽은 사이트 판정도 2주 지나면 다시 확인해본다

# feeds_config.json에 적힌 max_items에 이 배율을 곱해서 실제로 가져온다.
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

# 한 번 실행에 새로 해석할 구글 링크 수와, 연속 실패 허용 횟수.
MAX_NEW_RESOLVES_PER_RUN = 40
MAX_CONSECUTIVE_FAILS = 5

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


# 한국어 기사에서 치킨 프랜차이즈 'BBQ' 소식을 걸러내기 위한 단어들.
KO_EXCLUDE_TERMS = [
    "bbq치킨", "bbq 치킨", "제너시스", "비비큐", "황금올리브",
]
# 한국어 기사는 영문 'BBQ'만으로는 통과시키지 않는다.
# 아래 단어 중 하나가 있어야 진짜 바비큐 기사로 본다.
KO_REQUIRED_TERMS = [
    "바비큐", "바베큐",
    "iobsf", "kooba", "kbri", "kcbs",
    "korea barbecue university", "aobe",
]
HANGUL = re.compile(r"[가-힣]")

# 스포츠바비큐 소식으로서 격에 맞지 않는 기사(범죄, 사건사고, 추문)를 거른다.
# 한국어, 일본어, 중국어는 글자가 들어 있으면 뺀다.
UNFIT_TERMS_CJK = [
    "마약", "출소", "복역", "구속", "체포", "기소", "징역", "실형", "집행유예",
    "폭행", "성범죄", "성추행", "음주운전", "살인", "사망", "숨져", "사기", "횡령",
    "逮捕", "容疑", "死亡", "麻薬", "被告",
    "吸毒", "判刑",
]
# 라틴 문자 언어는 단어 단위로 찾는다.
UNFIT_PATTERN = re.compile(
    r"\b("
    r"arrest(ed|s)?|charged with|convicted|sentenced|indicted|lawsuit|sued|"
    r"murder(ed)?|homicide|shooting|stabbing|kill(s|ed)?|dies|died|fatal|overdose|"
    r"detenid[oa]s?|asesinad[oa]s?|asesinato|homicidio|muert[oa]s?|"
    r"prisão|assassinad[oa]s?|assassinato|mort[oa]s?|"
    r"festgenommen|mord"
    r")\b",
    re.IGNORECASE,
)


# 대회, 축제, 단체 소식만 게시한다. 식당 개업, 친목 모임, 개인 블로그 같은
# 가벼운 소식은 아래 단어가 하나도 없으면 뺀다.
EVENT_TERMS_CJK = [
    "대회", "챔피언십", "선수권", "페스티벌", "축제", "경연", "월드컵",
    "스포츠바비큐", "프로바비큐어", "협회", "연맹",
    "選手権", "コンテスト", "グランプリ", "フェスティバル",
    "大赛", "比赛", "锦标赛", "烧烤节",
    "مسابقة", "مهرجان", "بطولة",
    "การแข่งขัน", "เทศกาล",
]
EVENT_PATTERN = re.compile(
    r"\b("
    r"competitions?|contests?|championships?|champions?|cook-?offs?|"
    r"festivals?|fest|tournaments?|world cup|pitmasters?|judges?|bash|"
    r"world records?|guinness|"
    r"campeonatos?|concursos?|torneos?|torneios?|mundial|competencias?|"
    r"parrilleros?|asadores?|churrasqueiros?|"
    r"titles?|títulos?|campeão|campeões|campeã|campeón|campeones|"
    r"meisterschaft|wettbewerb|kampioenschap|wedstrijd|"
    r"championnat|concours|campionato|gara|"
    r"iobsf|kooba|kbri|kcbs|wbqa|ibca|nbbqa|aobe|american royal|memphis in may"
    r")\b",
    re.IGNORECASE,
)


def is_event(text):
    lowered = (text or "").lower()
    if any(term in lowered for term in EVENT_TERMS_CJK):
        return True
    return bool(EVENT_PATTERN.search(lowered))


def is_unfit(text):
    lowered = (text or "").lower()
    if any(term in lowered for term in UNFIT_TERMS_CJK):
        return True
    return bool(UNFIT_PATTERN.search(lowered))


def is_relevant(title, summary=""):
    """제목이나 요약 중 하나라도 핵심 단어를 포함하면 통과시킨다.
    범죄, 사건사고, 추문처럼 격에 맞지 않는 기사는 뺀다.
    대회, 축제, 단체와 관련 없는 가벼운 소식도 뺀다.
    한국어 기사는 치킨 프랜차이즈 BBQ를 가리키는 단어가 있으면 빼고,
    영문 'BBQ'만 있고 '바비큐'가 없으면 브랜드 기사로 보고 뺀다."""
    haystack = (title + " " + strip_html(summary)).lower()
    if not any(term.lower() in haystack for term in CORE_BBQ_TERMS):
        return False
    if is_unfit(haystack):
        return False
    if not is_event(haystack):
        return False
    if HANGUL.search(haystack):
        if any(term in haystack for term in KO_EXCLUDE_TERMS):
            return False
        if not any(term in haystack for term in KO_REQUIRED_TERMS):
            return False
    return True


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
    except requests.exceptions.ConnectionError:
        # 도메인이 없어졌거나 서버가 완전히 응답하지 않는 경우.
        # 사이트 자체가 운영되지 않는다고 보고 죽은 것으로 처리한다.
        return False
    except Exception:
        # 시간 초과 등 일시적인 문제는 판단을 보류하고 살려둔다.
        return True


def resolve_and_validate(raw_url, cache, budget):
    """캐시에 있으면 재사용하고, 없으면 새로 확인해서 캐시에 저장한다.

    실제 주소 해석에 실패해도 기사를 버리지 않는다. 구글 뉴스 링크는
    브라우저에서 누르면 원문으로 넘어가므로, 그 링크를 그대로 게시한다.
    해석 실패는 캐시에 남기지 않아서 다음 실행 때 다시 시도하게 한다.
    한 번 실행에 새로 해석하는 개수는 budget으로 제한해 구글의 속도
    제한에 걸리지 않게 한다."""
    key = raw_key(raw_url)
    cached = cache.get(key)
    if cached:
        return cached.get("url"), cached.get("alive", True)

    if budget["left"] <= 0:
        return raw_url, True
    budget["left"] -= 1

    url = resolve_final_url(raw_url)

    if "news.google.com" in url:
        budget["fails"] += 1
        # 연속 실패가 쌓이면 속도 제한으로 보고 이번 실행의 해석을 멈춘다.
        if budget["fails"] >= MAX_CONSECUTIVE_FAILS:
            print("    (구글 링크 해석이 연속 실패 — 이번 실행은 원본 링크로 게시)")
            budget["left"] = 0
        return raw_url, True
    budget["fails"] = 0

    alive = validate_url(url)
    cache[key] = {
        "url": url,
        "alive": alive,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return url, alive


def parse_entry(entry, query_label, cache, budget):
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

    url, alive = resolve_and_validate(raw_url, cache, budget)
    if not alive:
        return None

    published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if published_struct:
        published_at = datetime(*published_struct[:6], tzinfo=timezone.utc)
    else:
        published_at = datetime.now(timezone.utc)

    return {
        "id": make_id(raw_url),
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
    budget = {"left": MAX_NEW_RESOLVES_PER_RUN, "fails": 0}
    for feed in config.get("queries", []):
        query = feed["query"]
        label = feed.get("label", query)
        rss_url = (
            "https://news.google.com/rss/search?q="
            + (query + f" when:{POOL_RETENTION_DAYS}d").replace(" ", "+")
            + "&hl=" + feed.get("hl", "ko")
            + "&gl=" + feed.get("gl", "KR")
            + "&ceid=" + feed.get("ceid", "KR:ko")
        )
        print(f"[검색어: {label}]")
        parsed = fetch_feed(rss_url)
        limit = feed.get("max_items", 8) * MAX_ITEMS_MULTIPLIER
        found, rejected = 0, 0
        for entry in parsed.entries[:limit]:
            item = parse_entry(entry, label, cache, budget)
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
            item = parse_entry(entry, feed.get("label", "OFFICIAL"), cache, budget)
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


# 같은 사건을 다룬 기사를 가려내기 위한 설정.
# 어느 기사에나 나오는 단어는 비교에서 뺀다.
TITLE_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "will", "are", "was",
    "has", "its", "into", "new", "first", "annual",
    "del", "los", "las", "para", "por", "con", "una", "que", "como", "ser",
    "sera", "fue", "ano", "anos",
    "dos", "das", "nos", "nas", "pela", "pelo", "com", "sua", "seu",
    "der", "die", "das", "und", "mit", "een", "het", "van", "voor",
    "des", "les", "une", "sur", "aux",
    "bbq", "barbe", "barbq", "grill",
}
CJK_RUN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]+")
LATIN_WORD = re.compile(r"[a-z0-9]+")


def title_tokens(title):
    """제목을 비교용 낱말 묶음으로 바꾼다. 라틴 문자는 악센트를 지우고
    앞 다섯 글자로 줄여 asado, asadores, asador를 한 낱말로 본다.
    한중일 문자는 두 글자씩 끊어 비교한다."""
    text = unicodedata.normalize("NFKD", (title or "").lower())
    text = "".join(ch for ch in text if not ("\u0300" <= ch <= "\u036f"))
    text = unicodedata.normalize("NFC", text)
    tokens = set()
    for run in CJK_RUN.findall(text):
        if len(run) == 1:
            continue
        tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    for word in LATIN_WORD.findall(CJK_RUN.sub(" ", text)):
        if len(word) < 3 or word.isdigit():
            continue
        stem = word[:5]
        if word in TITLE_STOPWORDS or stem in TITLE_STOPWORDS:
            continue
        tokens.add(stem)
    return tokens


def same_story(a, b):
    """두 제목이 같은 사건을 다루는지 판단한다.
    두 제목의 낱말을 합친 것 가운데 60% 이상이 겹치고, 겹친 낱말이
    세 개 이상이면 같은 기사로 본다. 같은 대회의 예고, 현장, 결과처럼
    대회 이름만 같고 내용이 다른 기사는 따로 남는다.
    '#Mundial del asado'처럼 낱말이 두 개 이하인 짧은 제목은 그 낱말이
    전부 다른 제목에 들어 있으면 같은 기사로 본다."""
    if not a or not b:
        return False
    shared = len(a & b)
    if min(len(a), len(b)) <= 2 and shared >= 2 and shared == min(len(a), len(b)):
        return True
    return shared >= 3 and shared / len(a | b) >= 0.6


def dedupe_stories(items):
    """같은 사건의 기사는 한 줄만 남긴다. 겹치는 기사들은 한 묶음으로
    모아, 묶음 안의 어느 기사와든 같으면 같은 사건으로 본다. 묶음마다
    제목이 가장 자세한 기사 하나를 남기고, 최신 기사 먼저 순서를 유지한다."""
    groups = []  # [대표 기사, 대표 낱말 수, 묶음 낱말 목록]
    for item in items:
        tokens = title_tokens(item.get("title", ""))
        for group in groups:
            if any(same_story(tokens, member) for member in group[2]):
                group[2].append(tokens)
                if len(tokens) > group[1]:
                    group[0], group[1] = item, len(tokens)
                break
        else:
            groups.append([item, len(tokens), [tokens]])
    return [group[0] for group in groups]


def select_live(items):
    """48시간 안의 기사를 우선 게시한다. 모자라면 7일 안의 최신 기사로
    MIN_LIVE_ITEMS까지 채운다. 7일이 넘은 기사는 게시하지 않는다."""
    pool = prune_expired(items, POOL_RETENTION_DAYS * 24)
    pool.sort(key=lambda x: x["published_at"], reverse=True)
    pool = dedupe_stories(pool)
    fresh = prune_expired(pool, LIVE_RETENTION_HOURS)
    if len(fresh) >= MIN_LIVE_ITEMS:
        return fresh[:MAX_LIVE_ITEMS]
    return pool[:MIN_LIVE_ITEMS]


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


def normalize_title(title):
    return re.sub(r"\W+", "", (title or "").lower())


def merge(existing, new_items, max_len):
    """id와 제목 두 기준으로 중복을 거른다. 같은 기사가 나중에 실제
    주소로 해석되면 구글 링크를 실제 주소로 바꿔 끼운다."""
    by_id = {item["id"]: item for item in existing}
    titles = {normalize_title(item["title"]) for item in existing}
    for item in new_items:
        old = by_id.get(item["id"])
        if old:
            if "news.google.com" in old["url"] and "news.google.com" not in item["url"]:
                old["url"] = item["url"]
            continue
        t = normalize_title(item["title"])
        if t in titles:
            continue
        by_id[item["id"]] = item
        titles.add(t)
        existing.append(item)
    existing.sort(key=lambda x: x["published_at"], reverse=True)
    return existing[:max_len]


def drop_poisoned(cache):
    """해석 실패한 구글 링크가 '죽은 링크'로 저장된 옛 캐시 항목을 지운다."""
    return {
        k: v for k, v in cache.items()
        if not ("news.google.com" in v.get("url", "") and not v.get("alive", True))
    }


def main():
    config = load_json(CONFIG_PATH, {"queries": [], "official_feeds": []})
    print(f"등록된 검색어 수: {len(config.get('queries', []))}")

    live = load_json(NEWS_PATH, [])
    live = prune_expired(live, POOL_RETENTION_DAYS * 24)
    # 이미 게시된 기사도 현재 기준으로 다시 걸러낸다.
    live = [item for item in live if is_relevant(item.get("title", ""))]

    cache = load_json(CACHE_PATH, {})
    cache = prune_cache(cache, CACHE_RETENTION_DAYS)
    cache = drop_poisoned(cache)
    print(f"캐시된 링크 수: {len(cache)}")

    collected = fetch_all(config, cache)
    live = merge(live, collected, 10000)
    live = select_live(live)

    save_json(NEWS_PATH, live)
    save_json(CACHE_PATH, cache)

    print(
        f"[{datetime.now(timezone.utc).isoformat()}] "
        f"{len(collected)}건 게시 (현재 live={len(live)}, 캐시={len(cache)})"
    )


if __name__ == "__main__":
    main()
