#!/usr/bin/env python3
"""
בוט טלגרם חכם — BatYam Today
================================
בוט שמבין שאלות בעברית ומחזיר תשובות רלוונטיות.
תומך בהגדרת העדפות, שאילתות חופשיות, והמלצות אישיות.

פקודות:
  /start          — הרשמה והגדרת העדפות
  /today           — מה קורה היום?
  /tomorrow        — מה קורה מחר?
  /week            — השבוע הקרוב
  /track <מילה>    — הוסיפי מעקב
  /untrack <מילה>  — הסירי מעקב
  /list            — ההעדפות שלי
  /recommend       — המלצות אישיות
  /help            — עזרה

שאלות חופשיות (בלי /):
  "מה יש היום במתנס הבונים?"
  "מה יש מחר אחהצ?"
  "מה יש לגיל 3?"
  "מה ממליץ לי?"
"""

import requests
import json
import os
import re
import html
import datetime
import zoneinfo
from collections import defaultdict

import batyam_db as db

IL_TZ = zoneinfo.ZoneInfo("Asia/Jerusalem")

# Load secrets
def load_secrets():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for path in [
        os.path.join(os.path.dirname(script_dir), "batyam_secrets.json"),
        os.path.join(os.path.expanduser("~"), "batyam_secrets.json"),
        os.path.join(script_dir, "batyam_secrets.json"),
    ]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}

SECRETS = load_secrets()
TELEGRAM_BOT_TOKEN = SECRETS.get("TELEGRAM_BOT_TOKEN", "")
DASHBOARD_URL = SECRETS.get("DASHBOARD_URL", "https://meravtech.com/batyam/")
ADMIN_CHAT_IDS = set(SECRETS.get("ADMIN_CHAT_IDS", []))

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batyam_bot.log")


def log(msg):
    line = f"[{datetime.datetime.now(IL_TZ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# Tiny attribution shown at the bottom of /start, /help, /about and pushed
# notifications so anyone receiving a message knows who built the bot.
# IMPORTANT: keep the visible text free of bare domain literals (e.g. don't
# write "meravtech.com" as anchor text). Telegram auto-detects bare URLs
# inside anchor text, conflicts with the surrounding <a>, and ends up
# breaking the line and chopping the trailing "m" off the domain.
BRAND_LINE = '✍️ נוצר על ידי <a href="https://meravtech.com">מירב טלר ושדי | הטכנולוגית</a>'
BRAND_FOOTER = f"\n\n<i>{BRAND_LINE}</i>"


def send_typing(chat_id):
    """Show 'typing…' indicator above the chat. Lasts ~5 s on Telegram side.

    Call right after you receive a webhook so the user sees activity while
    the bot does its DB lookup / external fetch / multi-message reply.
    """
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass


def _ensure_credit(text, parse_mode="HTML"):
    """Every outgoing message carries Merav's credit + site link, always.

    מירב ביקשה במפורש: קרדיט בכל סוג הודעה. במקום לסמוך על כל פורמט בנפרד
    (וכל פורמט חדש שיישכח), הקרדיט מתווסף כאן — בשכבת השליחה — לכל הודעה
    שעדיין אין בה אחד. טקסט רגיל + דומיין גלוי, כדי שישרוד העתקה לוואטסאפ.
    """
    if "הטכנולוגית" in text:
        return text  # message already carries its own credit
    if parse_mode == "HTML":
        return text + "\n\n<i>✍️ נוצר על ידי מירב טלר ושדי | הטכנולוגית</i>\nmeravtech.com"
    return text + "\n\n✍️ נוצר על ידי מירב טלר ושדי | הטכנולוגית\nmeravtech.com"


def send_telegram(chat_id, text, parse_mode="HTML", reply_markup=None):
    text = _ensure_credit(text, parse_mode)
    if not TELEGRAM_BOT_TOKEN:
        log(f"  [DRY] -> {chat_id}: {text[:80]}")
        return True
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                   "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload, timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        log(f"  שגיאת טלגרם: {e}")
        return False


def edit_telegram(chat_id, message_id, text, parse_mode="HTML", reply_markup=None):
    """Edit an existing message in place (for settings menu)."""
    text = _ensure_credit(text, parse_mode)
    if not TELEGRAM_BOT_TOKEN:
        return True
    try:
        payload = {"chat_id": chat_id, "message_id": message_id,
                   "text": text, "parse_mode": parse_mode,
                   "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText",
            json=payload, timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        log(f"  שגיאת עריכה: {e}")
        return False


def send_my_tracks(chat_id, user_id):
    """Send list of active tracks with remove buttons.

    callback_data uses the preference id (small int), not the keyword text.
    Telegram limits callback_data to 64 bytes; keywords with control chars or
    long URL-encoded payloads previously broke the whole message silently.
    """
    prefs = db.get_user_preferences(user_id)
    if not prefs:
        send_telegram(chat_id, "📭 <b>אין מעקבים פעילים</b>\n\nלחצו על תחומים בהודעת הפתיחה, או כתבו:\n/track גימבורי")
        return

    text = f"📋 <b>המעקבים שלך ({len(prefs)}):</b>\n\nלחצו על X כדי להסיר:"
    buttons = []
    for p in prefs:
        # Sanitize button label only — control chars in keywords break Telegram rendering.
        label = re.sub(r"[\r\n\t]+", " ", p["keyword"] or "").strip()
        if len(label) > 40:
            label = label[:37] + "…"
        buttons.append([{"text": f"❌ {label}", "callback_data": f"rmpref:{p['id']}"}])
    buttons.append([{"text": "➕ הוסיפו עוד תחומים", "callback_data": "cmd:start_tracks"}])

    send_telegram(chat_id, text, reply_markup={"inline_keyboard": buttons})


def make_whatsapp_text(ev):
    """Create a WhatsApp share message for an event."""
    title = (ev.get("title") or "פעילות")[:80]
    title = re.sub(r'^בת ים\s*[-–]\s*פעילויות הפגה במקלטים\s*', '', title).strip()
    title = re.sub(r'^החברה לתרבות פנאי וספורט בת ים\s*', '', title).strip()

    age = ev.get("age_group") or ""
    location = ev.get("location") or ""
    date_str = ev.get("event_date") or ""
    time_str = ev.get("event_time") or ""
    link = ev.get("link") or ""

    # Day of week in Hebrew
    day_names = {0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת", 6: "ראשון"}
    day_label = ""
    try:
        import datetime
        iso = ev.get("event_date_iso")
        if iso:
            d = datetime.date.fromisoformat(iso)
            day_label = f"יום {day_names.get(d.weekday(), '')}"
    except:
        pass

    lines = [f"מוזמנים ל{title}"]
    if age:
        lines.append(f"לגילאי {age}")

    info_parts = []
    if day_label:
        info_parts.append(day_label)
    if date_str:
        info_parts.append(date_str)
    if time_str:
        info_parts.append(time_str)
    if location:
        info_parts.append(location)
    if info_parts:
        lines.append(" | ".join(info_parts))

    lines.append("")
    if link:
        lines.append(link)
    lines.append("")
    lines.append("מס' המקומות מוגבל!")
    lines.append("במידה ואין ביכולתכם להגיע — נא בטלו הרשמה.")

    return "\n".join(lines)


def send_event_alert(chat_id, ev):
    """Send an event alert with action buttons."""
    text = format_event_line(ev)
    text = "🚨 <b>יש מקום פנוי!</b>\n\n" + text

    # WhatsApp share link
    wa_text = make_whatsapp_text(ev)
    import urllib.parse
    wa_url = "https://wa.me/?text=" + urllib.parse.quote(wa_text)

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ נרשמתי!", "callback_data": f"confirm:{ev.get('event_id', '')}"},
                {"text": "🔇 עצרו התראות", "callback_data": f"mute:{ev.get('event_id', '')}"},
            ],
            [
                {"text": "📲 שתפו בוואטסאפ", "url": wa_url},
            ],
        ]
    }
    return send_telegram(chat_id, text, reply_markup=reply_markup)


# ===== FORMATTERS =====

def _clean_event_title(raw_title):
    title = (raw_title or "")[:80]
    title = re.sub(r'^בת ים\s*[-–]\s*פעילויות הפגה במקלטים\s*', '', title).strip()
    title = re.sub(r'^החברה לתרבות פנאי וספורט בת ים\s*', '', title).strip()
    return title or "פעילות"


