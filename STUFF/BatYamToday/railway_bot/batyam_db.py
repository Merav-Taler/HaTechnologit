"""
שכבת מסד נתונים — BatYam Today
SQLite database layer for the community activity tracking platform.
"""

import sqlite3
import os
import re
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

IL_TZ = ZoneInfo("Asia/Jerusalem")

def _today_il():
    """Get today's date in Israel timezone."""
    return datetime.now(IL_TZ).date()

DB_PATH = os.environ.get("BATYAM_DB_PATH", os.path.join(os.path.dirname(__file__), "batyam_data.db"))


def normalize_text(text):
    """Normalize text for keyword matching — remove quotes, geresh, etc."""
    import re
    text = text.lower()
    # Remove Hebrew geresh/gershayim and common quote marks
    text = re.sub(r"['\u0027\u2018\u2019\u0060\u00B4\u05F3\u05F4\"״׳]", "", text)
    return text


# מילות מעקב נפוצות הן קטגוריות ("מוזיקה", "ספורט") — אבל טקסט אירוע כמעט אף פעם
# לא מכיל את מילת הקטגוריה עצמה ("LIVE ON THE BEACH עם נועה קירל" לא מכיל "מוזיקה").
# לכן כל מילת מעקב מורחבת לרשימת מילים נרדפות. באג אמיתי מיולי 2026: תושבת עם
# מעקבים מוזיקה/תרבות/ספורט לא קיבלה התראה על אירועי המאה והמונדיאל.
# המפתחות והערכים מושווים אחרי normalize_text (בלי גרשיים, lowercase).
KEYWORD_SYNONYMS = {
    "מוזיקה": ["מוסיקה", "מוזיקלי", "מופע", "הופעה", "קונצרט", "זמר", "זמרת", "להקה",
                "פסטיבל", "שירה בציבור", "ערב שירה", "live", "לייב", "דיגיי", "תקליטן",
                "אמפי", "מארח את", "על הבמה"],
    "ספורט": ["כדורגל", "כדורסל", "מונדיאל", "ריצה", "יוגה", "זומבה", "פילאטיס",
               "התעמלות", "כושר", "אופניים", "שחייה", "טניס", "גודו", "קרטה",
               "ספורטיבי", "ספורטיבית", "מרוץ", "צעדה"],
    "תרבות": ["הצגה", "תיאטרון", "סרט", "מופע", "מוזיאון", "פסטיבל", "טקס",
               "סטנדאפ", "קולנוע", "תערוכה", "ערב שירה", "הרצאה"],
    "ילדים": ["לילדים", "ילדי", "משפחות", "משפחתי", "גימבורי", "גמבורי",
               "בובות", "פעוטות", "תינוקות", "הורים וילדים", "כיתות"],
    "קהילה": ["קהילתי", "קהילתית", "שכונות", "שכונתי", "תושבים", "מפגש",
               "התנדבות", "מתנדבים", "חגיגות"],
    "יצירה": ["סדנת", "סדנה", "סדנאות", "אמנות", "אומנות", "ציור", "פיסול",
               "קרמיקה", "מלאכה", "יצירתי"],
    "הפגה": ["הפוגה", "מקלט", "מקלטים"],
    "ריקוד": ["מחול", "היפ הופ", "בלט", "רקדנים"],
    "הרצאות": ["הרצאה", "העשרה", "קורס"],
}


# כתיבים וניסוחים שונים לאותה קטגוריה — "מוסיקה" חייבת להתנהג כמו "מוזיקה".
KEYWORD_ALIASES = {
    "מוסיקה": "מוזיקה", "הופעות": "מוזיקה", "הופעה": "מוזיקה",
    "זמרים": "מוזיקה", "זמר": "מוזיקה", "קונצרט": "מוזיקה", "מופעים": "מוזיקה",
    "הצגות": "תרבות", "תיאטרון": "תרבות",
    "סדנאות": "יצירה", "סדנה": "יצירה", "סדנת": "יצירה",
    "ריקודים": "ריקוד", "מחול": "ריקוד",
    "הרצאה": "הרצאות",
    "מקלטים": "הפגה", "מקלט": "הפגה",
}


