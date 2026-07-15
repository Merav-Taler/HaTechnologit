#!/usr/bin/env python3
"""
דייג'סט יומי — BatYam Today
==============================
רץ פעם ביום (07:00) מ-cron.
מייצר סיכום יומי של מה קורה היום + השבוע הקרוב.
שולח לכל המשתמשים הרשומים בטלגרם.
מייצר טקסט מוכן להעתקה לוואטסאפ.
"""

import requests
import datetime
import zoneinfo
import os
import json
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

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batyam_digest.log")

DAYS_HEB = {
    0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי",
    4: "שישי", 5: "שבת", 6: "ראשון"
}


def log(msg):
    line = f"[{datetime.datetime.now(IL_TZ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_telegram(chat_id, message):
    # קרדיט בכל הודעה, תמיד (בקשה מפורשת של מירב) — אם הפורמט לא הוסיף, מוסיפים כאן.
    if "הטכנולוגית" not in message:
        message = message + "\n\n<i>✍️ נוצר על ידי מירב טלר ושדי | הטכנולוגית</i>\nmeravtech.com"
    if not TELEGRAM_BOT_TOKEN:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def format_date_hebrew(date_str):
    """Convert DD/MM/YYYY to Hebrew day name + date."""
    try:
        parts = date_str.split("/")
        d = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
        day_name = DAYS_HEB.get(d.weekday(), "")
        return f"יום {day_name}, {parts[0]}/{parts[1]}"
    except Exception:
        return date_str


def build_today_digest():
    """Build the daily digest for today's events."""
    now = datetime.datetime.now(IL_TZ)
    today_str = now.strftime("%d/%m/%Y")
    day_name = DAYS_HEB.get(now.weekday(), "")

    events = db.get_today_events()

    if not events:
        return None, None  # Nothing today

    # Group by section
    by_section = defaultdict(list)
    for ev in events:
        section = ev.get("section_name", "כללי")
        by_section[section].append(ev)

    # === Telegram version (HTML) ===
    tg_lines = [
        f"📋 <b>מה קורה היום בבת ים?</b>",
        f"📅 יום {day_name}, {now.strftime('%d/%m/%Y')}",
        "",
    ]

    for section, section_events in by_section.items():
        tg_lines.append(f"📍 <b>{section}</b>")
        for ev in section_events:
            cap = ev.get("capacity", 0) or 0
            reg = ev.get("registered", 0) or 0
            spots = cap - reg if cap > reg else 0
            is_full = ev.get("is_full") or (cap > 0 and spots <= 0)
            status = "❌" if is_full else "✅"
            spots_txt = f"(מלא)" if is_full else (f"({spots} מקומות)" if spots > 0 else "(רישום פתוח)")

            title = ev["title"][:50]
            tg_lines.append(f"  {status} {title}")
            if ev["capacity"] > 0:
                tg_lines.append(f"      👥 {ev['registered']}/{ev['capacity']} {spots_txt}")
            if ev.get("neighborhood"):
                tg_lines.append(f"      🏘 {ev['neighborhood']}")
            if ev["link"]:
                tg_lines.append(f"      👉 {ev['link']}")  # plain URL — survives copy to WhatsApp
            tg_lines.append("")

    tg_lines.append(f"🔗 לכל הפעילויות באתר: {DASHBOARD_URL}")  # plain URL — copy-safe
    tg_lines.append("")
    tg_lines.append("✍️ נוצר על ידי מירב טלר ושדי | הטכנולוגית\nmeravtech.com")  # plain — survives copy to WhatsApp
    telegram_msg = "\n".join(tg_lines)

    # === WhatsApp version (plain text with markdown) ===
    wa_lines = [
        f"📋 *מה קורה היום בבת ים?*",
        f"📅 יום {day_name}, {now.strftime('%d/%m/%Y')}",
        "",
    ]

    for section, section_events in by_section.items():
        wa_lines.append(f"📍 *{section}*")
        for ev in section_events:
            cap = ev.get("capacity", 0) or 0
            reg = ev.get("registered", 0) or 0
            spots = cap - reg if cap > reg else 0
            is_full = ev.get("is_full") or (cap > 0 and spots <= 0)
            status = "❌" if is_full else "✅"
            spots_txt = f"(מלא)" if is_full else (f"({spots} מקומות)" if spots > 0 else "(רישום פתוח)")

            title = ev["title"][:50]
            wa_lines.append(f"  {status} {title}")
            if ev["capacity"] > 0:
                wa_lines.append(f"      👥 {ev['registered']}/{ev['capacity']} {spots_txt}")
            if ev["link"]:
                wa_lines.append(f"      🔗 {ev['link']}")
        wa_lines.append("")

    wa_lines.append(f"📱 כל הפעילויות: {DASHBOARD_URL}")
    wa_lines.append("")
    wa_lines.append("✍️ נוצר ע\"י מירב טלר ושדי | הטכנולוגית — https://meravtech.com")
    whatsapp_msg = "\n".join(wa_lines)

    return telegram_msg, whatsapp_msg