def format_event_card(ev, include_inline_links=True, show_date=True):
    """Format a single event as Telegram-flavored HTML.

    include_inline_links=False produces a button-friendly message body — the
    register/share links live in a separate inline_keyboard, not in the text.
    show_date=False omits the date from the meta row — used when events are
    already grouped under a date header (avoids '📅 יום רביעי' + '📅 29/07' twice).
    """
    time_str = ev.get("event_time") or ""
    location = ev.get("location") or ""
    age = ev.get("age_group") or ""
    title = html.escape(_clean_event_title(ev.get("title")))
    link = ev.get("link") or ""
    capacity = ev.get("capacity", 0) or 0
    registered = ev.get("registered", 0) or 0
    spots = capacity - registered if capacity > 0 else -1
    is_full = ev.get("is_full") or (capacity > 0 and spots <= 0)

    line = f"📌 <b>{title}</b>"
    meta = []
    if time_str:
        meta.append(f"🕐 {time_str}")
    date_str = ev.get("event_date") or ""
    if date_str and show_date:
        meta.append(f"📅 {date_str}")
    if location:
        meta.append(f"📍 {location}")
    if age:
        meta.append(f"👶 {age}")
    if is_full:
        meta.append("❌ מלא")
    elif spots > 0:
        meta.append(f"✅ {spots} מקומות פנויים")
    elif capacity > 0:
        meta.append(f"👥 {registered}/{capacity}")
    else:
        meta.append("📋 רישום פתוח")
    if meta:
        line += "\n" + " | ".join(meta)

    if include_inline_links:
        if link:
            # Plain URL — users copy these messages into WhatsApp; an <a> anchor
            # loses the link on paste. The wa.me share stays an anchor (its URL
            # is huge and only useful as a click action, never as copied text).
            line += f"\n👉 להרשמה: {link}"
        if link and not is_full:
            line += f"\n📲 <a href=\"{_event_whatsapp_url(ev)}\">שתפו בוואטסאפ</a>"

    return line


# Backward-compatible alias used by other callers (e.g. push notifications).
def format_event_line(ev):
    return format_event_card(ev, include_inline_links=True)


def _event_whatsapp_url(ev):
    """wa.me URL with a pre-filled share message for a single event."""
    import urllib.parse
    title = _clean_event_title(ev.get("title"))
    age = ev.get("age_group") or ""
    parts = []
    if ev.get("event_date"):
        parts.append(ev["event_date"])
    if ev.get("event_time"):
        parts.append(ev["event_time"])
    if ev.get("location"):
        parts.append(ev["location"])
    body = f"מוזמנים ל{title}"
    if age:
        body += f"\nלגילאי {age}"
    if parts:
        body += "\n" + " | ".join(parts)
    if ev.get("link"):
        body += f"\n\n{ev['link']}"
    body += "\n\nמס' המקומות מוגבל!\nבמידה ואין ביכולתכם להגיע — נא בטלו הרשמה."
    return "https://wa.me/?text=" + urllib.parse.quote(body)


def event_buttons(ev):
    """Inline keyboard rows for a single event card: [להרשמה][שיתוף]."""
    row = []
    link = ev.get("link") or ""
    is_full = ev.get("is_full")
    if link:
        row.append({"text": "📝 להרשמה", "url": link})
    if link and not is_full:
        row.append({"text": "📤 שיתוף", "url": _event_whatsapp_url(ev)})
    return [row] if row else []


