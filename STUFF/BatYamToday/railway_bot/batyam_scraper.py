#!/usr/bin/env python3
"""
סורק רב-מרחבי — BatYam Today
===============================
סורק את כל המרחבים (sections) באתר coing.co/batya
ושומר את כל האירועים ב-SQLite.

רץ כל 2 דקות מ-cron. לא שולח התראות — זו אחריות של batyam_dispatcher.py.
"""

import requests
from bs4 import BeautifulSoup
import re
import os
import json
import time
import datetime
import zoneinfo

import batyam_db as db

IL_TZ = zoneinfo.ZoneInfo("Asia/Jerusalem")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

BASE_URL = "https://www.coing.co"
CITY_SLUG = "batya"

# מרחבים ידועים — ניתן לגלות עוד דינמית
KNOWN_SECTIONS = [
    {"slug": "BatYam_Main", "name": "כללי — הבית שלכם", "cid": 2841},
    {"slug": "BatYam_shelters", "name": "פעילויות הפגה במקלטים", "cid": 9101},
    {"slug": "plusi_all", "name": "כל מה שקורה בבת ים", "cid": 7447},
    {"slug": "BatYam_culture", "name": "תרבות ופנאי", "cid": 4605},
    {"slug": "BatYam_south", "name": "רובע דרום", "cid": 3591},
    {"slug": "BatYam_Kehilot", "name": "רשת הקהילות", "cid": 4126},
]

# Slugs we never treat as discoverable sections (UI/utility paths on coing.co).
SECTION_BLACKLIST = {"events", "calendar", "map", "subcommunities", "whosin",
                     "site", "static", "static-icons", "login", "register"}

# Seed gids per section. coing.co's main API call (gid=0) only returns *direct*
# children of a community. Sections like BatYam_Kehilot (רשת הקהילות) are
# parent-of-parents — their direct children are sub-communities (e.g., קואלה,
# gid=67287), and the actual events live one level deeper. Without explicit
# seeds, the scraper would never reach those events because the section's HTML
# is JS-rendered and the API doesn't list nested communities. Seeds come from
# communities_data.json plus this hardcoded fallback for known good ones.
SECTION_SEED_GIDS = {
    # filled in at runtime from communities_data.json by load_extra_sections_from_json
}

# שכונות ידועות לזיהוי מתוך טקסט האירוע
NEIGHBORHOODS = [
    "רמת הנשיא",
    "רמת יוסף",
    "לב העיר",
    "רובע דרום",
    "רמת דרום",
    "רובע צפון",
    "צפון",
    "עמידר",
    "פארק הים",
]