def build_week_digest():
    """Build a weekly overview from today to end of week (Saturday)."""
    now = datetime.datetime.now(IL_TZ)
    today = now.date()
    today_str = now.strftime("%d/%m/%Y")

    # Calculate days until end of week (Saturday: weekday 5)
    # weekday(): 0=Monday, 5=Saturday, 6=Sunday
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7  # If today is Saturday, include full next week

    events = db.get_upcoming_events(days=days_until_saturday)

    # הדייג'סט היומי ("מה קורה היום") נשלח באותה ריצה — אל תחזור על אירועי
    # היום גם בסיכום השבועי. השבועי מציג רק את ההמשך: ממחר עד שבת.
    today_iso = today.strftime("%Y-%m-%d")
    events = [ev for ev in events if (ev.get("event_date_iso") or "") > today_iso]

    if not events:
        return None

    # Group by date (tomorrow onwards — today already went out in the daily digest)
    by_date = defaultdict(list)
    for ev in events:
        date_key = ev.get("event_date", "לא ידוע")
        by_date[date_key].append(ev)

    if not by_date:
        return None

    tg_lines = [
        "📆 <b>מה עוד מחכה לכם השבוע בבת ים?</b>",
        "",
    ]

    for date_key in sorted(by_date.keys(), key=lambda d: db.parse_date_to_iso(d) or ""):
        date_heb = format_date_hebrew(date_key)
        tg_lines.append(f"📅 <b>{date_heb}</b>")

        for ev in by_date[date_key]:
            cap = ev.get("capacity", 0) or 0
            reg = ev.get("registered", 0) or 0
            spots = cap - reg if cap > reg else 0
            is_full = ev.get("is_full") or (cap > 0 and spots <= 0)
            status = "❌" if is_full else "✅"
            spots_txt = f"(מלא)" if is_full else (f"({spots} מקומות)" if spots > 0 else "(רישום פתוח)")

            title = ev["title"][:50]
            tg_lines.append(f"  {status} {title}")
            if ev["capacity"] > 0:
                tg_lines.append(f"      👥 {ev['registered']}/{ev['capacity']} {spots_txt}")
            if ev.get("neighborhood"):
                tg_lines.append(f"      🏘 {ev['neighborhood']}")
            if ev["link"]:
                tg_lines.append(f"      👉 {ev['link']}")  # plain URL — survives copy to WhatsApp

        tg_lines.append("")

    tg_lines.append(f"🔗 לכל הפעילויות באתר: {DASHBOARD_URL}")  # plain URL — copy-safe
    tg_lines.append("")
    tg_lines.append("✍️ נוצר על ידי מירב טלר ושדי | הטכנולוגית\nmeravtech.com")  # plain — survives copy to WhatsApp
    return "\n".join(tg_lines)