def _date_group_header(ev):
    """'📅 יום רביעי, 29/07' — date header for grouped event lists."""
    day_names = {0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת", 6: "ראשון"}
    iso = ev.get("event_date_iso")
    date_str = ev.get("event_date") or ""
    try:
        d = datetime.date.fromisoformat(iso)
        return f"יום {day_names.get(d.weekday(), '')}, {d.strftime('%d/%m')}"
    except Exception:
        return date_str or "ללא תאריך מוגדר"


def send_events_response(chat_id, events, header=""):
    """Send a list of events as a single consolidated message (no spam).

    Empty list → one consolation message.
    Any events → header + date-grouped list in ONE message, capped so long
    free-text searches (3 weeks of results) stay inside Telegram's 4096-char
    limit — the rest is one click away on the site.
    """
    if not events:
        send_telegram(chat_id, header + "\n\n📭 לא נמצאו פעילויות מתאימות\n\n💡 נסו /week לראות את כל השבוע או /recommend להמלצות אישיות")
        return None

    # מיון לפי תאריך ואז שעה — חיפוש חופשי מחזיר שבועות קדימה, ומיון לפי
    # שעה בלבד עירבב תאריכים (אירוע של 20.8 הופיע לפני אירוע של 19.7).
    events.sort(key=lambda e: (e.get("event_date_iso") or "9999-12-31",
                               e.get("event_time") or "99:99"))

    MAX_EVENTS = 15  # ~3100 תווים גלויים במקרה הגרוע — בטוח מתחת ל-4096 של טלגרם
    shown = events[:MAX_EVENTS]
    rest = len(events) - len(shown)

    lines = []
    if header:
        lines.append(header)
        lines.append("")
    last_date = None
    for ev in shown:
        group = _date_group_header(ev)
        if group != last_date:
            lines.append(f"📅 <b>{group}</b>")
            lines.append("")
            last_date = group
        # Date lives in the group header — keep the card itself compact
        lines.append(format_event_card(ev, include_inline_links=True, show_date=False))
        lines.append("")
    if rest > 0:
        lines.append(f"…ועוד {rest} פעילויות נוספות — כולן באתר 👇")
        lines.append("")
    # Attribution — plain text so it survives copy-paste to WhatsApp.
    # Don't remove without asking Merav.
    lines.append("<i>✍️ נוצר על ידי מירב טלר ושדי | הטכנולוגית</i>")
    lines.append("meravtech.com")
    keyboard = {"inline_keyboard": [[
        {"text": "🔗 פתחו רשימה מלאה באתר", "url": DASHBOARD_URL},
    ]]}
    ok = send_telegram(chat_id, "\n".join(lines), reply_markup=keyboard)
    if not ok:
        # לעולם לא משאירים משתמש בלי תגובה: אם ההודעה המלאה נכשלה (ארוכה
        # מדי / HTML בעייתי), שולחים גרסה קצרה עם קישור לאתר.
        send_telegram(chat_id,
            f"{header}\n\n📊 נמצאו {len(events)} פעילויות — הרשימה ארוכה מכדי להציג כאן.",
            reply_markup=keyboard)
    return None


def format_events_list(events, header=""):
    """Legacy string-returning formatter, kept for digest/dispatcher callers."""
    if not events:
        return header + "\n\n📭 לא נמצאו פעילויות מתאימות"

    events.sort(key=lambda e: e.get("event_time") or "99:99")
    lines = []
    if header:
        lines.append(header)
        lines.append("")
    for ev in events:
        lines.append(format_event_card(ev, include_inline_links=True))
        lines.append("")
    lines.append(f"🔗 <a href=\"{DASHBOARD_URL}\">לכל הפעילויות</a>")
    return "\n".join(lines)


# ===== QUERY ENGINE =====

def normalize(text):
    """Normalize text for matching."""
    text = text.lower().strip()
    text = re.sub(r"['\u05F3\u05F4\u0027\u2018\u2019\u0060\u00B4\"״׳]", "", text)
    return text


# Hebrew holidays — static map for the current Gregorian year(s).
# Dates are Gregorian (DD, MM, YYYY). Holidays often span 1-2 days; we return the start.
HOLIDAYS = {
    # 2026
    "פסח":         (2, 4, 2026),    # Pesach (1st seder)
    "שביעי של פסח": (8, 4, 2026),
    "יום הזיכרון":  (21, 4, 2026),
    "יום העצמאות":  (22, 4, 2026),
    "לג בעומר":    (6, 5, 2026),
    "ל\"ג בעומר":  (6, 5, 2026),
    "לג":          (6, 5, 2026),    # short form
    "יום ירושלים":  (15, 5, 2026),
    "שבועות":      (22, 5, 2026),
    "צום תמוז":    (5, 7, 2026),
    "תשעה באב":    (26, 7, 2026),
    "ראש השנה":    (12, 9, 2026),
    "יום כיפור":   (21, 9, 2026),
    "סוכות":       (26, 9, 2026),
    "שמחת תורה":   (4, 10, 2026),
    "חנוכה":       (5, 12, 2026),
    "פורים":       (3, 3, 2027),
}


def get_target_date(text):
    """Extract target date from natural language. Returns (date_or_None, label)."""
    today = datetime.date.today()
    text_lower = text.lower()

    # Holidays first (specific match)
    for kw, (d, m, y) in HOLIDAYS.items():
        if kw in text:
            holiday_date = datetime.date(y, m, d)
            if holiday_date >= today:
                return holiday_date, kw
            # If the holiday this year already passed and the same key has a later occurrence,
            # the next year's date (if any) would have been overwritten in the dict — so just return.
            return holiday_date, kw

    if any(w in text_lower for w in ["היום", "עכשיו", "כרגע"]):
        return today, "היום"
    elif any(w in text_lower for w in ["מחר"]):
        return today + datetime.timedelta(days=1), "מחר"
    elif any(w in text_lower for w in ["מחרתיים"]):
        return today + datetime.timedelta(days=2), "מחרתיים"
    elif any(w in text_lower for w in ["שבוע הבא", "השבוע הבא", "בשבוע הבא"]):
        # Range query: marker tuple (start, end) so query_events knows it is a range.
        # Israeli week starts Sunday (weekday 6 in Python's Monday=0).
        days_until_sunday = (6 - today.weekday()) % 7
        if days_until_sunday == 0:
            days_until_sunday = 7
        next_sunday = today + datetime.timedelta(days=days_until_sunday)
        return ("range", next_sunday, next_sunday + datetime.timedelta(days=6)), "שבוע הבא"
    elif any(w in text_lower for w in ["שבוע", "השבוע"]):
        return None, "השבוע"  # None = current-week range query (existing behavior)
    elif any(w in text_lower for w in ["שישי"]):
        days_ahead = (4 - today.weekday()) % 7
        return today + datetime.timedelta(days=days_ahead), "יום שישי"
    elif any(w in text_lower for w in ["שבת"]):
        days_ahead = (5 - today.weekday()) % 7
        return today + datetime.timedelta(days=days_ahead), "שבת"
    elif any(w in text_lower for w in ["ראשון", "ביום ראשון"]):
        days_ahead = (6 - today.weekday()) % 7 or 7
        return today + datetime.timedelta(days=days_ahead), "יום ראשון"
    elif any(w in text_lower for w in ["שני", "ביום שני", "בשני"]):
        days_ahead = (0 - today.weekday()) % 7 or 7
        return today + datetime.timedelta(days=days_ahead), "יום שני"
    elif any(w in text_lower for w in ["שלישי", "ביום שלישי", "בשלישי"]):
        days_ahead = (1 - today.weekday()) % 7 or 7
        return today + datetime.timedelta(days=days_ahead), "יום שלישי"
    elif any(w in text_lower for w in ["רביעי", "ביום רביעי", "ברביעי"]):
        days_ahead = (2 - today.weekday()) % 7 or 7
        return today + datetime.timedelta(days=days_ahead), "יום רביעי"
    elif any(w in text_lower for w in ["חמישי", "ביום חמישי", "בחמישי"]):
        days_ahead = (3 - today.weekday()) % 7 or 7
        return today + datetime.timedelta(days=days_ahead), "יום חמישי"

    return today, "היום"


def get_time_filter(text):
    """Extract time filter from text."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["בוקר", "בקר"]):
        return "morning", (6, 12)
    elif any(w in text_lower for w in ["צהריים", "צהרים"]):
        return "noon", (11, 14)
    elif any(w in text_lower for w in ["אחהצ", "אחר הצהריים", "אחרי הצהריים"]):
        return "afternoon", (13, 18)
    elif any(w in text_lower for w in ["ערב"]):
        return "evening", (17, 23)
    return None, None


def get_age_filter(text):
    """Extract age from text."""
    m = re.search(r'גיל\s*(\d+)', text)
    if m:
        return int(m.group(1))
    m = re.search(r'לבן\s*(\d+)', text)
    if m:
        return int(m.group(1))
    m = re.search(r'לבת\s*(\d+)', text)
    if m:
        return int(m.group(1))
    return None


_FILTER_STOPWORDS = {
    # מילות שאלה ופניה
    "מה", "מי", "איזה", "איזו", "איפה", "מתי", "האם", "יש", "יהיה", "משהו",
    "לי", "לך", "אתה", "את", "אתם", "הבוט", "בבוט", "תגיד", "תגידי", "תאמר", "ספר", "תספר",
    "אנא", "בבקשה", "אפשר", "בא", "אהבתי", "רוצה", "צריך", "יודע",
    "תוכל", "אולי", "כן", "לא", "תודה",
    # ברכות
    "שלום", "היי", "הי", "טוב", "ערב",
    # מילות תאריך/זמן (מטופלות בנפרד)
    "היום", "מחר", "מחרתיים", "שבוע", "השבוע",
    "ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת",
    "בראשון", "בשני", "בשלישי", "ברביעי", "בחמישי", "בשישי",
    "ביום",
    "בוקר", "ערב", "בערב", "בבוקר", "בצהריים", "צהריים", "צהרים", "אחהצ", "עכשיו", "כרגע",
    # קישוריות
    "של", "על", "עם", "אל", "מן",
    "או", "ואת", "בעיר", "בבת", "ים", "פעילויות", "אירועים", "פעילות",
    "אירוע", "מופע", "מופעים", "חוג", "חוגים", "מפגש", "מפגשים",
}


def get_text_filter(text):
    """Extract free-text search terms (e.g., a presenter's name like 'אורלי')."""
    # גרש/אפוסטרוף נמחקים (לא הופכים לרווח!) — "ג'ימבורי" חייב להישאר מילה
    # אחת "גימבורי", אחרת הוא מתפצל ל"ג"+"ימבורי" ולא נמצא כלום.
    cleaned = re.sub(r"['׳’`]", '', text)
    cleaned = re.sub(r'[?!.,;:"()\[\]/\\]', ' ', cleaned)
    words = [w.strip() for w in cleaned.split() if w.strip()]
    search_terms = []
    for w in words:
        if w.lower() in _FILTER_STOPWORDS:
            continue
        if w.isdigit():
            continue
        if len(w) <= 2:
            continue
        if any(prefix in w for prefix in ("מתנס", "מתנ")):
            continue
        search_terms.append(w)
    return search_terms if search_terms else None


def get_location_filter(text):
    """Extract location from text."""
    text_norm = normalize(text)
    # Check known patterns
    patterns = [
        (r'מתנס\s+([\u0590-\u05FF]+(?:\s+[\u0590-\u05FF]+)?)', lambda m: m.group(0)),
        (r'בית ספר\s+([\u0590-\u05FF]+)', lambda m: m.group(0)),
        (r'ביס\s+([\u0590-\u05FF]+)', lambda m: "בית ספר " + m.group(1)),
        (r'פארק\s+([\u0590-\u05FF]+)', lambda m: m.group(0)),
    ]
    for pat, fmt in patterns:
        m = re.search(pat, text_norm)
        if m:
            return fmt(m)
    return None


def query_events(text, user_id=None, chat_id=None):
    """Main query engine — understand a question and return matching events.

    If chat_id is provided, the response is sent directly with per-event action
    buttons via send_events_response and this function returns None. Otherwise
    a single concatenated HTML string is returned (legacy behavior used by
    callers that compose into a larger message).
    """
    target_date, date_label = get_target_date(text)
    time_label, time_range = get_time_filter(text)
    age = get_age_filter(text)
    location = get_location_filter(text)
    text_terms = get_text_filter(text)

    # אם יש חיפוש חופשי (שם של מורה/נושא) ואין תאריך ספציפי בשאלה — חפש בכל
    # האירועים הקרובים. חלון של 60 יום: אירועי הקיץ הגדולים (אמפי, חגיגות
    # המאה) מתפרסמים חודש-חודשיים מראש, ו-21 יום פספסו אותם.
    has_explicit_date = any(w in text.lower() for w in [
        "היום", "מחר", "מחרתיים", "שישי", "שבת", "ראשון", "שבוע"
    ])
    if text_terms and not has_explicit_date:
        rows = db.get_upcoming_events(days=60)
        date_label = "הקרובות"
        target_date = None
    elif isinstance(target_date, tuple) and len(target_date) == 3 and target_date[0] == "range":
        # Custom date range (e.g. "next week")
        _, start_d, end_d = target_date
        all_upcoming = db.get_upcoming_events(days=21)
        rows = [
            ev for ev in all_upcoming
            if ev.get("event_date_iso") and start_d.strftime("%Y-%m-%d") <= ev["event_date_iso"] <= end_d.strftime("%Y-%m-%d")
        ]
    elif target_date:
        target_iso = target_date.strftime("%Y-%m-%d")
        rows = db.get_events_by_date(target_iso)
    else:
        # Default week query
        events = db.get_upcoming_events(days=7)
        rows = events  # already dicts

    events = [dict(r) if not isinstance(r, dict) else r for r in rows]

    # Apply filters
    filtered = []
    for ev in events:
        # Time filter
        if time_range and ev.get("event_time"):
            try:
                hour = int(ev["event_time"].split(":")[0])
                if not (time_range[0] <= hour < time_range[1]):
                    continue
            except:
                pass

        # Age filter
        if age and ev.get("age_group"):
            ag = ev["age_group"]
            m = re.match(r'(\d+)-(\d+)', ag)
            if m:
                min_age, max_age = int(m.group(1)), int(m.group(2))
                if not (min_age <= age <= max_age):
                    continue

        # Location filter
        if location:
            ev_loc = normalize(ev.get("location") or "")
            ev_text = normalize(ev.get("raw_text") or "")
            loc_norm = normalize(location)
            if loc_norm not in ev_loc and loc_norm not in ev_text:
                continue

        # Free-text filter (presenter name, topic, etc.) — כל המונחים חייבים
        # להופיע באירוע (AND). קודם היה מספיק מונח אחד (OR), ואז "חנן בן ארי"
        # החזיר 30+ אירועים לא קשורים כי "ארי" הופיע איפשהו.
        # כל מונח מורחב במילים נרדפות (db.keyword_terms) — "ספורט" מוצא גם
        # "מונדיאל", בדיוק כמו במעקבים — ונבדק גם בלי תחיליות עבריות נפוצות
        # (ל, ב, מ, ש, ו, ה) — "לאורלי" יזהה "אורלי".
        if text_terms:
            # אותו מנוע התאמה כמו המעקבים: נרמול (מתקן חיפוש "גימבורי" מול
            # "ג'ימבורי"), ניקוי שם המארגן, מילים נרדפות, וגבולות מילה עבריים.
            ev_title = db.normalize_text(ev.get("title") or "")
            ev_haystack = db.matchable_text(ev)
            def _term_found(t, haystack):
                return any(db.term_in_text(v, haystack) for v in db.keyword_terms(t))
            if not all(_term_found(t.lower(), ev_haystack) for t in text_terms):
                continue
            # התאמה "חזקה" = המונח מופיע בכותרת האירוע עצמה (לא רק אי-שם בטקסט),
            # או שהאירוע הוא הופעה חיה מובהקת: העירייה כותבת "על הבמה: ריטה, ברי
            # סחרוף..." בגוף האירוע — סמן אמין גם כשהכותרת גנרית ("קבלת שבת חגיגית").
            STAGE_SIGNALS = ("על הבמה", "במופע מלא", "הופעה מרכזית", "הופעה חיה")
            ev["_strong"] = (all(_term_found(t.lower(), ev_title) for t in text_terms)
                             or any(s in ev_haystack for s in STAGE_SIGNALS))

        filtered.append(ev)

    # קטגוריה רחבה ("מוזיקה") מחזירה עשרות התאמות-טקסט חלשות שדוחקות את
    # ההופעות הגדולות מעבר לגבול התצוגה. אם יש יותר מדי תוצאות ויש התאמות
    # כותרת — מציגים אותן; השאר נשארות בספירה ובאתר.
    if text_terms and len(filtered) > 12:
        strong = [ev for ev in filtered if ev.get("_strong")]
        if strong:
            filtered = strong

    # Build header
    header_parts = [f"📋 <b>פעילויות {date_label}</b>"]
    if time_label:
        time_labels = {"morning": "בוקר", "noon": "צהריים", "afternoon": "אחה\"צ", "evening": "ערב"}
        header_parts[0] += f" ({time_labels.get(time_label, '')})"
    if text_terms:
        header_parts.append(f"🔍 חיפוש: {' '.join(text_terms)}")
    if location:
        header_parts.append(f"📍 {location}")
    if age:
        header_parts.append(f"👶 גיל {age}")
    header_parts.append(f"נמצאו {len(filtered)} פעילויות")

    header = "\n".join(header_parts)
    if chat_id is not None:
        send_events_response(chat_id, filtered, header)
        return None
    return format_events_list(filtered, header)


def get_recommendations(user_id):
    """Get personalized recommendations based on user preferences."""
    prefs = db.get_user_preferences(user_id)
    if not prefs:
        return "🎯 <b>עדיין לא הגדרת העדפות!</b>\n\nשלחו /track ואחריו מילת חיפוש, למשל:\n/track גימבורי\n/track יצירה\n/track שמרטפייה"

    events = db.get_upcoming_events(days=7)
    matched = []

    for ev in events:
        if ev.get("is_full"):
            continue
        for pref in prefs:
            # Same matcher as dispatcher/list — synonyms, age ranges, רוסית
            if db.event_matches_keyword(pref["keyword"], ev):
                ev["_matched_kw"] = pref["keyword"]
                matched.append(ev)
                break

    if not matched:
        kw_list = ", ".join(p["keyword"] for p in prefs)
        return f"🔍 <b>אין פעילויות מתאימות כרגע</b>\n\nמילות המעקב שלך: {kw_list}\nנמשיך לחפש ונודיע ברגע שיהיה משהו!"

    header = f"🎯 <b>המלצות אישיות</b>\nלפי ההעדפות שלך — {len(matched)} פעילויות מתאימות!"
    return format_events_list(matched, header)


# ===== COMMAND HANDLERS =====

def handle_start(chat_id, text, user):
    """Handle /start command — different for new vs returning users."""
    # Reactivate if was stopped
    if not user.get("active"):
        db.update_user_field(user["id"], "active", 1)

    name = user.get("name") or ""
    greeting = f" {name}" if name else ""
    prefs = db.get_user_preferences(user["id"])

    if prefs:
        # Returning user — show status + actions
        pref_list = ", ".join(p["keyword"] for p in prefs)
        welcome_text = (
            f"👋 <b>היי{greeting}! שמחים לראותך</b>\n\n"
            f"📋 <b>המעקבים שלך:</b> {pref_list}\n"
            f"🔔 התראות: {'פעילות' if user.get('notify_instant') else 'כבויות'}\n"
            f"📰 דייג'סט יומי: {'פעיל' if user.get('notify_digest') else 'כבוי'}\n\n"
            f"מה תרצו לעשות?" + BRAND_FOOTER
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📅 מה יש היום?", "callback_data": "cmd:today"},
                    {"text": "📅 מחר?", "callback_data": "cmd:tomorrow"},
                ],
                [
                    {"text": "🎯 המלצות לי", "callback_data": "cmd:recommend"},
                    {"text": "📋 המעקבים שלי", "callback_data": "cmd:mytracks"},
                ],
                [
                    {"text": "➕ הוסיפו מעקב", "callback_data": "cmd:start_tracks"},
                    {"text": "⚙️ הגדרות", "callback_data": "cmd:settings"},
                ],
            ]
        }
    else:
        # New user — wizard onboarding (step 1)
        welcome_text = (
            f"🎉 <b>היי{greeting}! ברוכים הבאים</b>\n\n"
            f"אני אעזור לכם לא לפספס פעילויות לילדים בבת ים.\n\n"
            f"<b>שלב 1 מתוך 2 — בחרו מה מעניין אתכם:</b>\n"
            f"(לחצו על כמה שרוצים)" + BRAND_FOOTER
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "👶 פעוטות", "callback_data": "qtrack:פעוטות"},
                    {"text": "🧒 ילדים", "callback_data": "qtrack:ילדים"},
                    {"text": "🏃 ספורט", "callback_data": "qtrack:ספורט"},
                ],
                [
                    {"text": "🎨 יצירה", "callback_data": "qtrack:יצירה"},
                    {"text": "🎵 מוזיקה", "callback_data": "qtrack:מוזיקה"},
                    {"text": "🎭 תרבות", "callback_data": "qtrack:תרבות"},
                ],
                [
                    {"text": "🕯 שבת וחגים", "callback_data": "qtrack:שבת"},
                    {"text": "🛡 הפגה במקלטים", "callback_data": "qtrack:הפגה"},
                    {"text": "🤝 קהילה", "callback_data": "qtrack:קהילה"},
                ],
                [
                    {"text": "🇷🇺 רוסית", "callback_data": "qtrack:רוסית"},
                ],
                [
                    {"text": "👶 0-3", "callback_data": "qtrack:גיל 0-3"},
                    {"text": "🧒 3-6", "callback_data": "qtrack:גיל 3-6"},
                    {"text": "📚 6-12", "callback_data": "qtrack:גיל 6-12"},
                    {"text": "🎓 12+", "callback_data": "qtrack:גיל 12+"},
                    {"text": "🧑 18+", "callback_data": "qtrack:גיל 18+"},
                ],
                [
                    {"text": "✅ סיימתי — מה יש היום?", "callback_data": "cmd:today"},
                ],
            ]
        }
        send_telegram(chat_id, welcome_text, reply_markup=keyboard)

        # Step 2 — explain how to add custom keywords
        step2 = (
            "<b>שלב 2 — מעקב לפי מילות חיפוש:</b>\n\n"
            "כתבו מילה או שם פעילות — וכל פעם שתתפרסם פעילות שמכילה את המילה הזו, תקבלו התראה!\n\n"
            "לדוגמה:\n"
            "<code>/track גימבורי</code> — כל פעילות גימבורי\n"
            "<code>/track סדנה</code> — כל סדנה שתתפרסם\n"
            "<code>/track בת חן, יצירה</code> — כמה מילים בבת אחת\n\n"
            "💡 אפשר לשלב מעקב לפי מילה + לפי גיל + לפי תחום — תקבלו התראה על כולם!\n\n"
            "🌐 <a href=\"https://meravtech.com/batyam/\">האתר המלא</a>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💻 <a href=\"https://meravtech.com\">הטכנולוגית</a> — מירב טלר ושדי"
        )
        send_telegram(chat_id, step2)
        return None
    send_telegram(chat_id, welcome_text, reply_markup=keyboard)
    return None