# קבוצות גיל — רק זיהוי מפורש של מספרים בטקסט.
# אסור להמציא גיל ממילים כמו "תינוקות"/"פעוטות"/"גן"/"נוער" — מילים אלו אינן
# מבטיחות טווח גיל מדויק, ואירועים שיוצגו עם גיל שגוי גורמים לאנשים
# להירשם בטעות לפעילויות שאינן מתאימות לילדיהם.
# חשוב: הדפוסים מסודרים מהספציפי לכללי. דפוסים פתוחים כמו "מגיל 14" נמנעים
# כי הם תופסים מספרים מקריים בטקסט (למשל "מלווה מגיל 14"), ודפוסים כמו
# "גיל 60+" נמנעים כי הם תופסים אזכורים שוליים שאינם מגדירים את גיל הפעילות.
# העדפנו להחזיר None מאשר לתייג טעות.
AGE_PATTERNS = [
    # טווחי גיל מפורשים עם תווית מקדימה (הכי אמין). תומך בדצימליים (1.5-2.5).
    (r'לגיל[איי]{0,2}\s*(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)', lambda m: f"{m.group(1)}-{m.group(2)}"),
    (r'גילאי?\s*(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)', lambda m: f"{m.group(1)}-{m.group(2)}"),
    (r'בני\s*(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)', lambda m: f"{m.group(1)}-{m.group(2)}"),
    (r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*שנ', lambda m: f"{m.group(1)}-{m.group(2)}"),
    # "גילי X עד Y" / "מגיל X עד Y" / "בגילאי X עד Y" / "בני X עד Y"
    (r'לגיל[איי]{0,2}\s*(\d+\.?\d*)\s*עד\s*(\d+\.?\d*)', lambda m: f"{m.group(1)}-{m.group(2)}"),
    (r'גילאי?\s*(\d+\.?\d*)\s*עד\s*(\d+\.?\d*)', lambda m: f"{m.group(1)}-{m.group(2)}"),
    (r'מגיל\s*(\d+\.?\d*)\s*עד\s*(\d+\.?\d*)', lambda m: f"{m.group(1)}-{m.group(2)}"),
    (r'בני\s*(\d+\.?\d*)\s*עד\s*(\d+\.?\d*)', lambda m: f"{m.group(1)}-{m.group(2)}"),
    # טווחי חודשים מפורשים
    (r'(\d+)\s*[-–]\s*(\d+)\s*חודש', lambda m: f"{m.group(1)}-{m.group(2)} חודשים"),
    (r'לידה\s*[-–]\s*(\d+)\s*חודש', lambda m: f"0-{m.group(1)} חודשים"),
    (r'מלידה\s*עד\s*גיל\s*(\d+)', lambda m: f"0-{m.group(1)}"),
    (r'גילאי?\s*זחילה\s*עד\s*(\d+)', lambda m: f"0-{m.group(1)}"),
    # תוויות "+" / "ומעלה" — רק כשמוצמדות לתווית גיל מובהקת
    (r'לגיל[איי]{0,2}\s*(\d+\.?\d*)\s*\+', lambda m: f"{m.group(1)}+"),
    (r'גילאי?\s*(\d+\.?\d*)\s*\+', lambda m: f"{m.group(1)}+"),
    (r'לגיל[איי]{0,2}\s*(\d+\.?\d*)\s*ומעלה', lambda m: f"{m.group(1)}+"),
    (r'גילאי?\s*(\d+\.?\d*)\s*ומעלה', lambda m: f"{m.group(1)}+"),
    # לא מוסיפים: "גיל\s*(\d+)\+", "מגיל\s*(\d+)", "עד\s*גיל\s*(\d+)" — אלה
    # תופסים אזכורים מקריים בטקסט (כמו "מלווה מגיל 14") ומובילים לתיוג שגוי.
]

# מיקומים ידועים
KNOWN_LOCATIONS = [
    "מתנ\"ס הבונים", "מתנס הבונים", "מרכז קהילתי הבונים",
    "מתנ\"ס עופר", "מתנס עופר",
    "מתנ\"ס בית צדיק", "מתנס בית צדיק", "בית צדיק",
    "מתנ\"ס רמת יוסף", "מתנס רמת יוסף",
    "תרבוטק",
    "בי\"ס נחשונים", "בי\"ס גורדון", "בי\"ס תחכמוני", "בי\"ס הראל",
    "בית ספר נחשונים", "בית ספר גורדון", "בית ספר תחכמוני", "בית ספר הראל",
    "פארק הים",
]

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batyam_scraper.log")


def _load_telegram_secrets():
    """Best-effort read of bot token + admin chat ids — for _admin_alert.

    Mirrors batyam_bot.load_secrets() lookup order. Returns (token, [chat_ids]).
    Returns ('', []) if the file is missing — _admin_alert becomes a no-op.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(here), "batyam_secrets.json"),
        os.path.join(os.path.expanduser("~"), "batyam_secrets.json"),
        os.path.join(here, "batyam_secrets.json"),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    s = json.load(f)
                return s.get("TELEGRAM_BOT_TOKEN", ""), list(s.get("ADMIN_CHAT_IDS", []))
            except Exception:
                pass
    # Fallback to environment variables (Railway reads these at boot in main.py).
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    raw_ids = os.environ.get("ADMIN_CHAT_IDS", "[]")
    try:
        ids = list(json.loads(raw_ids))
    except Exception:
        ids = []
    return token, ids


_TG_TOKEN, _TG_ADMINS = _load_telegram_secrets()


def _admin_alert(html_msg):
    """Send a Telegram message to every admin. Silent on failure.

    Used for: scraper errors, new sections discovered, daily health summary.
    Strictly admin-only — recipients come from ADMIN_CHAT_IDS in secrets/env,
    never from the users table. This is for the operator (Merav), not residents.
    """
    if not _TG_TOKEN or not _TG_ADMINS:
        return
    for chat_id in _TG_ADMINS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": html_msg, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=5,
            )
        except Exception:
            pass


def log(msg):
    line = f"[{datetime.datetime.now(IL_TZ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def detect_neighborhood(text):
    """זיהוי שכונה מתוך טקסט האירוע."""
    for n in NEIGHBORHOODS:
        if n in text:
            return n
    return None


# מילות מספר בעברית → מספר. רק מילים שבאמת מתארות גיל בילדים (1-18).
# הסדר חשוב: צירופים ארוכים קודם (למשל "אחת עשרה" לפני "אחת").
HEBREW_NUMBER_WORDS = [
    ("שמונה עשרה", "18"), ("שבע עשרה", "17"), ("שש עשרה", "16"),
    ("חמש עשרה", "15"), ("ארבע עשרה", "14"), ("שלוש עשרה", "13"),
    ("שתים עשרה", "12"), ("שנים עשרה", "12"), ("אחת עשרה", "11"),
    ("שמונה", "8"), ("ארבע", "4"), ("חמש", "5"), ("שש", "6"),
    ("שבע", "7"), ("תשע", "9"), ("עשר", "10"), ("שלוש", "3"),
    ("שתי", "2"), ("שני", "2"),
    # שנה / שנתיים יחידים — נתרגם רק בהקשר גיל
    ("שנתיים", "2"),
    ("שנה", "1"),
]


def _normalize_hebrew_numbers(text):
    """המרת מילות מספר בעברית למספרים, רק בהקשר של גיל.

    מטרה: לאפשר ל-AGE_PATTERNS לתפוס טקסט כמו "בגילאי שנה- שלוש שנים" → "1-3".
    החלפה גלובלית של "שנה" → "1" תהיה מסוכנת (שינוי "השנה", "שנה טובה" וכו'),
    לכן אנו פועלים רק על קטעים שכוללים תווית גיל ברורה.
    """
    # נתפוס קטע שמתחיל בתווית גיל ("גילאי/לגיל/מגיל/בגילאי/בני") ונמשך עד
    # סוף משפט/פיסוק. בתוך הקטע נחליף מילות מספר בעברית לספרות. הקטע יכול
    # להסתיים ב"שנים" או בלעדיה ("גילאי שנה עד שלוש").
    # תפיסת קטע שלם מהתווית "גילאי" עד סוף משפט. greedy כדי לתפוס
    # גם "בגילאי שנה- שלוש שנים" כשלמות (לא רק "בגילאי שנה").
    age_phrase_re = re.compile(
        r'((?:ל?גילאי|לגיל[איי]?|מגיל|בגילאי?|בני)'
        r'[^.;\n!?]{0,80})'
    )

    def replace_in_phrase(match):
        phrase = match.group(1)
        # רק boundary בהתחלה — לא מציגים boundary בסוף כי בטקסטים מהקוינג
        # מילים נצמדות זו לזו ללא רווח (למשל "שנתייםהפעילות"). הסדר ב-
        # HEBREW_NUMBER_WORDS מתחיל מצירופים ארוכים, כך שהמילה הספציפית
        # ביותר נתפסת ראשונה.
        for word, digit in HEBREW_NUMBER_WORDS:
            phrase = re.sub(r'(?<![א-ת])' + word, digit, phrase)
        return phrase

    return age_phrase_re.sub(replace_in_phrase, text)


def detect_age_group(text):
    """זיהוי קבוצת גיל מתוך טקסט האירוע."""
    if not text:
        return None
    # תמיכה במילות מספר בעברית ("שנה", "שלוש שנים")
    normalized = _normalize_hebrew_numbers(text)
    for pattern, formatter in AGE_PATTERNS:
        m = re.search(pattern, normalized)
        if m:
            result = formatter(m)
            return _normalize_range_order(result)
    return None


def _normalize_range_order(s):
    """אם הטווח הפוך (8-4) נסדר אותו מהקטן לגדול (4-8).

    Why: בעורך RTL, "לגילי 4-8" נשמר במקור כ-"לגילי 8-4" כי המספרים נכתבים
    בסדר חזותי לא לוגי. הregex תופס את הסדר המקורי, אבל ההצגה למשתמש
    חייבת להיות מהצעיר למבוגר. אם כתב המשתמשת זאת ככה — זו טעות RTL,
    לא כוונה. השמלום הוא תמיד טווח מקטן לגדול.
    """
    if not s or "-" not in s:
        return s
    suffix = ""
    core = s
    for tail in (" חודשים",):
        if s.endswith(tail):
            core = s[: -len(tail)]
            suffix = tail
            break
    parts = core.split("-")
    if len(parts) != 2:
        return s
    try:
        a, b = float(parts[0]), float(parts[1])
    except ValueError:
        return s
    if a <= b:
        return s
    # הופכים: 8-4 → 4-8, 2.5-1.5 → 1.5-2.5
    def fmt(n):
        return str(int(n)) if n.is_integer() else str(n)
    return f"{fmt(b)}-{fmt(a)}{suffix}"


def detect_time(text):
    """זיהוי שעת האירוע מתוך הטקסט."""
    # Match HH:MM patterns (not dates)
    patterns = [
        r'(?:שעה|בשעה)\s*(\d{1,2}[:.]\d{2})',      # שעה 9:00
        r'(\d{1,2}:\d{2})\s*$',                       # ends with time
        r'\b(\d{1,2}:\d{2})\b(?!\s*/\s*\d)',           # HH:MM not followed by /digit (not capacity)
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            t = m.group(1).replace('.', ':')
            # Validate it's a reasonable time
            parts = t.split(':')
            if len(parts) == 2:
                h, mi = int(parts[0]), int(parts[1])
                if 6 <= h <= 23 and 0 <= mi <= 59:
                    return f"{h:02d}:{mi:02d}"
    return None


def detect_location(text):
    """זיהוי מיקום מתוך טקסט האירוע."""
    # Zoom detection
    if re.search(r'zoom|זום', text, re.IGNORECASE):
        return "זום (אונליין)"

    text_lower = text.lower()
    text_no_quotes = re.sub(r'["\']', '', text)

    for loc in KNOWN_LOCATIONS:
        loc_clean = re.sub(r'["\']', '', loc)
        if loc_clean in text_no_quotes or loc_clean.lower() in text_lower:
            return loc

    # Try regex patterns for common location formats
    location_patterns = [
        r'(מתנ"?ס\s+[\u0590-\u05FF]+(?:\s+[\u0590-\u05FF]+)?)',
        r'(מרכז קהילתי\s+[\u0590-\u05FF]+)',
        r'(בי"?ס\s+[\u0590-\u05FF]+)',
        r'(בית ספר\s+[\u0590-\u05FF]+)',
    ]
    for pat in location_patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()

    return None


def fetch_section_cid(session, section_slug):
    """Discover the community ID for a section by fetching its page.

    coing.co exposes the community id in three forms across different page
    versions; try them in order.
    """
    url = f"{BASE_URL}/{CITY_SLUG}/{section_slug}"
    try:
        resp = session.get(url, headers={"User-Agent": UA}, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        for pat in (r'"cid"\s*:\s*(\d+)', r'cid=(\d+)', r'"id"\s*:\s*(\d+)'):
            m = re.search(pat, resp.text)
            if m:
                cid = int(m.group(1))
                # Reject obvious noise (single-digit ids are usually unrelated objects).
                if cid > 100:
                    return cid
    except Exception as e:
        log(f"  שגיאה בגילוי cid עבור {section_slug}: {e}")
    return None


def scrape_section(session, section):
    """Scrape all events from a single section."""
    slug = section["slug"]
    cid = section["cid"]
    section_url = f"{BASE_URL}/{CITY_SLUG}/{slug}"

    log(f"  סורק: {section['name']} ({slug}, cid={cid})")

    # Get CSRF token
    try:
        resp = session.get(section_url, headers={"User-Agent": UA}, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as e:
        log(f"  שגיאה בטעינת {slug}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    csrf_meta = soup.find("meta", {"name": "csrf-token"})
    csrf = csrf_meta["content"] if csrf_meta else ""

    api_headers = {
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRF-Token": csrf,
        "Accept": "*/*",
        "Referer": section_url,
    }

    # Paginate through the API. Most sections are flat (gid=0 returns the
    # full event list). A few are hierarchical (e.g. BatYam_Kehilot, where
    # actual events live under sub-community gids like 67287 = קואלה).
    #
    # Strategy: ALWAYS fetch gid=0 with full pagination. Then visit ONLY the
    # explicit seed gids registered for this slug (via communities_data.json
    # or discover_section_from_url). Don't auto-discover children from item
    # HTML — for flat sections like plusi_all, every event in the list looks
    # like a "child gid", which causes the BFS to explode (~200 useless
    # fetches per scrape, every 2 minutes). Explicit seeds are the only safe
    # source of nested gids; we already capture them when a coing URL with a
    # gid is reported via the bot or seeded from the JSON.
    MAX_PAGES_PER_GID = 50
    all_items = []
    fetches = 0

    seeds = sorted(SECTION_SEED_GIDS.get(slug, ()))
    gids_to_scan = [0] + [g for g in seeds if g != 0]

    for gid in gids_to_scan:
        page = 1
        while page <= MAX_PAGES_PER_GID:
            try:
                resp2 = session.get(
                    f"{BASE_URL}/site/communities/groups",
                    params={"cid": cid, "type": "regular", "view": "auto", "gid": gid, "page": page},
                    headers=api_headers, timeout=15,
                )
                fetches += 1
                data = resp2.json()
                if not data.get("success") or not data.get("items"):
                    break
                all_items.extend(data["items"])
                page += 1
                time.sleep(0.4)
            except Exception as e:
                log(f"  שגיאה בעמוד {page} (gid={gid}): {e}")
                break

    if seeds:
        log(f"  גרפנו gid=0 + {len(seeds)} זרעים, {fetches} בקשות")
    else:
        log(f"  גרפנו gid=0, {fetches} בקשות")

    log(f"  נמצאו {len(all_items)} אירועים (API)")

    # Direct-fetch fallback: check known event IDs that API doesn't return
    # Also scan for sub-events by fetching each top-level event page
    api_ids = set()
    for item_html in all_items:
        for m in re.finditer(r'/' + re.escape(slug) + r'/(\d+)', item_html):
            api_ids.add(m.group(1))

    # Also check IDs already in DB for this section
    try:
        conn = db.get_db()
        existing = set(r[0] for r in conn.execute(
            "SELECT event_id FROM events WHERE section_id=(SELECT id FROM sections WHERE slug=?)",
            (slug,)).fetchall())
        conn.close()
        api_ids.update(existing)
    except:
        pass

    # Discover hidden events by scanning each top-level event page for links.
    # This is expensive (20 HTTP fetches per section) — run at most once per 24h.
    hidden_ids = set()
    if db.should_scan_hidden(slug, max_age_hours=24):
        for top_id in sorted(api_ids)[:20]:  # check top 20 known events
            try:
                page_resp = session.get(f"{BASE_URL}/{CITY_SLUG}/{slug}/{top_id}",
                                       headers={"User-Agent": UA}, timeout=10)
                if page_resp.status_code == 200:
                    for m in re.finditer(r'/' + re.escape(slug) + r'/(\d+)', page_resp.text):
                        found_id = m.group(1)
                        if found_id not in api_ids and found_id not in hidden_ids:
                            hidden_ids.add(found_id)
                time.sleep(0.3)
            except:
                pass
        try:
            db.mark_hidden_scanned(slug)
        except Exception:
            pass

    if hidden_ids:
        log(f"  Fallback: {len(hidden_ids)} אירועים נסתרים נמצאו בדפי אירועים")
        fallback_count = 0
        for eid in sorted(hidden_ids)[:10]:  # max 10 per run
            try:
                event_url = f"{BASE_URL}/{CITY_SLUG}/{slug}/{eid}"
                eresp = session.get(event_url, headers={"User-Agent": UA}, timeout=15)
                eresp.raise_for_status()
                eresp.encoding = "utf-8"
                esoup = BeautifulSoup(eresp.text, "html.parser")
                etext = esoup.get_text(separator=" ", strip=True)

                # Get title from og:title
                og = esoup.find("meta", property="og:title")
                title = og["content"].strip() if og and og.get("content") else ""
                if not title or len(title) < 3:
                    title = "פעילות"

                # Parse event data — coing shows fullness in several ways
                # (etext is the visible-text extract; HTML attrs aren't here).
                is_full = ("לא נשאר מקום" in etext or "אופס" in etext
                           or "האירוע מלא" in etext)
                is_past = "אירוע שחלף" in etext
                date_match = re.search(r'(\d{1,2}/\d{2}/\d{4})', etext)
                event_date = date_match.group(1) if date_match else ""

                cap_match = re.search(r'רשומים\s*\((\d+)/(\d+)\)', etext)
                registered = int(cap_match.group(1)) if cap_match else 0
                capacity = int(cap_match.group(2)) if cap_match else 0
                if capacity > 0 and registered >= capacity:
                    is_full = True

                # Get image
                og_img = esoup.find("meta", property="og:image")
                image_url = og_img["content"].strip() if og_img and og_img.get("content") else ""

                neighborhood = detect_neighborhood(etext)
                age_group = detect_age_group(etext)
                event_time = detect_time(etext)
                location = detect_location(etext)

                # Build HTML-like item for parse_event compatibility
                fallback_html = f'<div><a href="{event_url}">{title}</a><span>{etext[:200]}</span></div>'

                # Upsert directly
                db.upsert_event(
                    event_id=eid,
                    section_id=section.get("id", 0),
                    title=title,
                    event_date=event_date,
                    registered=registered,
                    capacity=capacity,
                    is_full=is_full,
                    is_past=is_past,
                    link=event_url,
                    raw_text=etext[:2000],
                    neighborhood=neighborhood,
                    age_group=age_group,
                    event_time=event_time,
                    location=location,
                    image_url=image_url,
                )
                log(f"    + {title[:40]} (fallback)")
                fallback_count += 1
                time.sleep(1)  # courtesy delay
            except Exception as e:
                log(f"    שגיאת fallback {eid}: {e}")
        if fallback_count:
            log(f"  HTML fallback: נוספו {fallback_count} אירועים")

    return all_items


def parse_event(html_item):
    """Parse a single event from HTML."""
    soup_item = BeautifulSoup(html_item, "html.parser")
    text = soup_item.get_text(separator=" ", strip=True)

    link_el = soup_item.find("a", href=True)
    link = link_el["href"] if link_el else ""
    if link and not link.startswith("http"):
        link = BASE_URL + link
    event_id = link.rstrip("/").split("/")[-1] if link else ""

    # Extract title — try structured elements first, then clean from raw text
    title = ""
    title_el = soup_item.find(["h3", "h4", "h2"])
    if title_el:
        title = title_el.get_text(strip=True)
    if not title:
        strong_el = soup_item.find("strong")
        if strong_el:
            title = strong_el.get_text(strip=True)
    if not title:
        title = text[:200] if text else ""

    # Clean title: remove common prefixes and cut at description markers
    for prefix in [
        r'^בת ים\s*[-–]\s*פעילויות הפגה במקלטים\s*',
        r'^בת ים\s*[-–]\s*רמת יוסף ולב העיר\s*',
        r'^בת ים\s*[-–]\s*רובע דרום\s*',
        r'^בת ים\s*[-–]\s*רמת הנשיא\s*',
        r'^בת ים\s*[-–]\s*רובע צפון\s*',
        r'^בת ים\s*[-–]\s*הבית שלכם\s*',
        r'^בת ים\s*[-–]\s*רשת הקהילות\s*',
        r'^החברה לתרבות פנאי וספורט בת ים\s*',
        r'^תרבות ופנאי בבת ים\s*',
        r'^בתיה מרכז הצעירים של בת ים\s*',
        r'^Born in Bat Yam\s*',
        r'^ענת\s+',
        r'^מאור ארביבו\s+',
    ]:
        title = re.sub(prefix, '', title)

    # Remove location if it will be shown separately
    title = re.sub(r'\s*[-–]\s*מתנ"?ס\s+[\u0590-\u05FF]+(?:\s+[\u0590-\u05FF]+)?', '', title)
    title = re.sub(r'\s*[-–]\s*פעילות הפוגה', '', title)
    title = re.sub(r'\s*הפוגה במקלט', '', title)

    # Cut at description/filler markers (even at position 0 for some)
    cut_markers_any = ['הנכם מוזמנים', 'הורים יקריםהנכם', 'תושבים יקרים,',
                       'סבתא יקרה,', 'https://', '📅', '🪑', '❄', '📸', '🚀', '💸', '🤲', '📢']
    cut_markers_5 = ['הורים יקרים', 'תושבי בת ים', 'בואו אלינו',
                     'הצטרפו', 'לפרטים', 'נכון?', 'את בפנים']
    for marker in cut_markers_any:
        idx = title.find(marker)
        if idx >= 0:
            title = title[:idx] if idx > 0 else title
            break
    for marker in cut_markers_5:
        idx = title.find(marker)
        if idx > 5:
            title = title[:idx]
            break

    # Remove trailing junk
    title = re.sub(r'[-–,\s]+$', '', title).strip()
    # Limit length — cut at last space before 80 chars
    if len(title) > 80:
        cut = title[:80].rfind(' ')
        if cut > 20:
            title = title[:cut]
    if not title:
        title = "פעילות"

    is_full = ("לא נשאר מקום" in text or "אופס" in text
               or "האירוע מלא" in text)
    # Also mark full if registered >= capacity and capacity > 0
    # (will be checked again after capacity is parsed below)
    is_past = "אירוע שחלף" in text

    date_match = re.search(r'(\d{1,2}/\d{2}/\d{4})', text)
    event_date = date_match.group(1) if date_match else ""

    # Capacity: look for "רשומים (X/Y)" pattern on the event page
    # Note: "הצטרפו X Y" in list view is NOT capacity — it's "joined X, minimum Y"
    registered = 0
    capacity = 0
    # Look for explicit registered/capacity pattern
    cap_match = re.search(r'רשומים\s*\((\d+)/(\d+)\)', text)
    if cap_match:
        registered = int(cap_match.group(1))
        capacity = int(cap_match.group(2))
    else:
        # Find all X/Y patterns and pick the one that's NOT a date
        for m in re.finditer(r'(\d+)/(\d+)', text):
            left = int(m.group(1))
            right = int(m.group(2))
            # Skip if it looks like a date (DD/MM where right > 12 = year portion)
            if right > 31:  # likely year (2026)
                continue
            if right >= 1 and right <= 12 and left >= 1 and left <= 31:
                # Could be DD/MM date — skip if followed by /YYYY
                after = text[m.end():m.end()+5]
                if re.match(r'/\d{4}', after):
                    continue
                # Could still be a date DD/MM without year — skip
                continue
            # Looks like capacity
            registered = left
            capacity = right
            break

    # Mark full if capacity reached
    if capacity > 0 and registered >= capacity:
        is_full = True

    # Extract image
    img_el = soup_item.find("img", src=True)
    image_url = ""
    if img_el:
        src = img_el.get("src", "")
        if src and not src.endswith('.svg') and 'logo' not in src.lower():
            image_url = src if src.startswith("http") else BASE_URL + src

    neighborhood = detect_neighborhood(text)
    age_group = detect_age_group(text)
    event_time = detect_time(text)
    location = detect_location(text)

    return {
        "event_id": event_id,
        "title": title,
        "link": link,
        "date": event_date,
        "is_full": is_full,
        "is_past": is_past,
        "registered": registered,
        "capacity": capacity,
        "text": text,
        "neighborhood": neighborhood,
        "age_group": age_group,
        "event_time": event_time,
        "location": location,
        "image_url": image_url,
    }


def discover_section_from_url(url, session=None):
    """Extract section slug from a coing.co event/section URL and ensure it's
    registered for scraping. Self-healing entry point used by the bot's
    /missing flow and any future ingest channel.

    Accepts:
      - https://www.coing.co/batya/<SLUG>
      - https://www.coing.co/batya/<SLUG>/
      - https://www.coing.co/batya/<SLUG>/<event_id>
      - /batya/<SLUG>/...

    Returns dict {slug, name, cid, section_id, was_new} on success; None on failure.
    """
    if not url:
        return None
    m = re.search(rf'(?:^|/){CITY_SLUG}/([A-Za-z0-9_]+)(?:/(\d+))?', url)
    if not m:
        return None
    slug = m.group(1)
    if slug in SECTION_BLACKLIST:
        return None
    gid_str = m.group(2)
    if gid_str:
        try:
            SECTION_SEED_GIDS.setdefault(slug, set()).add(int(gid_str))
        except ValueError:
            pass

    existing = {s["slug"]: s for s in db.get_active_sections(CITY_SLUG)}
    if slug in existing:
        s = existing[slug]
        return {"slug": slug, "name": s["name"], "cid": s["cid"],
                "section_id": s["id"], "was_new": False}

    own_session = session is None
    if own_session:
        session = requests.Session()
    try:
        cid = fetch_section_cid(session, slug)
    finally:
        if own_session:
            session.close()
    if not cid:
        return None

    section_id = db.upsert_section(slug, slug, cid, CITY_SLUG)
    log(f"  self-heal: סקציה חדשה נוספה לסריקה — {slug} (cid={cid})")
    _admin_alert(f"🆕 סקציה חדשה התווספה דרך self-healing: <b>{slug}</b> (cid={cid})")
    return {"slug": slug, "name": slug, "cid": cid,
            "section_id": section_id, "was_new": True}


def load_extra_sections_from_json():
    """Read communities_data.json and return [{slug, name, cid=0}, ...].

    The JSON is the curated list of communities/sections we've observed in the
    wild. coing.co's main BatYam page does not link to most of them, so this
    file is how we learn about sections like BatYam_Kehilot. Each entry's URL
    is parsed for the slug; the cid is resolved later via fetch_section_cid.

    Searched paths (first hit wins):
      1. Same dir as scraper (railway_bot/)
      2. Parent dir (the repo root)
      3. BATYAM_DATA_DIR (Railway volume) — if env var is set
    """
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "communities_data.json"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "communities_data.json"),
    ]
    if os.environ.get("BATYAM_DATA_DIR"):
        candidates.append(os.path.join(os.environ["BATYAM_DATA_DIR"], "communities_data.json"))

    path = next((p for p in candidates if os.path.exists(p)), None)
    if not path:
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception as e:
        log(f"  שגיאה בטעינת communities_data.json: {e}")
        return []

    seen = set()
    out = []
    for entry in entries:
        url = (entry or {}).get("url", "")
        m = re.search(rf'/{CITY_SLUG}/([A-Za-z0-9_]+)(?:/(\d+))?', url)
        if not m:
            continue
        slug = m.group(1)
        gid = m.group(2)  # may be None for top-level URLs
        if slug in SECTION_BLACKLIST:
            continue
        if slug not in seen:
            seen.add(slug)
            # Strip the "עוד מידע על  | " prefix the scraper-generator added.
            name = (entry.get("name") or slug).replace("עוד מידע על  |", "").strip(" |")
            out.append({"slug": slug, "name": name or slug, "cid": 0})
        # Register the gid as a seed so scrape_section visits it explicitly.
        # Top-level coing API only returns direct children — without seeds,
        # nested communities like קואלה (gid=67287) under BatYam_Kehilot
        # are unreachable.
        if gid:
            try:
                gid_int = int(gid)
            except ValueError:
                continue
            SECTION_SEED_GIDS.setdefault(slug, set()).add(gid_int)
    return out


def discover_sections(session):
    """Try to discover all sections from the main city page."""
    url = f"{BASE_URL}/{CITY_SLUG}"
    try:
        resp = session.get(url, headers={"User-Agent": UA}, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find links to subcommunities
        links = soup.find_all("a", href=True)
        sections = []
        seen_slugs = set()
        for link in links:
            href = link["href"]
            m = re.match(rf'/{CITY_SLUG}/([A-Za-z0-9_]+)/?$', href)
            if m:
                slug = m.group(1)
                if slug not in seen_slugs and slug not in SECTION_BLACKLIST:
                    seen_slugs.add(slug)
                    name = link.get_text(strip=True) or slug
                    sections.append({"slug": slug, "name": name, "cid": 0})
        return sections
    except Exception as e:
        log(f"שגיאה בגילוי מרחבים: {e}")
        return []


def enrich_event(session, event_id, link):
    """Fetch individual event page for real capacity, time range, and image."""
    if not link:
        return {}
    try:
        resp = session.get(link, headers={"User-Agent": UA}, timeout=15)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        text = resp.text

        result = {}

        # Real capacity: "רשומים (X/Y)"
        m = re.search(r'רשומים\s*\((\d+)/(\d+)\)', text)
        if m:
            result["registered"] = int(m.group(1))
            result["capacity"] = int(m.group(2))
            result["is_full"] = result["registered"] >= result["capacity"]

        # Textual full markers — coing.co shows several variants depending on
        # the event type. Some don't expose the (X/Y) badge at all:
        #   - "לא נשאר מקום" / "אופס!" — older / event-page-style notices
        #   - data-type="group-full" — semantic marker on the disabled register
        #     button; reliable across all full events (verified 2026-05-07
        #     against מסיבת אוזניות 259675 which had no other markers)
        #   - "האירוע מלא" — visible label inside that disabled button
        # Trust any of these in addition to the registered/capacity check.
        if ("לא נשאר מקום" in text or "אופס!" in text
                or 'data-type="group-full"' in text
                or "האירוע מלא" in text):
            result["is_full"] = True
            # Make sure capacity > 0 so upsert_event keeps the is_full flag
            # (its CASE branches need a positive capacity to overwrite).
            if not result.get("capacity"):
                result["capacity"] = result.get("registered", 1) or 1
                result["registered"] = result["capacity"]

        # Real date from individual page: "יום ג׳ 24/03/2026"
        date_m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})\s*$', text, re.MULTILINE)
        if not date_m:
            date_m = re.search(r'יום\s+\S+\s+(\d{1,2})/(\d{1,2})/(\d{4})', text)
        if date_m:
            d, mo, y = date_m.group(1), date_m.group(2), date_m.group(3)
            result["event_date"] = f"{int(d):02d}/{int(mo):02d}/{y}"
            result["event_date_iso"] = f"{y}-{int(mo):02d}-{int(d):02d}"

        # Time range from calendar links (UTC — add 2 for Israel)
        start_m = re.search(r'startdt=\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})', text)
        end_m = re.search(r'enddt=\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})', text)
        if not start_m:
            start_m = re.search(r'dates=\d{8}T(\d{2})(\d{2})\d{2}Z/', text)
            end_m = re.search(r'dates=\d{8}T\d{6}Z/\d{8}T(\d{2})(\d{2})\d{2}Z', text)
        if start_m and end_m:
            # Convert UTC to Israel time — use zoneinfo for correct DST
            try:
                from zoneinfo import ZoneInfo
                import datetime as _dt
                _now = _dt.datetime.now(ZoneInfo("Asia/Jerusalem"))
                offset = _now.utcoffset().total_seconds() / 3600
                offset = int(offset)
            except:
                offset = 2  # fallback to winter time
            sh = int(start_m.group(1)) + offset
            sm = int(start_m.group(2))
            eh = int(end_m.group(1)) + offset
            em = int(end_m.group(2))
            result["event_time"] = f"{sh:02d}:{sm:02d}"
            result["end_time"] = f"{eh:02d}:{em:02d}"
        else:
            # Fallback: Hebrew pattern "שעה 9-11" or "09:00 - 11:00"
            m = re.search(r'(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})', text)
            if m:
                result["event_time"] = m.group(1)
                result["end_time"] = m.group(2)
            else:
                m = re.search(r'שעה\s*(\d{1,2})\s*[-–]\s*(\d{1,2})', text)
                if m:
                    result["event_time"] = f"{int(m.group(1)):02d}:00"
                    result["end_time"] = f"{int(m.group(2)):02d}:00"

        # Parse HTML for meta tags
        soup = BeautifulSoup(text, "html.parser")

        # og:title — use as clean title (H1 of the event page)
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            clean = og_title["content"].strip()
            # Skip if it's just a section name
            skip_titles = ["בת ים", "פעילויות הפגה", "כל מה שקורה", "תרבות ופנאי", "רובע"]
            if clean and len(clean) > 5 and not any(clean.startswith(s) for s in skip_titles):
                result["title"] = clean

        # Full page text — for location/age/neighborhood enrichment
        page_text = soup.get_text(separator=" ", strip=True)
        if not result.get("age_group"):
            age = detect_age_group(page_text)
            if age:
                result["age_group"] = age
        if not result.get("location"):
            loc = detect_location(page_text)
            if loc:
                result["location"] = loc
        if not result.get("neighborhood"):
            hood = detect_neighborhood(page_text)
            if hood:
                result["neighborhood"] = hood

        # Location: from div with location/address class
        if not result.get("location"):
            loc_div = soup.find(['div','span','p'], class_=re.compile(r'location|address|venue|place', re.I))
            if loc_div:
                loc_text = loc_div.get_text(strip=True)
                # Clean: remove ", ישראל" suffix
                loc_text = re.sub(r',?\s*ישראל\s*$', '', loc_text).strip()
                if loc_text and len(loc_text) > 3 and len(loc_text) < 60:
                    result["location"] = loc_text

        # Image: og:image meta tag
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            img = og_img["content"]
            if img and "logo" not in img.lower() and "favicon" not in img.lower():
                result["image_url"] = img

        # Fallback: first event image
        if "image_url" not in result:
            img_el = soup.find("img", class_=re.compile(r'event|group|cover'))
            if img_el and img_el.get("src"):
                src = img_el["src"]
                if src and "logo" not in src.lower():
                    result["image_url"] = src if src.startswith("http") else BASE_URL + src

        return result
    except Exception as e:
        log(f"    שגיאה בהעשרת {event_id}: {e}")
        return {}


def main():
    import fcntl

    # Lockfile: prevent overlapping cron runs
    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".batyam_scraper.lock")
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        lock_fd.close()
        return  # Another scrape running — exit silently

    try:
        _main_inner()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _main_inner():
    log("=" * 50)
    log("BatYam Today — סורק פעילויות")

    session = requests.Session()

    # Ensure known sections are in DB
    for sec in KNOWN_SECTIONS:
        if sec["cid"] == 0:
            # Try to discover CID
            cid = fetch_section_cid(session, sec["slug"])
            if cid:
                sec["cid"] = cid
                log(f"  גילוי cid: {sec['slug']} = {cid}")
            else:
                log(f"  לא ניתן לגלות cid עבור {sec['slug']}, מדלג")
                continue
        db.upsert_section(sec["slug"], sec["name"], sec["cid"], CITY_SLUG)

    # Merge sections from communities_data.json (curated extras coing.co doesn't link from /batya).
    # This is how slugs like BatYam_Kehilot get into the active scrape — the home page
    # only links to plusi_all, so dynamic discover_sections() can't see them.
    extras = load_extra_sections_from_json()
    if extras:
        log(f"  טוענת {len(extras)} סקציות מ-communities_data.json")
        existing_slugs = {s["slug"] for s in db.get_active_sections(CITY_SLUG)}
        for sec in extras:
            if sec["slug"] in existing_slugs:
                continue
            cid = fetch_section_cid(session, sec["slug"])
            if cid:
                db.upsert_section(sec["slug"], sec["name"], cid, CITY_SLUG)
                log(f"  מרחב נוסף: {sec['name']} ({sec['slug']}, cid={cid})")
                _admin_alert(f"🆕 סקציה חדשה התווספה לסריקה: <b>{sec['name']}</b> ({sec['slug']})")
            else:
                log(f"  לא נמצא cid עבור {sec['slug']} — מדלג")

    # Try to discover new sections from coing.co's homepage (limited — most sections
    # are JS-rendered and won't appear here, but it catches the easy ones).
    discovered = discover_sections(session)
    for sec in discovered:
        existing = db.get_active_sections(CITY_SLUG)
        existing_slugs = {s["slug"] for s in existing}
        if sec["slug"] not in existing_slugs:
            cid = fetch_section_cid(session, sec["slug"])
            if cid:
                db.upsert_section(sec["slug"], sec["name"], cid, CITY_SLUG)
                log(f"  מרחב חדש נמצא: {sec['name']} ({sec['slug']}, cid={cid})")
                _admin_alert(f"🆕 סקציה חדשה התגלתה: <b>{sec['name']}</b> ({sec['slug']})")

    # Auto-cleanup: mark past events
    today_iso = datetime.date.today().strftime("%Y-%m-%d")
    cleanup_conn = db.get_db()
    cleaned = cleanup_conn.execute(
        "UPDATE events SET is_past=1 WHERE is_past=0 AND event_date_iso < ? AND event_date_iso IS NOT NULL",
        (today_iso,)).rowcount
    cleanup_conn.commit()
    cleanup_conn.close()
    # No-date entries: keep visible — they are ongoing/permanent activities
    # Only mark as past if they were explicitly marked "אירוע שחלף" on coing
    if cleaned:
        log(f"  ניקוי: {cleaned} אירועים ישנים סומנו כ-past")

    # Scrape each active section
    sections = db.get_active_sections(CITY_SLUG)
    log(f"סורק {len(sections)} מרחבים")

    total_events = 0
    total_available = 0
    failed_sections = []
    empty_sections = []

    for section in sections:
        if section["cid"] == 0:
            continue

        try:
            items = scrape_section(session, section)
        except Exception as e:
            log(f"  ❌ קריסה בסריקת {section['slug']}: {e}")
            failed_sections.append((section["slug"], str(e)[:200]))
            continue

        if not items:
            empty_sections.append(section["slug"])

        # Parse all events from list
        parsed_events = []
        for html_item in items:
            ev = parse_event(html_item)
            if ev["event_id"] and not ev["is_past"]:
                parsed_events.append(ev)

        # Skip events that were already enriched recently with complete data
        all_ids = [ev["event_id"] for ev in parsed_events if ev.get("event_id")]
        fresh_ids = db.get_fresh_enriched_ids(all_ids, max_age_hours=6)
        # Also skip events we tried to enrich in the last 30 min (even if incomplete)
        # — their source page simply lacks the data, retrying is wasteful.
        recent_ids = db.get_recently_enriched_ids(all_ids, max_age_hours=0.5)
        skip_ids = fresh_ids | recent_ids

        # Enrich events with individual page data (batch to avoid DB lock)
        enriched = 0
        skipped = 0
        enriched_ids = []
        for ev in parsed_events:
            if enriched >= 30:  # Max 30 per section — prevents long DB locks
                break
            if ev["event_id"] in skip_ids:
                skipped += 1
                continue
            if ev["link"]:
                extra = enrich_event(session, ev["event_id"], ev["link"])
                if extra:
                    ev.update({k: v for k, v in extra.items() if v is not None})
                    enriched += 1
                    enriched_ids.append(ev["event_id"])
                    time.sleep(1)  # courtesy delay

        log(f"  העשרה: {enriched} אירועים חדשים, {skipped} דולגו (טריים)")

        for ev in parsed_events:
            db.upsert_event(
                event_id=ev["event_id"],
                section_id=section["id"],
                title=ev["title"],
                event_date=ev.get("event_date") or ev["date"],
                registered=ev.get("registered", 0),
                capacity=ev.get("capacity", 0),
                is_full=ev.get("is_full", False),
                is_past=ev.get("is_past", False),
                link=ev["link"],
                raw_text=ev["text"],
                neighborhood=ev["neighborhood"],
                age_group=ev["age_group"],
                event_time=ev.get("event_time"),
                end_time=ev.get("end_time"),
                location=ev["location"],
                image_url=ev.get("image_url"),
            )

            total_events += 1
            if not ev.get("is_full") and not ev.get("is_past"):
                total_available += 1

        # Mark enriched timestamps after upsert so new events are updated too
        for eid in enriched_ids:
            try:
                db.mark_enriched(eid)
            except Exception:
                pass

        db.mark_section_scraped(section["id"])
        time.sleep(2)  # courtesy delay between sections

    stats = db.get_stats()
    log(f"סיום: {total_events} אירועים נסרקו, {total_available} עם מקום פנוי")
    log(f"סה\"כ ב-DB: {stats['events_total']} אירועים, {stats['users']} משתמשים")

    # Health alert: only notify admin on REAL failures (a section threw an
    # exception during scraping). Two checks that proved noisy were removed:
    #   - "empty section" → many sections legitimately have 0 events for days
    #     (e.g. PLUSI_Hagim outside holiday season); they spammed the admin
    #     every 2 minutes.
    #   - "sharp drop vs yesterday" → today's `total_events` is the per-run
    #     scrape counter, while the daily snapshot in stats history is the
    #     DB total — incompatible comparison fired false positives every cycle.
    # If silent dropout becomes a concern again, prefer a once-a-day digest
    # over an every-cycle alert.
    if failed_sections:
        _admin_alert(
            "🩺 <b>כשלי סריקה</b>\n\n" +
            "\n".join(f"• <b>{s}</b>: {err}" for s, err in failed_sections)
        )

    # Enrich events missing capacity/location/title/image (ones that weren't enriched before)
    # Skip events we tried in the last 2h — if source has no data, retrying is wasteful.
    # Restrict to coing.co links: external links (Zoom, external forms) have og:title
    # and og:image that describe the *platform*, not the event — enriching them
    # silently overwrites curated titles and images.
    try:
        conn = db.get_db()
        missing = conn.execute("""
            SELECT event_id, title, link FROM events
            WHERE is_past=0 AND link IS NOT NULL
              AND link LIKE 'https://www.coing.co/%'
              AND (capacity=0 OR location IS NULL OR length(title) > 45 OR image_url IS NULL OR image_url = '')
              AND (last_enriched IS NULL OR datetime(last_enriched) < datetime('now','localtime','-2 hours'))
            ORDER BY event_date_iso LIMIT 15
        """).fetchall()
        if missing:
            log(f"  השלמת נתונים: {len(missing)} אירועים חסרי מכסה/מיקום/תמונה")
            for row in missing:
                extra = enrich_event(session, row["event_id"], row["link"])
                if extra:
                    updates = []
                    params = []
                    if extra.get("registered") is not None:
                        updates.append("registered=?"); params.append(extra["registered"])
                    if extra.get("capacity") is not None and extra["capacity"] > 0:
                        updates.append("capacity=?"); params.append(extra["capacity"])
                        updates.append("is_full=?"); params.append(1 if extra.get("is_full") else 0)
                    if extra.get("location"):
                        updates.append("location=?"); params.append(extra["location"])
                    if extra.get("image_url"):
                        updates.append("image_url=?"); params.append(extra["image_url"])
                    if extra.get("title"):
                        updates.append("title=?"); params.append(extra["title"])
                    if updates:
                        params.append(row["event_id"])
                        conn.execute(f"UPDATE events SET {','.join(updates)} WHERE event_id=?", params)
                # Always stamp last_enriched — even if no new data found — so we
                # don't retry the same dry source every run.
                conn.execute(
                    "UPDATE events SET last_enriched=datetime('now','localtime') WHERE event_id=?",
                    (row["event_id"],)
                )
                time.sleep(1)
            conn.commit()
        conn.close()
    except Exception as e:
        log(f"  שגיאת השלמת נתונים: {e}")

    # Integrity check: verify titles against og:title from coing.co.
    # IMPORTANT: only run this for coing.co links. External links (Zoom, Meet,
    # external registration forms) have their own og:title that has nothing to
    # do with the event ("Join our Cloud HD Video Meeting", "Google Meet — Use a
    # secure business meeting platform", etc) and would silently overwrite
    # human-curated titles for any manually-added event.
    try:
        import random
        conn = db.get_db()
        sample = conn.execute(
            "SELECT event_id, title, link FROM events "
            "WHERE is_past=0 AND link IS NOT NULL AND link LIKE 'https://www.coing.co/%' "
            "ORDER BY RANDOM() LIMIT 2"
        ).fetchall()
        for row in sample:
            try:
                resp = session.get(row["link"], headers={"User-Agent": UA}, timeout=10)
                soup = BeautifulSoup(resp.text, "html.parser")
                og = soup.find("meta", property="og:title")
                if og and og.get("content"):
                    real_title = og["content"].strip()
                    skip = ["בת ים", "פעילויות הפגה", "כל מה שקורה", "תרבות ופנאי", "רובע"]
                    if real_title and len(real_title) > 5 and not any(real_title.startswith(s) for s in skip):
                        if real_title != row["title"]:
                            conn.execute("UPDATE events SET title=? WHERE event_id=?", (real_title, row["event_id"]))
                            log(f"  תיקון כותרת: {row['event_id']} -> {real_title[:40]}")
            except:
                pass
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"  שגיאת integrity check: {e}")

    # Auto-update preview_data.js for the website
    try:
        today = datetime.date.today().strftime("%Y-%m-%d")
        conn = db.get_db()
        events = [dict(r) for r in conn.execute("""
            SELECT e.*, s.name as section_name FROM events e
            LEFT JOIN sections s ON e.section_id = s.id
            WHERE e.is_past = 0 AND (e.event_date_iso >= ? OR e.event_date_iso IS NULL)
            ORDER BY CASE WHEN e.event_date_iso IS NULL THEN 1 ELSE 0 END,
                     e.event_date_iso, e.event_time
        """, (today,)).fetchall()]
        locations = sorted(set(e["location"] for e in events if e.get("location")))
        conn.close()

        data = {"events": events, "stats": stats, "today": today, "filters": {"locations": locations}}
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        # Railway: write to /data/preview_data.js (served via Flask /preview_data.js endpoint)
        # SG legacy: ../public_html/batyam/preview_data.js
        # Local dev: same directory as scripts
        _data_dir = os.environ.get("BATYAM_DATA_DIR") or os.path.dirname(os.environ.get("BATYAM_DB_PATH", ""))
        preview_paths = []
        if _data_dir and os.path.isdir(_data_dir):
            preview_paths.append(os.path.join(_data_dir, "preview_data.js"))
        preview_paths.extend([
            os.path.join(os.path.dirname(_script_dir), "public_html", "batyam", "preview_data.js"),
            os.path.join(_script_dir, "preview_data.js"),
        ])
        written = False
        for preview_path in preview_paths:
            try:
                with open(preview_path, "w", encoding="utf-8") as f:
                    f.write(f"const DATA = {json.dumps(data, ensure_ascii=False)};")
                log(f"preview_data.js עודכן: {len(events)} אירועים ({preview_path})")
                written = True
                break
            except FileNotFoundError:
                continue
        if not written:
            log("שגיאה: לא נמצא נתיב לכתיבת preview_data.js")
    except Exception as e:
        log(f"שגיאה בעדכון preview_data.js: {e}")

    # Run dispatcher after scraping (saves a separate cron job)
    try:
        import batyam_dispatcher
        batyam_dispatcher.dispatch()
        log("שיגור התראות — הושלם")
    except Exception as e:
        log(f"שגיאה בשיגור התראות: {e}")

    # Dashboard data — only once per hour (not every run)
    try:
        import generate_dashboard_data
        dash_flag = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".dash_last")
        should_gen = True
        if os.path.exists(dash_flag):
            age = time.time() - os.path.getmtime(dash_flag)
            if age < 3600:  # less than 1 hour
                should_gen = False
        if should_gen:
            generate_dashboard_data.main()
            with open(dash_flag, "w") as f:
                f.write("")
    except Exception as e:
        log(f"שגיאה בעדכון dashboard: {e}")

    # On SG only: push DB to Railway and pull user data back.
    # On Railway itself, the SYNC_URL env var is unset → both are no-ops.
    try:
        push_db_to_railway()
    except Exception as e:
        log(f"שגיאה בסנכרון ל-Railway: {e}")

    try:
        pull_users_from_railway()
    except Exception as e:
        log(f"שגיאה במשיכת משתמשים מ-Railway: {e}")

    log("=" * 50)


def push_db_to_railway():
    """Snapshot the live DB and POST it to the Railway /sync_db endpoint.

    Uses sqlite3.Connection.backup() for a consistent read regardless of WAL state.
    """
    secrets = {}
    secrets_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "batyam_secrets.json")
    if os.path.exists(secrets_path):
        with open(secrets_path, "r", encoding="utf-8") as f:
            secrets = json.load(f)
    sync_url = secrets.get("SYNC_URL") or os.environ.get("SYNC_URL")
    sync_secret = secrets.get("SYNC_SECRET") or os.environ.get("SYNC_SECRET")
    if not sync_url or not sync_secret:
        return

    import sqlite3 as _sql
    snap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sync_snapshot.db")
    try:
        src = _sql.connect(db.DB_PATH)
        dst = _sql.connect(snap_path)
        src.backup(dst)
        src.close()
        dst.close()
        with open(snap_path, "rb") as f:
            body = f.read()
        resp = requests.post(
            sync_url,
            data=body,
            headers={
                "X-Sync-Secret": sync_secret,
                "Content-Type": "application/octet-stream",
            },
            timeout=30,
        )
        if resp.status_code == 200:
            log(f"סנכרון ל-Railway הצליח: {resp.text[:120]}")
        else:
            log(f"סנכרון ל-Railway נכשל: HTTP {resp.status_code} — {resp.text[:200]}")
    finally:
        try:
            os.unlink(snap_path)
        except OSError:
            pass


def _load_sync_secrets():
    """Return (sync_base_url_no_path, sync_secret) or (None, None) if unconfigured.

    sync_base_url is derived from SYNC_URL by stripping the /sync_db suffix so
    we can build sibling endpoints like /pull_users from the same value.
    """
    secrets = {}
    secrets_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "batyam_secrets.json")
    if os.path.exists(secrets_path):
        with open(secrets_path, "r", encoding="utf-8") as f:
            secrets = json.load(f)
    sync_url = secrets.get("SYNC_URL") or os.environ.get("SYNC_URL")
    sync_secret = secrets.get("SYNC_SECRET") or os.environ.get("SYNC_SECRET")
    if not sync_url or not sync_secret:
        return None, None
    base = sync_url.rsplit("/", 1)[0]
    return base, sync_secret


def pull_users_from_railway():
    """Fetch users + user_preferences from Railway and merge into the SG DB.

    Railway is the authoritative source for these tables (the bot writes
    there when users /start or /track). This function makes the SG copy
    catch up so the daily digest, which reads from SG, reaches everyone.
    """
    base, sync_secret = _load_sync_secrets()
    if not base:
        return

    pull_url = base + "/pull_users"
    resp = requests.get(
        pull_url,
        headers={"X-Sync-Secret": sync_secret, "Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code != 200:
        log(f"משיכת משתמשים נכשלה: HTTP {resp.status_code} — {resp.text[:200]}")
        return
    data = resp.json()
    if not data.get("ok"):
        log(f"משיכת משתמשים נכשלה: {data.get('error', 'unknown')}")
        return

    users = data.get("users", [])
    prefs = data.get("user_preferences", [])

    import sqlite3 as _sql
    conn = _sql.connect(db.DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        # FK off so we can safely DELETE+INSERT user_preferences (FK to users.id);
        # the inserts respect the same ids so referential integrity is restored.
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")

        # Upsert users by id. Build the INSERT OR REPLACE dynamically off the
        # actual table schema so we tolerate columns that exist on one side only.
        sg_user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        u_count = 0
        for u in users:
            common = [c for c in u.keys() if c in sg_user_cols]
            if not common:
                continue
            placeholders = ",".join(["?"] * len(common))
            cols = ",".join(common)
            conn.execute(
                f"INSERT OR REPLACE INTO users ({cols}) VALUES ({placeholders})",
                [u[c] for c in common],
            )
            u_count += 1

        # Replace user_preferences entirely. Railway is authoritative.
        conn.execute("DELETE FROM user_preferences")
        sg_pref_cols = {r[1] for r in conn.execute("PRAGMA table_info(user_preferences)").fetchall()}
        p_count = 0
        for p in prefs:
            common = [c for c in p.keys() if c in sg_pref_cols]
            if not common:
                continue
            placeholders = ",".join(["?"] * len(common))
            cols = ",".join(common)
            conn.execute(
                f"INSERT INTO user_preferences ({cols}) VALUES ({placeholders})",
                [p[c] for c in common],
            )
            p_count += 1

        conn.execute("COMMIT")
        log(f"משיכת משתמשים מ-Railway: {u_count} משתמשים + {p_count} העדפות עודכנו")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
