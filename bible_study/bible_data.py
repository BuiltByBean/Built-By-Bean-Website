import re
import time
import requests as http_requests

from config import Config

# ---------------------------------------------------------------------------
# Bible book data
# ---------------------------------------------------------------------------
BIBLE_BOOKS = [
    {"name": "Genesis", "chapters": 50, "testament": "OT"},
    {"name": "Exodus", "chapters": 40, "testament": "OT"},
    {"name": "Leviticus", "chapters": 27, "testament": "OT"},
    {"name": "Numbers", "chapters": 36, "testament": "OT"},
    {"name": "Deuteronomy", "chapters": 34, "testament": "OT"},
    {"name": "Joshua", "chapters": 24, "testament": "OT"},
    {"name": "Judges", "chapters": 21, "testament": "OT"},
    {"name": "Ruth", "chapters": 4, "testament": "OT"},
    {"name": "1 Samuel", "chapters": 31, "testament": "OT"},
    {"name": "2 Samuel", "chapters": 24, "testament": "OT"},
    {"name": "1 Kings", "chapters": 22, "testament": "OT"},
    {"name": "2 Kings", "chapters": 25, "testament": "OT"},
    {"name": "1 Chronicles", "chapters": 29, "testament": "OT"},
    {"name": "2 Chronicles", "chapters": 36, "testament": "OT"},
    {"name": "Ezra", "chapters": 10, "testament": "OT"},
    {"name": "Nehemiah", "chapters": 13, "testament": "OT"},
    {"name": "Esther", "chapters": 10, "testament": "OT"},
    {"name": "Job", "chapters": 42, "testament": "OT"},
    {"name": "Psalms", "chapters": 150, "testament": "OT"},
    {"name": "Proverbs", "chapters": 31, "testament": "OT"},
    {"name": "Ecclesiastes", "chapters": 12, "testament": "OT"},
    {"name": "Song of Solomon", "chapters": 8, "testament": "OT"},
    {"name": "Isaiah", "chapters": 66, "testament": "OT"},
    {"name": "Jeremiah", "chapters": 52, "testament": "OT"},
    {"name": "Lamentations", "chapters": 5, "testament": "OT"},
    {"name": "Ezekiel", "chapters": 48, "testament": "OT"},
    {"name": "Daniel", "chapters": 12, "testament": "OT"},
    {"name": "Hosea", "chapters": 14, "testament": "OT"},
    {"name": "Joel", "chapters": 3, "testament": "OT"},
    {"name": "Amos", "chapters": 9, "testament": "OT"},
    {"name": "Obadiah", "chapters": 1, "testament": "OT"},
    {"name": "Jonah", "chapters": 4, "testament": "OT"},
    {"name": "Micah", "chapters": 7, "testament": "OT"},
    {"name": "Nahum", "chapters": 3, "testament": "OT"},
    {"name": "Habakkuk", "chapters": 3, "testament": "OT"},
    {"name": "Zephaniah", "chapters": 3, "testament": "OT"},
    {"name": "Haggai", "chapters": 2, "testament": "OT"},
    {"name": "Zechariah", "chapters": 14, "testament": "OT"},
    {"name": "Malachi", "chapters": 4, "testament": "OT"},
    {"name": "Matthew", "chapters": 28, "testament": "NT"},
    {"name": "Mark", "chapters": 16, "testament": "NT"},
    {"name": "Luke", "chapters": 24, "testament": "NT"},
    {"name": "John", "chapters": 21, "testament": "NT"},
    {"name": "Acts", "chapters": 28, "testament": "NT"},
    {"name": "Romans", "chapters": 16, "testament": "NT"},
    {"name": "1 Corinthians", "chapters": 16, "testament": "NT"},
    {"name": "2 Corinthians", "chapters": 13, "testament": "NT"},
    {"name": "Galatians", "chapters": 6, "testament": "NT"},
    {"name": "Ephesians", "chapters": 6, "testament": "NT"},
    {"name": "Philippians", "chapters": 4, "testament": "NT"},
    {"name": "Colossians", "chapters": 4, "testament": "NT"},
    {"name": "1 Thessalonians", "chapters": 5, "testament": "NT"},
    {"name": "2 Thessalonians", "chapters": 3, "testament": "NT"},
    {"name": "1 Timothy", "chapters": 6, "testament": "NT"},
    {"name": "2 Timothy", "chapters": 4, "testament": "NT"},
    {"name": "Titus", "chapters": 3, "testament": "NT"},
    {"name": "Philemon", "chapters": 1, "testament": "NT"},
    {"name": "Hebrews", "chapters": 13, "testament": "NT"},
    {"name": "James", "chapters": 5, "testament": "NT"},
    {"name": "1 Peter", "chapters": 5, "testament": "NT"},
    {"name": "2 Peter", "chapters": 3, "testament": "NT"},
    {"name": "1 John", "chapters": 5, "testament": "NT"},
    {"name": "2 John", "chapters": 1, "testament": "NT"},
    {"name": "3 John", "chapters": 1, "testament": "NT"},
    {"name": "Jude", "chapters": 1, "testament": "NT"},
    {"name": "Revelation", "chapters": 22, "testament": "NT"},
]
BOOK_MAP = {b["name"]: b for b in BIBLE_BOOKS}
NT_BOOKS = {b["name"] for b in BIBLE_BOOKS if b["testament"] == "NT"}