def handle_today(chat_id, user):
    query_events("מה יש היום", user_id=user["id"] if user else None, chat_id=chat_id)
    return None


def handle_tomorrow(chat_id, user):
    query_events("מה יש מחר", user_id=user["id"] if user else None, chat_id=chat_id)
    return None


def handle_week(chat_id, user):
    query_events("מה יש השבוע", user_id=user["id"] if user else None, chat_id=chat_id)
    return None


def handle_track(chat_id, text, user):
    raw = text.replace("/track", "").strip()
    if not raw:
        return "📝 כתבו /track ואחריו מילת חיפוש\nלמשל: /track גימבורי\n\nאפשר כמה מילים מופרדות בפסיק:\n/track גימבורי, יצירה, בת חן"

    # Split by comma, newline, or "ו" connector
    import re
    keywords = re.split(r'[,،\n]+', raw)
    keywords = [kw.strip() for kw in keywords if kw.strip() and len(kw.strip()) >= 2]

    if not keywords:
        return "📝 לא זיהיתי מילות חיפוש. נסו שוב."

    added = []
    existing = []
    for kw in keywords:
        if db.add_preference(user["id"], kw):
            added.append(kw)
        else:
            existing.append(kw)

    parts = []
    if added:
        parts.append(f"✅ נוספו: <b>{', '.join(html.escape(k) for k in added)}</b>")
    if existing:
        parts.append(f"ℹ️ כבר קיימים: {', '.join(html.escape(k) for k in existing)}")
    parts.append("\nתקבלו התראה ברגע שתהיה פעילות מתאימה!")
    return "\n".join(parts)


def handle_untrack(chat_id, text, user):
    keyword = text.replace("/untrack", "").strip()
    if not keyword:
        prefs = db.get_user_preferences(user["id"])
        if not prefs:
            return "📭 אין מעקבים פעילים"
        kw_list = "\n".join(f"• {p['keyword']} — /untrack {p['keyword']}" for p in prefs)
        return f"📋 <b>המעקבים שלך:</b>\n{kw_list}"

    db.remove_preference(user["id"], keyword)
    return f"🗑 הסרתי מעקב על: <b>{html.escape(keyword)}</b>"