def main():
    log("=" * 50)
    log("BatYam Today — דייג'סט יומי")

    # Save daily stats snapshot
    try:
        db.save_daily_snapshot()
        log("שמירת סנאפשוט יומי — הצלחה")
    except Exception as e:
        log(f"שגיאה בשמירת סנאפשוט: {e}")

    # Build digests
    tg_today, wa_today = build_today_digest()
    tg_week = build_week_digest()

    if not tg_today and not tg_week:
        log("אין פעילויות היום או השבוע — לא נשלח דייג'סט")
        log("=" * 50)
        return

    # Combine today + week overview
    full_message = ""
    if tg_today:
        full_message = tg_today
    if tg_week:
        if full_message:
            full_message += "\n\n" + "—" * 20 + "\n\n"
        full_message += tg_week

    # Send reminders for confirmed events happening today
    try:
        today_confirmed = db.get_tomorrow_confirmed()  # "tomorrow" was set at 07:00, but we check today
        # Actually let's get today's confirmed events
        today_iso = datetime.datetime.now(IL_TZ).date().strftime("%Y-%m-%d")
        conn = db.get_db()
        today_reminders = [dict(r) for r in conn.execute("""
            SELECT u.telegram_chat_id, e.title, e.event_time, e.end_time, e.location, e.link
            FROM confirmations c
            JOIN users u ON c.user_id = u.id
            JOIN events e ON c.event_id = e.event_id
            WHERE e.event_date_iso = ? AND u.active = 1 AND COALESCE(u.notify_reminder, 1) = 1
            ORDER BY e.event_time
        """, (today_iso,)).fetchall()]
        conn.close()

        # Group by user
        by_user = {}
        for r in today_reminders:
            cid = r["telegram_chat_id"]
            if cid not in by_user:
                by_user[cid] = []
            by_user[cid].append(r)

        reminder_sent = 0
        for chat_id, events_list in by_user.items():
            lines = ["⏰ <b>תזכורת! יש לכם פעילויות היום:</b>\n"]
            for ev in events_list:
                t = ev.get("event_time", "")
                title = (ev.get("title", "") or "")[:50]
                lines.append(f"• <b>{title}</b>")
                meta = []
                if t:
                    meta.append(f"🕐 {t}")
                    if ev.get("end_time"):
                        meta[-1] += f"-{ev['end_time']}"
                if ev.get("location"):
                    meta.append(f"📍 {ev['location']}")
                if meta:
                    lines.append("  " + " | ".join(meta))
                if ev.get("link"):
                    lines.append(f"  👉 {ev['link']}")  # plain URL — survives copy to WhatsApp
                lines.append("")
            lines.append("בהצלחה! 🎉")
            if send_telegram(chat_id, "\n".join(lines)):
                reminder_sent += 1
        if reminder_sent:
            log(f"נשלחו {reminder_sent} תזכורות לפעילויות היום")
    except Exception as e:
        log(f"שגיאה בתזכורות: {e}")

    # Send to all users who want digest
    users = db.get_all_active_users()
    digest_users = [u for u in users if u.get("notify_digest", 1)]

    log(f"שולח דייג'סט ל-{len(digest_users)} משתמשים")

    sent = 0
    for user in digest_users:
        if send_telegram(user["telegram_chat_id"], full_message):
            sent += 1

    log(f"נשלח בהצלחה ל-{sent}/{len(digest_users)} משתמשים")

    # Save WhatsApp version to file for dashboard
    if wa_today:
        wa_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latest_digest.txt")
        try:
            with open(wa_file, "w", encoding="utf-8") as f:
                f.write(wa_today)
            log("טקסט וואטסאפ נשמר ל-latest_digest.txt")
        except Exception as e:
            log(f"שגיאה בשמירת טקסט: {e}")

    stats = db.get_stats()
    log(f"סטטיסטיקות: {stats}")
    log("=" * 50)


if __name__ == "__main__":
    main()