def keyword_terms(keyword):
    """All normalized search terms for a tracker keyword (the word + synonyms).

    Aliases first ("מוסיקה"→"מוזיקה"), then synonym expansion. The original
    word is always included so nothing gets narrower than a literal match.
    """
    kw = normalize_text(keyword).strip()
    canon = KEYWORD_ALIASES.get(kw, kw)
    terms = [kw]
    if canon != kw:
        terms.append(canon)
    terms += [normalize_text(t) for t in KEYWORD_SYNONYMS.get(canon, [])]
    return terms


def event_matches_keyword(keyword, event):
    """One tracker keyword vs one event — the single source of truth for matching.
    Used by the dispatcher (notifications), /list, and get_users_for_event, so
    counts shown to users always agree with what actually gets sent.
    Handles: 'רוסית', 'גיל X-Y' / 'גיל X+', and synonym-expanded text matching."""
    kw = normalize_text(keyword).strip()
    raw = (event.get("raw_text") or "") + " " + (event.get("title") or "")

    if kw == "רוסית":
        return bool(re.search(r'[Ѐ-ӿ]', raw))

    age_range = re.match(r'^גיל\s*(\d+)\s*[-–]\s*(\d+)$', kw)
    age_plus = re.match(r'^גיל\s*(\d+)\s*\+$', kw)
    if age_range or age_plus:
        event_age = event.get("age_group") or ""
        if not event_age:
            return False
        ev_range = re.match(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)', event_age)
        ev_plus = re.match(r'(\d+(?:\.\d+)?)\s*\+', event_age)
        if age_range:
            u_lo, u_hi = int(age_range.group(1)), int(age_range.group(2))
            if ev_range:
                return float(ev_range.group(1)) <= u_hi and u_lo <= float(ev_range.group(2))
            if ev_plus:
                return u_hi >= float(ev_plus.group(1))
            return False
        u_lo = int(age_plus.group(1))
        if ev_range:
            return u_lo <= float(ev_range.group(2))
        return bool(ev_plus)

    text = normalize_text(raw)
    return any(t in text for t in keyword_terms(kw))