def handle_list(chat_id, user):
    prefs = db.get_user_preferences(user["id"])
    if not prefs:
        send_telegram(chat_id,
            "📭 <b>אין מעקבים פעילים</b>\n\nהוסיפו תחומים שמעניינים אתכם:",
            reply_markup={"inline_keyboard": [[
                {"text": "➕ הוסיפו מעקב", "callback_data": "cmd:start_tracks"}
            ]]})
        return None

    # Count matching events per keyword (via api.php)
    all_events = db.get_all_events_for_matching()

    lines = ["📋 <b>המעקבים שלך:</b>", ""]
    today_iso = datetime.datetime.now(IL_TZ).strftime("%Y-%m-%d")
    show_buttons = []  # one button per tracker with matches — tap to see the events
    for p in prefs:
        # Same matcher the dispatcher uses (synonyms, age ranges, רוסית) — so the
        # counts here always agree with what notifications will actually fire.
        matches = [ev for ev in all_events if db.event_matches_keyword(p["keyword"], ev)]

        if matches:
            available = [m for m in matches if not m["is_full"]]
            # "הקרובה" = nearest FUTURE dated event (matches[0] was arbitrary DB
            # order and often dateless, which rendered an empty line).
            upcoming = sorted(
                (m for m in matches if (m.get("event_date_iso") or "") >= today_iso),
                key=lambda m: (m["event_date_iso"], m.get("event_time") or ""))
            status = f"🟢 {len(available)} פנויות" if available else "🔴 הכל מלא"
            lines.append(f"• <b>{p['keyword']}</b> — {len(matches)} פעילויות ({status})")
            if upcoming:
                next_ev = upcoming[0]
                time_str = f" {next_ev['event_time']}" if next_ev.get("event_time") else ""
                lines.append(f"  הקרובה: {next_ev['event_date']}{time_str}")
            cb = f"showkw:{p['keyword']}"
            if len(cb.encode("utf-8")) <= 64:  # Telegram callback_data hard limit
                show_buttons.append({"text": f"👀 {p['keyword']} ({len(matches)})", "callback_data": cb})
        else:
            lines.append(f"• <b>{p['keyword']}</b> — אין פעילויות כרגע")

    lines.append("")
    if show_buttons:
        lines.append("👇 לחצו על מעקב כדי לראות את הפעילויות עצמן:")

    # Tracker buttons in rows of 2, then the management row
    keyboard_rows = [show_buttons[i:i + 2] for i in range(0, len(show_buttons), 2)]
    keyboard_rows += [
        [{"text": "➕ הוסיפו", "callback_data": "cmd:start_tracks"},
         {"text": "🗑 הסירו", "callback_data": "cmd:mytracks"}],
        [{"text": "🎯 המלצות", "callback_data": "cmd:recommend"},
         {"text": "⚙️ הגדרות", "callback_data": "cmd:settings"}],
    ]
    send_telegram(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": keyboard_rows})
    return None


def show_tracker_events(chat_id, keyword):
    """Show the actual events behind a tracker count (from the /list buttons)."""
    events = [ev for ev in db.get_upcoming_events(days=60)
              if db.event_matches_keyword(keyword, ev)]
    header = f"👀 <b>פעילויות במעקב: {keyword}</b>"
    send_events_response(chat_id, events, header)


def handle_recommend(chat_id, user):
    return get_recommendations(user["id"])


def handle_about(chat_id):
    """Short bio + attribution. Reachable via /about and linked from /help and /start."""
    text = (
        "🤖 <b>BatYam Today Bot</b>\n\n"
        "ניטור בזמן אמת של פעילויות לילדים בבת ים, מבוסס על coing.co/batya.\n"
        "פתוח לקהילה, חינם לחלוטין.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "✍️ <b>נוצר על ידי מירב טלר ושדי | הטכנולוגית</b>\n"
        "אם הבוט עוזר לכם — ספרו עליו לחברים והמשפחה 💜\n\n"
        "🌐 <a href=\"https://meravtech.com\">האתר העסקי שלי</a>\n"
        "📬 פניות, הצעות, באגים: שלחו DM כאן בבוט (אני קוראת הכל)\n"
        "🔒 מידע פרטיות: <a href=\"https://meravtech.com/batyam/privacy.html\">מדיניות פרטיות</a>"
    )
    send_telegram(chat_id, text)
    return None


def handle_help(chat_id):
    text = (
        "🤖 <b>איך להשתמש ב-BatYam Today?</b>\n\n"
        "<b>שלב 1 — בחרו מה מעניין אתכם:</b>\n"
        "לחצו /track ובחרו תחומים (פעוטות, ילדים, ספורט...)\n"
        "או כתבו: /track גימבורי\n"
        "👶 מעקב לפי גיל: /track גיל 0-3 / גיל 3-6 / גיל 6-12\n\n"
        "<b>שלב 2 — קבלו התראות!</b>\n"
        "ברגע שיתפרסם אירוע שמתאים לכם — תקבלו הודעה מיידית.\n"
        "כשיתפנה מקום — גם על זה תקבלו התראה.\n\n"
        "<b>שלב 3 — נרשמו? לחצו ✅ נרשמתי</b>\n"
        "וההתראות על האירוע הזה ייפסקו.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>שאלו בעברית חופשית:</b>\n"
        "• \"מה יש היום?\"\n"
        "• \"מה יש מחר בבוקר?\"\n"
        "• \"מה יש לגיל 3?\"\n"
        "• \"מה ממליץ לי?\"\n\n"
        "<b>פקודות:</b>\n"
        "/today — מה קורה היום\n"
        "/tomorrow — מה קורה מחר\n"
        "/week — מה קורה השבוע\n"
        "/track — הוסיפו מעקב\n"
        "/list — המעקבים שלי\n"
        "/settings — הגדרות\n"
        "/recommend — המלצות אישיות\n"
        "/stop — הפסקת כל ההתראות\n\n"
        "🌐 <a href=\"https://meravtech.com/batyam/\">האתר המלא</a>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✍️ נוצר על ידי <a href=\"https://meravtech.com\">מירב טלר ושדי | הטכנולוגית</a>\n"
        "ℹ️ עוד עליי: /about"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "➕ הוסיפו מעקב", "callback_data": "cmd:start_tracks"},
                {"text": "⚙️ הגדרות", "callback_data": "cmd:settings"},
            ],
            [
                {"text": "📅 היום", "callback_data": "cmd:today"},
                {"text": "📆 מחר", "callback_data": "cmd:tomorrow"},
                {"text": "🗓 שבוע", "callback_data": "cmd:week"},
            ],
        ]
    }
    send_telegram(chat_id, text, reply_markup=reply_markup)
    return None


def handle_stats(chat_id):
    """Admin-only: show bot analytics."""
    if ADMIN_CHAT_IDS and chat_id not in ADMIN_CHAT_IDS:
        return "הפקודה הזו זמינה למנהלים בלבד."
    stats = db.get_stats()
    top_kw = "\n".join(f"  {i+1}. {kw} ({cnt})" for i, (kw, cnt) in enumerate(stats.get("top_keywords", [])))
    text = (
        f"📊 <b>אנליטיקות BatYam Today</b>\n\n"
        f"<b>👥 משתמשים</b>\n"
        f"  פעילים: {stats['users']}\n"
        f"  סה\"כ (כולל מושבתים): {stats['users_total']}\n"
        f"  הצטרפו היום: {stats['users_today']}\n"
        f"  הצטרפו השבוע: {stats['users_week']}\n\n"
        f"<b>📅 אירועים</b>\n"
        f"  סה\"כ ב-DB: {stats['events_total']}\n"
        f"  פנויים ופעילים: {stats['events_available']}\n"
        f"  היום: {stats['events_today']}\n"
        f"  מדורים: {stats['sections']}\n\n"
        f"<b>🔔 התראות</b>\n"
        f"  נשלחו היום: {stats['notifications_today']}\n"
        f"  סה\"כ: {stats['notifications_sent']}\n\n"
        f"<b>🏷 מעקבים</b>\n"
        f"  סה\"כ: {stats['preferences_total']}\n\n"
        f"<b>🔝 מילות מעקב פופולריות:</b>\n{top_kw}"
    )
    # Add history if available
    history = db.get_stats_history(7)
    if history:
        text += "\n\n<b>📈 מגמות (ימים אחרונים):</b>\n"
        text += "תאריך | משתמשים | חדשים | התראות | מעקבים\n"
        for h in reversed(history):
            d = h['date'][5:]  # MM-DD
            text += f"{d} | {h['users_active']} | +{h['users_new']} | {h['notifications_sent']} | {h['preferences_total']}\n"
    send_telegram(chat_id, text)
    return None