# ---------------------------------------------------------------------------
# ESV API
# ---------------------------------------------------------------------------
ESV_API_BASE = "https://api.esv.org/v3/passage/text/"
ESV_COPYRIGHT = (
    "Scripture quotations are from the ESV\u00ae Bible "
    "(The Holy Bible, English Standard Version\u00ae), "
    "\u00a9 2001 by Crossway, a publishing ministry of Good News Publishers. "
    "Used by permission. All rights reserved."
)
_rate_requests: list[float] = []


def _rate_ok() -> bool:
    now = time.time()
    global _rate_requests
    _rate_requests = [t for t in _rate_requests if now - t < 3600]
    return sum(1 for t in _rate_requests if now - t < 60) < 55 and len(_rate_requests) < 950


def fetch_chapter(book: str, chapter: int) -> dict:
    api_key = Config.ESV_API_KEY
    if not api_key:
        return {"verses": [], "error": "ESV_API_KEY not configured", "copyright": ESV_COPYRIGHT}
    if not _rate_ok():
        return {"verses": [], "error": "Rate limit \u2014 please wait", "copyright": ESV_COPYRIGHT}
    try:
        is_single = book in BOOK_MAP and BOOK_MAP[book]["chapters"] == 1
        query = book if is_single else f"{book} {chapter}"
        resp = http_requests.get(ESV_API_BASE, params={
            "q": query, "include-headings": "false", "include-footnotes": "false",
            "include-verse-numbers": "true", "include-short-copyright": "false",
            "include-passage-references": "false", "indent-paragraphs": "0", "indent-poetry": "false",
        }, headers={"Authorization": f"Token {api_key}"}, timeout=10)
        _rate_requests.append(time.time())
        if resp.status_code != 200:
            return {"verses": [], "error": f"ESV API {resp.status_code}", "copyright": ESV_COPYRIGHT}
        return {"verses": _parse_verses(resp.json().get("passages", [""])[0]), "copyright": ESV_COPYRIGHT}
    except Exception as e:
        return {"verses": [], "error": str(e), "copyright": ESV_COPYRIGHT}


def fetch_verse_text(book: str, chapter: int, vs: int, ve: int) -> str:
    api_key = Config.ESV_API_KEY
    if not api_key or not _rate_ok():
        return ""
    q = f"{book} {chapter}:{vs}" if vs == ve else f"{book} {chapter}:{vs}-{ve}"
    try:
        resp = http_requests.get(ESV_API_BASE, params={
            "q": q, "include-headings": "false", "include-footnotes": "false",
            "include-verse-numbers": "false", "include-short-copyright": "false",
            "include-passage-references": "false", "indent-paragraphs": "0", "indent-poetry": "false",
        }, headers={"Authorization": f"Token {api_key}"}, timeout=10)
        _rate_requests.append(time.time())
        if resp.status_code == 200:
            return resp.json().get("passages", [""])[0].strip()
    except Exception:
        pass
    return ""


def fetch_ref_text(ref: str) -> str:
    api_key = Config.ESV_API_KEY
    if not api_key or not _rate_ok():
        return ""
    try:
        resp = http_requests.get(ESV_API_BASE, params={
            "q": ref, "include-headings": "false", "include-footnotes": "false",
            "include-verse-numbers": "true", "include-short-copyright": "false",
            "include-passage-references": "false", "indent-paragraphs": "0", "indent-poetry": "false",
        }, headers={"Authorization": f"Token {api_key}"}, timeout=10)
        _rate_requests.append(time.time())
        if resp.status_code == 200:
            return resp.json().get("passages", [""])[0].strip()
    except Exception:
        pass
    return ""


def _parse_verses(text: str) -> list[dict]:
    items = []
    flat = " ".join(text.split())
    parts = re.split(r"\[(\d+)\]\s*", flat)
    for i in range(1, len(parts), 2):
        vtext = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        if vtext:
            items.append({"type": "verse", "number": int(parts[i]), "text": vtext})
    return items


def format_ref(book, chapter, vs, ve):
    if not chapter:
        return book or ""
    if not vs:
        return f"{book} {chapter}"
    if vs == ve or not ve:
        return f"{book} {chapter}:{vs}"
    return f"{book} {chapter}:{vs}-{ve}"