def get_db():
    """Get a database connection with WAL mode for better concurrency."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        -- מרחבים/קטגוריות באתר coing
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,          -- e.g. 'BatYam_shelters'
            name TEXT NOT NULL,                 -- e.g. 'פעילויות הפגה במקלטים'
            cid INTEGER NOT NULL,               -- community ID on coing.co
            city TEXT NOT NULL DEFAULT 'batya',  -- city slug
            active INTEGER NOT NULL DEFAULT 1,
            last_scraped TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        -- Manual events section (for /add command)
        INSERT OR IGNORE INTO sections (slug, name, cid, city, active)
        VALUES ('manual', 'אירועים ידניים', 0, 'batya', 1);

        -- אירועים/פעילויות
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,       -- coing event ID (from URL)
            section_id INTEGER REFERENCES sections(id),
            title TEXT NOT NULL,
            event_date TEXT,                     -- DD/MM/YYYY
            event_date_iso TEXT,                 -- YYYY-MM-DD for sorting
            registered INTEGER DEFAULT 0,
            capacity INTEGER DEFAULT 0,
            is_full INTEGER DEFAULT 0,
            is_past INTEGER DEFAULT 0,
            link TEXT,
            raw_text TEXT,                       -- full text for keyword search
            neighborhood TEXT,                   -- שכונה
            age_group TEXT,                      -- קבוצת גיל
            event_time TEXT,                     -- HH:MM start
            end_time TEXT,                       -- HH:MM end
            location TEXT,                       -- מיקום (מתנ"ס, בי"ס וכו')
            image_url TEXT                       -- תמונת האירוע
            first_seen TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            last_checked TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        -- משתמשים
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            name TEXT,
            neighborhood TEXT,                   -- שכונה מועדפת
            active INTEGER NOT NULL DEFAULT 1,
            notify_digest INTEGER NOT NULL DEFAULT 1,   -- קבלת דייג'סט יומי
            notify_instant INTEGER NOT NULL DEFAULT 1,  -- קבלת התראות מיידיות
            quiet_start TEXT DEFAULT '22:00',    -- שעות שקט — התחלה
            quiet_end TEXT DEFAULT '07:00',      -- שעות שקט — סוף
            registered_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            last_active TEXT
        );

        -- העדפות מעקב של משתמשים
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            keyword TEXT NOT NULL,               -- מילת חיפוש
            section_id INTEGER REFERENCES sections(id),  -- NULL = כל המרחבים
            neighborhood TEXT,                   -- NULL = כל השכונות
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, keyword)
        );

        -- לוג התראות שנשלחו
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_id TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'telegram',  -- telegram / email
            sent_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        -- אירועים שהמשתמש אישר שנרשם אליהם
        CREATE TABLE IF NOT EXISTS confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_id TEXT NOT NULL,
            confirmed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, event_id)
        );

        -- סטטיסטיקות יומיות
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            users_active INTEGER DEFAULT 0,
            users_total INTEGER DEFAULT 0,
            users_new INTEGER DEFAULT 0,
            events_total INTEGER DEFAULT 0,
            events_available INTEGER DEFAULT 0,
            notifications_sent INTEGER DEFAULT 0,
            preferences_total INTEGER DEFAULT 0,
            top_keywords TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        -- אינדקסים
        CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date_iso);
        CREATE INDEX IF NOT EXISTS idx_events_section ON events(section_id);
        CREATE INDEX IF NOT EXISTS idx_events_full ON events(is_full, is_past);
        CREATE INDEX IF NOT EXISTS idx_notifications_user_event ON notifications(user_id, event_id);
        CREATE INDEX IF NOT EXISTS idx_preferences_user ON user_preferences(user_id);
        CREATE INDEX IF NOT EXISTS idx_confirmations_user ON confirmations(user_id, event_id);
    """)
    # Migrations — add columns that may not exist yet
    # Migrations — events table
    for col, defn in [
        ("was_full", "INTEGER DEFAULT 0"),
        ("last_enriched", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} {defn}")
        except:
            pass
    # Migrations — users table
    for col, defn in [("notify_reminder", "INTEGER DEFAULT 1")]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
        except:
            pass
    # Migrations — sections table
    for col, defn in [("last_hidden_scan", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE sections ADD COLUMN {col} {defn}")
        except:
            pass
    conn.commit()
    conn.close()


# ===== SECTIONS =====

def upsert_section(slug, name, cid, city="batya"):
    conn = get_db()
    conn.execute("""
        INSERT INTO sections (slug, name, cid, city) VALUES (?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET name=excluded.name, cid=excluded.cid
    """, (slug, name, cid, city))
    conn.commit()
    section_id = conn.execute("SELECT id FROM sections WHERE slug=?", (slug,)).fetchone()["id"]
    conn.close()
    return section_id


def get_active_sections(city="batya"):
    conn = get_db()
    rows = conn.execute("SELECT * FROM sections WHERE active=1 AND city=? ORDER BY name", (city,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_section_scraped(section_id):
    conn = get_db()
    conn.execute("UPDATE sections SET last_scraped=datetime('now','localtime') WHERE id=?", (section_id,))
    conn.commit()
    conn.close()


def should_scan_hidden(slug, max_age_hours=24):
    """Return True if section hasn't been scanned for hidden events within max_age_hours."""
    conn = get_db()
    row = conn.execute(
        "SELECT last_hidden_scan FROM sections WHERE slug=?", (slug,)
    ).fetchone()
    if not row or row["last_hidden_scan"] is None:
        conn.close()
        return True
    stale = conn.execute(
        "SELECT datetime(?) < datetime('now','localtime',?)",
        (row["last_hidden_scan"], f"-{max_age_hours} hours")
    ).fetchone()[0]
    conn.close()
    return bool(stale)


def mark_hidden_scanned(slug):
    conn = get_db()
    conn.execute("UPDATE sections SET last_hidden_scan=datetime('now','localtime') WHERE slug=?", (slug,))
    conn.commit()
    conn.close()


# ===== EVENTS =====

def parse_date_to_iso(date_str):
    """Convert DD/MM/YYYY to YYYY-MM-DD."""
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    except:
        pass
    return None


def mark_enriched(event_id):
    """Record that an event was successfully enriched from its detail page."""
    conn = get_db()
    conn.execute("UPDATE events SET last_enriched=datetime('now','localtime') WHERE event_id=?", (event_id,))
    conn.commit()
    conn.close()


def get_fresh_enriched_ids(event_ids, max_age_hours=6):
    """Return the subset of event_ids that were enriched recently and have complete data."""
    if not event_ids:
        return set()
    conn = get_db()
    placeholders = ",".join("?" * len(event_ids))
    rows = conn.execute(f"""
        SELECT event_id FROM events
        WHERE event_id IN ({placeholders})
          AND capacity > 0
          AND image_url IS NOT NULL AND image_url != ''
          AND location IS NOT NULL AND location != ''
          AND last_enriched IS NOT NULL
          AND datetime(last_enriched) > datetime('now','localtime',?)
    """, list(event_ids) + [f"-{max_age_hours} hours"]).fetchall()
    conn.close()
    return {r["event_id"] for r in rows}


def get_recently_enriched_ids(event_ids, max_age_hours=2):
    """Return event_ids enriched within the last X hours regardless of data quality.
    Used to skip retrying enrichment of events whose source simply lacks data."""
    if not event_ids:
        return set()
    conn = get_db()
    placeholders = ",".join("?" * len(event_ids))
    rows = conn.execute(f"""
        SELECT event_id FROM events
        WHERE event_id IN ({placeholders})
          AND last_enriched IS NOT NULL
          AND datetime(last_enriched) > datetime('now','localtime',?)
    """, list(event_ids) + [f"-{max_age_hours} hours"]).fetchall()
    conn.close()
    return {r["event_id"] for r in rows}


def upsert_event(event_id, section_id, title, event_date, registered, capacity,
                 is_full, is_past, link, raw_text="", neighborhood=None, age_group=None,
                 event_time=None, end_time=None, location=None, image_url=None):
    conn = get_db()
    event_date_iso = parse_date_to_iso(event_date) if event_date else None
    conn.execute("""
        INSERT INTO events (event_id, section_id, title, event_date, event_date_iso,
                           registered, capacity, is_full, is_past, link, raw_text,
                           neighborhood, age_group, event_time, end_time, location, image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            title=CASE WHEN length(events.title) <= 45 AND events.title IS NOT NULL THEN events.title ELSE excluded.title END,
            -- registered / capacity / is_full come from the enrichment step,
            -- which only fires every few hours. The plain API parse always
            -- carries capacity=0 ("we don't know"). Keep the previously
            -- enriched value when the new payload has no real number.
            registered=CASE WHEN excluded.capacity > 0 THEN excluded.registered ELSE events.registered END,
            capacity=CASE WHEN excluded.capacity > 0 THEN excluded.capacity ELSE events.capacity END,
            was_full=CASE
                WHEN events.is_full=1 AND excluded.capacity > 0 AND excluded.is_full=0 THEN 1
                ELSE events.was_full END,
            is_full=CASE
                WHEN excluded.is_full=1 THEN 1                                 -- new payload says full → trust it
                WHEN excluded.capacity > 0 THEN excluded.is_full               -- new payload has real numbers → trust them
                ELSE events.is_full END,                                       -- otherwise keep previous
            is_past=excluded.is_past,
            raw_text=excluded.raw_text,
            event_date=COALESCE(NULLIF(excluded.event_date, ''), events.event_date),
            event_date_iso=COALESCE(NULLIF(excluded.event_date_iso, ''), events.event_date_iso),
            event_time=COALESCE(NULLIF(excluded.event_time, ''), events.event_time),
            end_time=COALESCE(NULLIF(excluded.end_time, ''), events.end_time),
            location=COALESCE(NULLIF(excluded.location, ''), events.location),
            image_url=COALESCE(NULLIF(excluded.image_url, ''), events.image_url),
            -- age_group ו-neighborhood — תמיד נסונכרן מהזיהוי החדש (גם אל NULL).
            -- זה קריטי: אם הזיהוי הישן ייצר תיוג שגוי (למשל "0-1" מהמילה "תינוקות")
            -- והקוד החדש זיהה שאין גיל מפורש בטקסט, חייבים לנקות את הערך הישן
            -- כדי שלא יוצג מידע שגוי למשתמשים. אירועים ידניים (admin /add) לא
            -- מושפעים — הסקרייפר לא נוגע בסקציית 'manual'.
            age_group=excluded.age_group,
            neighborhood=COALESCE(excluded.neighborhood, events.neighborhood),
            last_checked=datetime('now','localtime')
    """, (event_id, section_id, title, event_date, event_date_iso,
          registered, capacity, is_full, is_past, link, raw_text,
          neighborhood, age_group, event_time, end_time, location, image_url))
    conn.commit()
    conn.close()


def clear_was_full(event_id):
    """Reset was_full flag after sending spot-opened alert."""
    conn = get_db()
    conn.execute("UPDATE events SET was_full=0 WHERE event_id=?", (event_id,))
    conn.commit()
    conn.close()


def get_available_events(section_id=None):
    """Get events with available space (not full, not past, today or future only)."""
    conn = get_db()
    today_iso = _today_il().strftime("%Y-%m-%d")
    sql = "SELECT * FROM events WHERE is_full=0 AND is_past=0 AND (event_date_iso >= ? OR event_date_iso IS NULL)"
    params = [today_iso]
    if section_id:
        sql += " AND section_id=?"
        params.append(section_id)
    sql += " ORDER BY event_date_iso"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_today_events():
    """Get all events happening today."""
    today_iso = _today_il().strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute("""
        SELECT e.*, s.name as section_name, s.slug as section_slug
        FROM events e
        LEFT JOIN sections s ON e.section_id = s.id
        WHERE e.event_date_iso = ? AND e.is_past = 0
        ORDER BY e.title
    """, (today_iso,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_upcoming_events(days=7):
    """Get events in the next N days."""
    today_iso = _today_il().strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute("""
        SELECT e.*, s.name as section_name, s.slug as section_slug
        FROM events e
        LEFT JOIN sections s ON e.section_id = s.id
        WHERE e.event_date_iso >= ? AND e.is_past = 0
        ORDER BY e.event_date_iso, e.title
    """, (today_iso,)).fetchall()
    conn.close()
    # Filter to N days
    max_date = (_today_il() + timedelta(days=days)).strftime("%Y-%m-%d")
    return [dict(r) for r in rows if r["event_date_iso"] and r["event_date_iso"] <= max_date]


# ===== USERS =====

def get_or_create_user(telegram_chat_id, name=None):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE telegram_chat_id=?", (str(telegram_chat_id),)).fetchone()
    if row:
        conn.execute("UPDATE users SET last_active=datetime('now','localtime') WHERE id=?", (row["id"],))
        conn.commit()
        conn.close()
        return dict(row)
    conn.execute("INSERT INTO users (telegram_chat_id, name) VALUES (?, ?)", (str(telegram_chat_id), name))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE telegram_chat_id=?", (str(telegram_chat_id),)).fetchone()
    conn.close()
    return dict(row)


def get_user(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_active_users():
    conn = get_db()
    rows = conn.execute("SELECT * FROM users WHERE active=1").fetchall()
    conn.close()
    return [dict(r) for r in rows]


ALLOWED_USER_FIELDS = {"neighborhood", "quiet_start", "quiet_end", "notify_digest",
                        "notify_instant", "active", "name", "last_active"}

def update_user(user_id, **kwargs):
    conn = get_db()
    for key, value in kwargs.items():
        if key not in ALLOWED_USER_FIELDS:
            continue
        conn.execute(f"UPDATE users SET {key}=? WHERE id=?", (value, user_id))
    conn.commit()
    conn.close()


def get_user_count():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
    conn.close()
    return count


# ===== PREFERENCES =====

def add_preference(user_id, keyword, section_id=None, neighborhood=None):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO user_preferences (user_id, keyword, section_id, neighborhood)
            VALUES (?, ?, ?, ?)
        """, (user_id, keyword, section_id, neighborhood))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False  # already exists


def remove_preference(user_id, keyword):
    conn = get_db()
    conn.execute("DELETE FROM user_preferences WHERE user_id=? AND keyword=?", (user_id, keyword))
    conn.commit()
    conn.close()


def remove_preference_by_id(user_id, pref_id):
    """Delete a preference by its id, only if it belongs to user_id. Returns the keyword removed (or None)."""
    conn = get_db()
    row = conn.execute(
        "SELECT keyword FROM user_preferences WHERE id=? AND user_id=?",
        (pref_id, user_id),
    ).fetchone()
    if row:
        conn.execute("DELETE FROM user_preferences WHERE id=? AND user_id=?", (pref_id, user_id))
        conn.commit()
    conn.close()
    return row["keyword"] if row else None


def get_user_preferences(user_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT up.*, s.name as section_name
        FROM user_preferences up
        LEFT JOIN sections s ON up.section_id = s.id
        WHERE up.user_id=? AND up.active=1
    """, (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_users_for_event(event):
    """Find all users whose preferences match a given event."""
    conn = get_db()
    rows = conn.execute("""
        SELECT DISTINCT u.*
        FROM users u
        JOIN user_preferences up ON u.id = up.user_id
        WHERE u.active=1 AND up.active=1 AND u.notify_instant=1
    """).fetchall()
    conn.close()

    matched_users = []

    for user in rows:
        user_prefs = get_user_preferences(user["id"])
        for pref in user_prefs:
            # Shared matcher — synonyms, רוסית, and age-range overlap all live there
            if not event_matches_keyword(pref["keyword"], event):
                continue
            # Section filter
            if pref["section_id"] and pref["section_id"] != event.get("section_id"):
                continue
            # Neighborhood filter
            if pref["neighborhood"] and event.get("neighborhood") and \
               pref["neighborhood"] not in event["neighborhood"]:
                continue
            matched_users.append(dict(user))
            break  # one match is enough per user

    return matched_users


# ===== NOTIFICATIONS =====

def was_notified(user_id, event_id):
    """Check if user was already notified about this event."""
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM notifications
        WHERE user_id=? AND event_id=?
    """, (user_id, event_id)).fetchone()
    conn.close()
    return row is not None


def log_notification(user_id, event_id, channel="telegram"):
    conn = get_db()
    conn.execute("""
        INSERT INTO notifications (user_id, event_id, channel) VALUES (?, ?, ?)
    """, (user_id, event_id, channel))
    conn.commit()
    conn.close()


# ===== SETTINGS HELPERS =====

TOGGLEABLE_FIELDS = {"notify_digest", "notify_instant", "notify_reminder", "active"}

def toggle_user_setting(user_id, field):
    """Toggle a boolean user setting. Returns new value."""
    if field not in TOGGLEABLE_FIELDS:
        return None
    conn = get_db()
    conn.execute(f"UPDATE users SET {field} = 1 - {field} WHERE id = ?", (user_id,))
    conn.commit()
    row = conn.execute(f"SELECT {field} FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def update_user_field(user_id, field, value):
    """Update a specific user field."""
    allowed = {"neighborhood", "quiet_start", "quiet_end", "notify_digest", "notify_instant", "active", "name"}
    if field not in allowed:
        return False
    conn = get_db()
    conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, user_id))
    conn.commit()
    conn.close()
    return True


def get_known_neighborhoods():
    """Get distinct neighborhoods from events."""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT neighborhood FROM events WHERE neighborhood IS NOT NULL AND neighborhood != '' AND is_past=0 ORDER BY neighborhood"
    ).fetchall()
    conn.close()
    return [r["neighborhood"] for r in rows]


# ===== CONFIRMATIONS =====

def confirm_event(user_id, event_id):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO confirmations (user_id, event_id) VALUES (?, ?)
        """, (user_id, event_id))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def is_confirmed(user_id, event_id):
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM confirmations WHERE user_id=? AND event_id=?
    """, (user_id, event_id)).fetchone()
    conn.close()
    return row is not None


def get_tomorrow_confirmed():
    """Get all users with confirmed events for tomorrow — for reminders."""
    tomorrow_iso = (_today_il() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute("""
        SELECT u.telegram_chat_id, u.name, e.title, e.event_time, e.end_time,
               e.event_date, e.location, e.link, e.age_group, c.confirmed_at
        FROM confirmations c
        JOIN users u ON c.user_id = u.id
        JOIN events e ON c.event_id = e.event_id
        WHERE e.event_date_iso = ? AND u.active = 1
        ORDER BY e.event_time
    """, (tomorrow_iso,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ===== STATS =====

def get_stats():
    conn = get_db()
    stats = {
        "users": conn.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0],
        "users_total": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "users_today": conn.execute("SELECT COUNT(*) FROM users WHERE date(registered_at) = date('now','localtime')").fetchone()[0],
        "users_week": conn.execute("SELECT COUNT(*) FROM users WHERE registered_at >= datetime('now','localtime', '-7 days')").fetchone()[0],
        "events_total": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "events_available": conn.execute("SELECT COUNT(*) FROM events WHERE is_full=0 AND is_past=0").fetchone()[0],
        "events_today": len(get_today_events()),
        "sections": conn.execute("SELECT COUNT(*) FROM sections WHERE active=1").fetchone()[0],
        "notifications_sent": conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
        "notifications_today": conn.execute("SELECT COUNT(*) FROM notifications WHERE date(sent_at) = date('now')").fetchone()[0],
        "preferences_total": conn.execute("SELECT COUNT(*) FROM user_preferences").fetchone()[0],
        "top_keywords": [(row[0], row[1]) for row in conn.execute(
            "SELECT keyword, COUNT(*) as cnt FROM user_preferences GROUP BY keyword ORDER BY cnt DESC LIMIT 10"
        ).fetchall()],
    }
    conn.close()
    return stats


def save_daily_snapshot():
    """Save a daily statistics snapshot. Called once a day from digest cron."""
    import json
    conn = get_db()
    today = _today_il().isoformat()
    # Check if already saved today
    existing = conn.execute("SELECT id FROM daily_stats WHERE date=?", (today,)).fetchone()
    if existing:
        conn.close()
        return
    stats = get_stats()
    top_kw = json.dumps(stats["top_keywords"][:10], ensure_ascii=False)
    # Count new users today
    new_today = conn.execute(
        "SELECT COUNT(*) FROM users WHERE date(registered_at) = date('now','localtime')"
    ).fetchone()[0]
    # Count notifications today
    notif_today = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE date(sent_at) = date('now','localtime')"
    ).fetchone()[0]
    conn.execute("""
        INSERT INTO daily_stats (date, users_active, users_total, users_new,
            events_total, events_available, notifications_sent, preferences_total, top_keywords)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (today, stats["users"], stats["users_total"], new_today,
          stats["events_total"], stats["events_available"], notif_today,
          stats["preferences_total"], top_kw))
    conn.commit()
    conn.close()


def get_stats_history(days=7):
    """Get daily stats for the last N days."""
    conn = get_db()
    rows = conn.execute("""
        SELECT date, users_active, users_total, users_new, events_total,
               events_available, notifications_sent, preferences_total, top_keywords
        FROM daily_stats
        ORDER BY date DESC LIMIT ?
    """, (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ===== HELPERS for Railway bot (replacing previous HTTP api.php client) =====

def get_events_by_date(date_iso):
    """Events for a specific YYYY-MM-DD, not past, ordered by time then title."""
    conn = get_db()
    rows = conn.execute("""
        SELECT e.*, s.name as section_name FROM events e
        LEFT JOIN sections s ON e.section_id = s.id
        WHERE e.event_date_iso = ? AND e.is_past = 0
        ORDER BY e.event_time, e.title
    """, (date_iso,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_events_for_matching():
    """All non-past events with the columns needed by /list keyword matching."""
    conn = get_db()
    rows = conn.execute(
        "SELECT title, raw_text, event_date, event_date_iso, event_time, is_full, age_group "
        "FROM events WHERE is_past=0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_event_by_id(event_id):
    """Single event by event_id (the coing event id, not the autoincrement pk)."""
    conn = get_db()
    row = conn.execute(
        "SELECT title, raw_text FROM events WHERE event_id=?", (event_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_or_create_manual_section():
    """Return the section.id for the 'manual' (אירועים ידניים) section, creating it if missing."""
    conn = get_db()
    row = conn.execute("SELECT id FROM sections WHERE slug='manual'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO sections (slug, name, cid, city, active) VALUES ('manual', 'אירועים ידניים', 0, 'batya', 1)"
        )
        conn.commit()
        row = conn.execute("SELECT id FROM sections WHERE slug='manual'").fetchone()
    section_id = row["id"]
    conn.close()
    return section_id


# Init DB on import
init_db()