def build_settings_message(user):
    """Build settings menu text and inline keyboard."""
    instant = "✅" if user.get("notify_instant") else "❌"
    digest = "✅" if user.get("notify_digest") else "❌"
    reminder = "✅" if user.get("notify_reminder", 1) else "❌"
    hood = user.get("neighborhood") or "לא מוגדר"
    quiet = f"{user.get('quiet_start', '22:00')}-{user.get('quiet_end', '07:00')}"

    prefs = db.get_user_preferences(user["id"])
    pref_text = ", ".join([p["keyword"] for p in prefs]) if prefs else "אין — הוסיפו עם /track"

    text = (
        "⚙️ <b>ההגדרות שלי</b>\n\n"
        f"🔔 התראות מיידיות: {instant}\n"
        f"📰 דייג'סט יומי: {digest}\n"
        f"⏰ תזכורת לפעילות: {reminder}\n"
        f"🏘 שכונה: {hood}\n"
        f"🌙 שעות שקט: {quiet}\n\n"
        f"📋 <b>מעקבים:</b> {pref_text}"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"🔔 מיידי: {instant}", "callback_data": "set:notify_instant"},
                {"text": f"📰 דייג'סט: {digest}", "callback_data": "set:notify_digest"},
            ],
            [
                {"text": f"⏰ תזכורת: {reminder}", "callback_data": "set:notify_reminder"},
                {"text": "🌙 שעות שקט", "callback_data": "set:pick_quiet"},
            ],
            [
                {"text": "🏘 בחר שכונה", "callback_data": "set:pick_hood"},
            ],
            [
                {"text": "📋 המעקבים שלי", "callback_data": "cmd:mytracks"},
                {"text": "➕ הוסיפו מעקב", "callback_data": "cmd:start_tracks"},
            ],
        ]
    }

    return text, keyboard


def handle_settings(chat_id, user):
    """Send settings menu with inline buttons."""
    text, keyboard = build_settings_message(user)
    send_telegram(chat_id, text, reply_markup=keyboard)


def handle_stop(chat_id, user):
    """Deactivate user — stop all notifications."""
    db.update_user_field(user["id"], "active", 0)
    return (
        "👋 <b>הפסקתי לשלוח התראות.</b>\n\n"
        "לא תקבלו יותר התראות או דייג'סט.\n"
        "בכל שלב — שלחו /start כדי לחזור."
    )


def handle_add_event(chat_id, text, user):
    """Admin-only: add a manual event.
    Format: /add כותרת | תאריך DD/MM/YYYY | שעה HH:MM | מיקום | קישור | תמונה
    """
    if ADMIN_CHAT_IDS and chat_id not in ADMIN_CHAT_IDS:
        return "הפקודה הזו זמינה למנהלים בלבד."

    content = text.replace("/add", "").strip()
    if not content:
        return (
            "📝 <b>הוספת אירוע ידני</b>\n\n"
            "שלחו בפורמט:\n"
            "<code>/add כותרת | תאריך | שעה | מיקום | קישור | תמונה</code>\n\n"
            "דוגמה:\n"
            "<code>/add מופע קטנטנים לגילאי 1.5-3 | 19/04/2026 | 17:00 | מתנ\"ס הבונים | https://link.com | https://meravtech.com/batyam/images/show.jpg</code>\n\n"
            "💡 קישור ותמונה אופציונליים\n"
            "💡 גיל — הוסיפו בכותרת: לגילאי 1-3"
        )

    parts = [p.strip() for p in content.split("|")]
    if len(parts) < 3:
        return "❌ חסרים פרטים. פורמט:\n/add כותרת | תאריך DD/MM/YYYY | שעה HH:MM | מיקום"

    title = parts[0]
    date_str = parts[1]
    time_str = parts[2] if len(parts) > 2 else ""
    location = parts[3] if len(parts) > 3 else ""
    link = parts[4] if len(parts) > 4 else ""
    image_url = parts[5] if len(parts) > 5 else ""

    # Validate date
    import re as _re
    date_match = _re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', date_str)
    if not date_match:
        return "❌ פורמט תאריך שגוי. השתמשו ב: DD/MM/YYYY"

    d, m, y = date_match.group(1), date_match.group(2), date_match.group(3)
    event_date = f"{int(d):02d}/{int(m):02d}/{y}"
    event_date_iso = f"{y}-{int(m):02d}-{int(d):02d}"

    # Detect age from title — שימוש בלוגיקת הזיהוי המרכזית של הסקרייפר,
    # כדי שגם פקודת /add (אירועים ידניים של מנהלים) תזהה גילאים באותה
    # שיטה כמו אירועים שנגרפים מהקוינג. אסור להסיק גיל ממילים כמו
    # "תינוקות"/"פעוטות" — רק מספרים מפורשים או מילות מספר בעברית
    # (שנה, שלוש שנים) בהקשר תווית גיל מובהקת.
    try:
        from batyam_scraper import detect_age_group as _scraper_detect_age
        age_group = _scraper_detect_age(title)
    except Exception:
        age_group = None

    # Detect neighborhood from title + location
    neighborhoods = ["רמת הנשיא", "רמת יוסף", "לב העיר", "רובע דרום", "רמת דרום", "רובע צפון", "צפון", "עמידר", "פארק הים"]
    all_text = f"{title} {location}"
    neighborhood = None
    for n in neighborhoods:
        if n in all_text:
            neighborhood = n
            break

    # Build rich raw_text for search filters
    raw_parts = [title, location, date_str, time_str]
    if age_group:
        raw_parts.append(f"גיל {age_group}")
    if neighborhood:
        raw_parts.append(neighborhood)
    raw_text = " ".join(p for p in raw_parts if p)

    # Get or create manual section (via api.php)
    try:
        manual_section_id = db.get_or_create_manual_section()
    except:
        manual_section_id = 1

    # Generate unique event ID
    import hashlib
    event_id = "manual_" + hashlib.md5(f"{title}{event_date}{time_str}".encode()).hexdigest()[:10]

    # Save to DB
    try:
        db.upsert_event(
            event_id=event_id,
            section_id=manual_section_id,
            title=title,
            event_date=event_date,
            registered=0,
            capacity=0,
            is_full=False,
            is_past=False,
            link=link or "",
            raw_text=raw_text,
            neighborhood=neighborhood,
            age_group=age_group,
            event_time=time_str,
            location=location,
            image_url=image_url or "",
        )

        result = f"✅ <b>אירוע נוסף בהצלחה!</b>\n\n"
        result += f"📌 {html.escape(title)}\n"
        result += f"📅 {event_date}\n"
        if time_str:
            result += f"🕐 {time_str}\n"
        if location:
            result += f"📍 {html.escape(location)}\n"
        if age_group:
            result += f"👶 גיל {age_group}\n"
        if neighborhood:
            result += f"🏘 {neighborhood}\n"
        if link:
            result += f"🔗 <a href=\"{link}\">קישור</a>\n"
        if image_url:
            result += f"🖼 תמונה: מצורפת\n"
        result += f"\n💡 האירוע יופיע באתר בעדכון הבא (עד 5 דקות)"
        return result
    except Exception as e:
        return f"❌ שגיאה בהוספה: {e}"


# ===== MAIN PROCESSOR =====

def process_message(chat_id, text, user_name=None):
    """Process an incoming message and return a response."""
    user = db.get_or_create_user(str(chat_id), user_name)
    text = text.strip()

    log(f"  [{chat_id}] {text}")

    # Deep link from website: /start track_<base64> or /start track_גימבורי
    if text.startswith("/start track_"):
        raw = text.replace("/start track_", "").strip()
        # Try base64 decode (website sends Hebrew as base64)
        try:
            import base64
            decoded = base64.b64decode(raw.replace('-', '+').replace('_', '/') + '==').decode('utf-8')
            keyword = decoded
        except Exception:
            keyword = raw.replace("_", " ")
        if keyword:
            db.add_preference(user["id"], keyword)
            return (
                f"🎉 <b>ברוכים הבאים!</b>\n\n"
                f"✅ הוספתי מעקב על: <b>{keyword}</b>\n"
                f"תקבלו התראה ברגע שתהיה פעילות מתאימה עם מקום פנוי!\n\n"
                f"💡 אפשר להוסיף עוד מעקבים עם /track"
            )

    # Deep link: /start preferences — show settings/track picker
    if text.strip() == "/start preferences":
        handle_settings(chat_id, user)
        return None

    # Commands
    if text.startswith("/start"):
        return handle_start(chat_id, text, user)
    elif text.startswith("/today"):
        return handle_today(chat_id, user)
    elif text.startswith("/tomorrow"):
        return handle_tomorrow(chat_id, user)
    elif text.startswith("/week"):
        return handle_week(chat_id, user)
    elif text.startswith("/track"):
        return handle_track(chat_id, text, user)
    elif text.startswith("/untrack"):
        return handle_untrack(chat_id, text, user)
    elif text.startswith("/list"):
        return handle_list(chat_id, user)
    elif text.startswith("/recommend"):
        return handle_recommend(chat_id, user)
    elif text.startswith("/settings"):
        handle_settings(chat_id, user)
        return None
    elif text.startswith("/stop"):
        return handle_stop(chat_id, user)
    elif text.startswith("/site") or text.startswith("/web"):
        send_telegram(chat_id,
            "🌐 <b>האתר המלא — מה קורה היום בבת ים?</b>\n\nסינון, חיפוש, מחולל הודעות ועוד:",
            reply_markup={"inline_keyboard": [[
                {"text": "🌐 פתחו את האתר", "url": DASHBOARD_URL}
            ]]})
        return None
    elif text.startswith("/help"):
        return handle_help(chat_id)
    elif text.startswith("/about") or text.startswith("/credits"):
        return handle_about(chat_id)
    elif text.startswith("/stats"):
        return handle_stats(chat_id)
    elif text.startswith("/add"):
        return handle_add_event(chat_id, text, user)

    # Free-text queries
    text_lower = text.lower()

    # Free-text command shortcuts (without /)
    if text_lower in ("list", "רשימה", "מעקבים", "המעקבים שלי"):
        return handle_list(chat_id, user)
    if text_lower in ("help", "עזרה", "הסבר", "איך"):
        return handle_help(chat_id)
    if text_lower in ("stop", "עצור", "הפסק", "הפסיקי"):
        return handle_stop(chat_id, user)
    if text_lower in ("site", "אתר"):
        send_telegram(chat_id,
            "🌐 <b>האתר המלא:</b>",
            reply_markup={"inline_keyboard": [[{"text": "🌐 פתחו את האתר", "url": DASHBOARD_URL}]]})
        return None

    # Settings request
    if any(w in text_lower for w in ["הגדרות", "העדפות", "settings"]):
        handle_settings(chat_id, user)
        return None

    # "מה ממליץ" / "תמליץ" / "המלצות"
    if any(w in text_lower for w in ["ממליץ", "תמליץ", "המלצ", "recommend"]):
        return get_recommendations(user["id"])

    # Any question about activities
    if any(w in text_lower for w in ["מה יש", "מה קורה", "מה עושים", "מה אפשר",
                                       "יש משהו", "פעילויות", "אירועים", "מה היום",
                                       "מה מחר", "מה בשבוע"]):
        try:
            query_events(text, user_id=user["id"], chat_id=chat_id)
        except Exception as e:
            log(f"  שגיאת חיפוש [{chat_id}] '{text}': {e}")
            return f"😕 משהו השתבש בחיפוש. נסו שוב, או כל הפעילויות באתר:\n{DASHBOARD_URL}"
        return None

    # Greetings and thank-yous — respond nicely, don't search
    greetings = ["שלום", "היי", "הי", "בוקר טוב", "ערב טוב", "תודה", "תודה רבה", "מעולה", "אחלה", "סבבה", "👍", "❤️", "🙏"]
    if text.strip() in greetings or text_lower in [g.lower() for g in greetings]:
        return "😊 שלום! איך אוכל לעזור?\n\n/today — מה קורה היום\n/track — הוסיפו מעקב\n/help — כל האפשרויות"

    # Default — try to answer as a query if it looks like one
    if len(text) > 4:
        try:
            query_events(text, user_id=user["id"], chat_id=chat_id)
        except Exception as e:
            log(f"  שגיאת חיפוש [{chat_id}] '{text}': {e}")
            return f"😕 משהו השתבש בחיפוש. נסו שוב, או כל הפעילויות באתר:\n{DASHBOARD_URL}"
        return None

    return "🤔 לא הבנתי. נסו:\n/today — מה קורה היום\n/help — כל האפשרויות\n\nאו שאלו בעברית: \"מה יש מחר?\""


# ===== WEBHOOK HANDLER =====

def handle_callback(callback_query):
    """Handle inline button presses (confirm/mute)."""
    data = callback_query.get("data", "")
    chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
    callback_id = callback_query.get("id")

    if not chat_id or not data:
        return

    user = db.get_or_create_user(str(chat_id))

    if data.startswith("confirm:"):
        event_id = data.split(":", 1)[1]
        db.confirm_event(user["id"], event_id)
        answer_callback(callback_id, "✅ מעולה! נרשמת.")
        reminder_on = user.get("notify_reminder", 1)
        reminder_text = "\n⏰ תקבלו תזכורת בבוקר יום הפעילות." if reminder_on else ""
        # Find matched keyword for this event to offer untrack
        matched_kw = None
        try:
            ev = db.get_event_by_id(event_id)
            if ev:
                prefs = db.get_user_preferences(user["id"])
                ev_text = db.normalize_text((ev["raw_text"] or "") + " " + (ev["title"] or ""))
                for p in prefs:
                    if db.normalize_text(p["keyword"]) in ev_text:
                        matched_kw = p["keyword"]
                        break
        except:
            pass
        buttons = []
        if reminder_on:
            buttons.append([{"text": "⏰ כבה תזכורות", "callback_data": "set:notify_reminder"}])
        if matched_kw:
            buttons.append([{"text": f"🔕 הפסיקו מעקב על: {matched_kw}", "callback_data": f"rmtrack:{matched_kw}"}])
        send_telegram(chat_id,
            f"✅ <b>שמרתי!</b> לא אשלח יותר התראות על האירוע הזה.{reminder_text}\n\n"
            f"💡 המעקבים שלכם עדיין פעילים — תקבלו התראה על פעילויות חדשות דומות!\n\n"
            f"בהצלחה! 🎉",
            reply_markup={"inline_keyboard": buttons} if buttons else None
        )
    elif data.startswith("mute:"):
        event_id = data.split(":", 1)[1]
        db.log_notification(user["id"], event_id, "muted")
        answer_callback(callback_id, "🔇 הושתק.")
        # Find matched keyword to offer untrack
        matched_kw = None
        try:
            ev = db.get_event_by_id(event_id)
            if ev:
                prefs = db.get_user_preferences(user["id"])
                ev_text = db.normalize_text((ev["raw_text"] or "") + " " + (ev["title"] or ""))
                for p in prefs:
                    if db.normalize_text(p["keyword"]) in ev_text:
                        matched_kw = p["keyword"]
                        break
        except:
            pass
        buttons = []
        if matched_kw:
            buttons.append([{"text": f"🔕 הפסיקו מעקב על: {matched_kw}", "callback_data": f"rmtrack:{matched_kw}"}])
        buttons.append([{"text": "⚙️ ההגדרות שלי", "callback_data": "cmd:settings"}])
        send_telegram(chat_id,
            f"🔇 <b>הושתק.</b> לא אשלח יותר על האירוע הזה.\n\n"
            f"💡 המעקבים שלכם עדיין פעילים — תקבלו התראה על פעילויות חדשות דומות!",
            reply_markup={"inline_keyboard": buttons}
        )
    elif data.startswith("qtrack:"):
        keyword = data.split(":", 1)[1]
        success = db.add_preference(user["id"], keyword)
        if success:
            # Show toast only, no separate message — less spam
            prefs = db.get_user_preferences(user["id"])
            active = ", ".join(p["keyword"] for p in prefs)
            answer_callback(callback_id, f"✅ {keyword} — נוסף! ({len(prefs)} מעקבים)")
        else:
            answer_callback(callback_id, f"כבר עוקבים: {keyword}")
    elif data.startswith("rmtrack:"):
        # Legacy path: callback_data has the keyword text (still works for short ASCII-safe keywords)
        keyword = data.split(":", 1)[1]
        db.remove_preference(user["id"], keyword)
        answer_callback(callback_id, f"🗑 הוסר: {keyword}")
        send_my_tracks(chat_id, user["id"])
    elif data.startswith("showkw:"):
        # /list button: show the actual events behind a tracker count
        keyword = data.split(":", 1)[1]
        answer_callback(callback_id, f"👀 {keyword}")
        show_tracker_events(chat_id, keyword)
    elif data.startswith("rmpref:"):
        # Preferred path: callback_data has the preference id (always under 64 bytes)
        try:
            pref_id = int(data.split(":", 1)[1])
        except ValueError:
            answer_callback(callback_id, "מזהה לא תקין")
            return
        keyword = db.remove_preference_by_id(user["id"], pref_id)
        answer_callback(callback_id, f"🗑 הוסר: {keyword}" if keyword else "כבר הוסר")
        send_my_tracks(chat_id, user["id"])
    elif data.startswith("set:"):
        setting = data.split(":", 1)[1]
        message_id = callback_query.get("message", {}).get("message_id")

        if setting in ("notify_instant", "notify_digest", "notify_reminder"):
            new_val = db.toggle_user_setting(user["id"], setting)
            labels = {"notify_instant": "התראות מיידיות", "notify_digest": "דייג'סט יומי", "notify_reminder": "תזכורת לפעילות"}
            label = labels.get(setting, setting)
            icon = "✅" if new_val else "❌"
            answer_callback(callback_id, f"{label}: {icon}")
            # Refresh user data and edit message in place
            user = db.get_or_create_user(str(chat_id))
            text, keyboard = build_settings_message(user)
            if message_id:
                edit_telegram(chat_id, message_id, text, reply_markup=keyboard)

        elif setting == "pick_hood":
            hoods = db.get_known_neighborhoods()
            if not hoods:
                answer_callback(callback_id, "אין שכונות זמינות כרגע")
                return
            buttons = [[{"text": h, "callback_data": f"hood:{h}"}] for h in hoods[:8]]
            buttons.append([{"text": "↩️ חזרה", "callback_data": "cmd:settings"}])
            if message_id:
                edit_telegram(chat_id, message_id, "🏘 <b>בחרו שכונה:</b>",
                             reply_markup={"inline_keyboard": buttons})
            answer_callback(callback_id, "")

        elif setting == "pick_quiet":
            options = [
                [{"text": "22:00–07:00 (ברירת מחדל)", "callback_data": "quiet:22:00-07:00"}],
                [{"text": "23:00–08:00", "callback_data": "quiet:23:00-08:00"}],
                [{"text": "21:00–06:00", "callback_data": "quiet:21:00-06:00"}],
                [{"text": "🔔 ללא הגבלה", "callback_data": "quiet:none"}],
                [{"text": "↩️ חזרה", "callback_data": "cmd:settings"}],
            ]
            if message_id:
                edit_telegram(chat_id, message_id, "🌙 <b>שעות שקט:</b>\n(לא נשלח התראות בשעות אלו)",
                             reply_markup={"inline_keyboard": options})
            answer_callback(callback_id, "")

    elif data.startswith("hood:"):
        hood = data.split(":", 1)[1]
        message_id = callback_query.get("message", {}).get("message_id")
        db.update_user_field(user["id"], "neighborhood", hood)
        answer_callback(callback_id, f"🏘 שכונה: {hood}")
        user = db.get_or_create_user(str(chat_id))
        text, keyboard = build_settings_message(user)
        if message_id:
            edit_telegram(chat_id, message_id, text, reply_markup=keyboard)

    elif data.startswith("quiet:"):
        val = data.split(":", 1)[1]
        message_id = callback_query.get("message", {}).get("message_id")
        if val == "none":
            db.update_user_field(user["id"], "quiet_start", "00:00")
            db.update_user_field(user["id"], "quiet_end", "00:00")
        else:
            parts = val.split("-")
            db.update_user_field(user["id"], "quiet_start", parts[0])
            db.update_user_field(user["id"], "quiet_end", parts[1])
        answer_callback(callback_id, f"🌙 עודכן!")
        user = db.get_or_create_user(str(chat_id))
        text, keyboard = build_settings_message(user)
        if message_id:
            edit_telegram(chat_id, message_id, text, reply_markup=keyboard)

    elif data.startswith("cmd:"):
        cmd = data.split(":", 1)[1]
        message_id = callback_query.get("message", {}).get("message_id")
        answer_callback(callback_id, "")
        if cmd == "today":
            query_events("מה יש היום", user_id=user["id"], chat_id=chat_id)
        elif cmd == "tomorrow":
            query_events("מה יש מחר", user_id=user["id"], chat_id=chat_id)
        elif cmd == "week":
            query_events("מה יש השבוע", user_id=user["id"], chat_id=chat_id)
        elif cmd == "mytracks":
            send_my_tracks(chat_id, user["id"])
        elif cmd == "recommend":
            resp = get_recommendations(user["id"])
            send_telegram(chat_id, resp)
        elif cmd == "start_tracks":
            # Show category picker for new tracks
            kb = {"inline_keyboard": [
                [{"text": "👶 פעוטות", "callback_data": "qtrack:פעוטות"},
                 {"text": "🧒 ילדים", "callback_data": "qtrack:ילדים"},
                 {"text": "🏃 ספורט", "callback_data": "qtrack:ספורט"}],
                [{"text": "🎨 יצירה", "callback_data": "qtrack:יצירה"},
                 {"text": "🎵 מוזיקה", "callback_data": "qtrack:מוזיקה"},
                 {"text": "🎭 תרבות", "callback_data": "qtrack:תרבות"}],
                [{"text": "🕯 שבת וחגים", "callback_data": "qtrack:שבת"},
                 {"text": "🛡 הפגה במקלטים", "callback_data": "qtrack:הפגה"},
                 {"text": "🤝 קהילה", "callback_data": "qtrack:קהילה"}],
                [{"text": "🇷🇺 רוסית", "callback_data": "qtrack:רוסית"}],
                [{"text": "👶 0-3", "callback_data": "qtrack:גיל 0-3"},
                 {"text": "🧒 3-6", "callback_data": "qtrack:גיל 3-6"},
                 {"text": "📚 6-12", "callback_data": "qtrack:גיל 6-12"},
                 {"text": "🎓 12+", "callback_data": "qtrack:גיל 12+"},
                 {"text": "🧑 18+", "callback_data": "qtrack:גיל 18+"}],
            ]}
            send_telegram(chat_id, "📌 <b>בחרו תחומים או גיל להוספה:</b>\n\nאו כתבו מילה חופשית עם /track", reply_markup=kb)
        elif cmd == "settings":
            text, keyboard = build_settings_message(user)
            if message_id:
                edit_telegram(chat_id, message_id, text, reply_markup=keyboard)
            else:
                handle_settings(chat_id, user)


def answer_callback(callback_id, text, show_alert=False):
    """Answer a callback query (dismiss the loading indicator)."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text, "show_alert": show_alert},
            timeout=10,
        )
    except:
        pass


def handle_webhook(payload):
    """Process a Telegram webhook payload."""
    if "callback_query" in payload:
        cb_chat_id = payload["callback_query"].get("message", {}).get("chat", {}).get("id")
        if cb_chat_id:
            send_typing(cb_chat_id)
        handle_callback(payload["callback_query"])
        return

    message = payload.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    user_name = message.get("from", {}).get("first_name", "")

    if not chat_id:
        return
    # Show "typing…" indicator immediately so the user sees the bot reacting,
    # even if the DB lookup or external fetch takes a second.
    send_typing(chat_id)

    if not text:
        send_telegram(chat_id, "😊 אני מבין רק טקסט.\n\nנסו: /today, /help, או שאלו בעברית!")
        return

    log(f"Webhook: {chat_id} ({user_name}): {text}")
    try:
        response = process_message(chat_id, text, user_name)
        if response:
            send_telegram(chat_id, response)
    except Exception as e:
        log(f"  ERROR in process_message: {e}")
        import traceback
        log(traceback.format_exc())


# ===== CLI TEST MODE =====

def interactive_test():
    """Interactive test mode — simulate bot conversation."""
    print("🤖 BatYam Today Bot — מצב בדיקה")
    print("הקלידו שאלה או פקודה (exit ליציאה)")
    print("=" * 50)

    test_chat_id = "test_user_123"

    while True:
        try:
            text = input("\n👤 את: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if text.lower() in ("exit", "quit", "יציאה"):
            break

        response = process_message(test_chat_id, text, "בדיקה")
        # Remove HTML tags for console display
        clean = re.sub(r'<[^>]+>', '', response)
        print(f"\n🤖 בוט: {clean}")


def poll_once():
    """Long-poll Telegram for updates (for cron use). Responds within 0-10 seconds."""
    import fcntl

    if not TELEGRAM_BOT_TOKEN:
        log("TELEGRAM_BOT_TOKEN not set")
        return

    # Lockfile: prevent overlapping cron runs
    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".batyam_bot.lock")
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        lock_fd.close()
        return  # Another instance running — exit silently

    try:
        # Read last update_id
        state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".batyam_bot_state.json")
        last_update_id = 0
        if os.path.exists(state_file):
            try:
                with open(state_file, "r") as f:
                    last_update_id = json.load(f).get("last_update_id", 0)
            except:
                pass

        total_processed = 0
        max_rounds = 6  # Process up to 6 rounds within 4 minutes
        start_time = datetime.datetime.now()
        max_duration = 240  # 4 minutes max — leaves 1 min buffer for 5-min cron

        for round_num in range(max_rounds):
            # Check if we've been running too long
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if elapsed >= max_duration:
                break

            remaining = max_duration - elapsed
            # Long poll — Telegram returns immediately when message arrives
            poll_timeout = min(55, int(remaining - 5)) if remaining > 10 else 2
            if poll_timeout < 2:
                break

            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                    params={"offset": last_update_id + 1, "timeout": poll_timeout, "limit": 20},
                    timeout=poll_timeout + 10,
                )
                data = resp.json()
                if not data.get("ok"):
                    log(f"Telegram error: {data}")
                    break

                updates = data.get("result", [])
                if not updates:
                    break  # No messages, stop

                for update in updates:
                    last_update_id = update["update_id"]

                    if "callback_query" in update:
                        handle_callback(update["callback_query"])
                        continue

                    message = update.get("message", {})
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "")
                    user_name = message.get("from", {}).get("first_name", "")

                    if not chat_id:
                        continue
                    if not text:
                        send_telegram(chat_id, "😊 אני מבין רק טקסט.\n\nנסו: /today, /help, או שאלו בעברית!")
                        continue
                    log(f"Poll: {chat_id} ({user_name}): {text}")
                    response = process_message(chat_id, text, user_name)
                    if response:
                        send_telegram(chat_id, response)

                total_processed += len(updates)

                # Save state after each round
                with open(state_file, "w") as f:
                    json.dump({"last_update_id": last_update_id}, f)

            except requests.exceptions.Timeout:
                break  # Normal: long poll timed out with no messages
            except Exception as e:
                log(f"Poll error: {e}")
                break

        if total_processed > 0:
            log(f"Processed {total_processed} messages")

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--webhook":
        # --webhook <path>: read the Telegram update JSON from a file,
        # handle it, then delete the file.
        # Fallback (no path): read from stdin (legacy behavior).
        if len(sys.argv) > 2:
            path = sys.argv[2]
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.loads(f.read())
                handle_webhook(payload)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        else:
            payload = json.loads(sys.stdin.read())
            handle_webhook(payload)
    elif len(sys.argv) > 1 and sys.argv[1] in ("--poll", "--queue"):
        # Legacy cron entries — no-op. Webhook is now direct (PHP shell_exec
        # invokes --webhook per update), so there's nothing to process here.
        pass
    elif len(sys.argv) > 1 and sys.argv[1] == "--test":
        interactive_test()
    else:
        interactive_test()
