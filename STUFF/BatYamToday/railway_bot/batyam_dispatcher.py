#!/usr/bin/env python3
"""
מנוע שיגור התראות — BatYam Today
==================================
רץ אחרי הסורק. בודק אירועים עם מקום פנוי,
מתאים להעדפות משתמשים, ושולח התראות בטלגרם.
"""

import requests
import datetime
import zoneinfo
import os
import json
import re
import html as html_mod
import urllib.parse

import batyam_db as db


def build_whatsapp_share_url(event):
    """Build a wa.me URL with pre-filled plain-text message for sharing the event.

    טלגרם לא מאפשר העתקה נוחה של הודעה עם HTML — הקישור 'נחבא' מאחורי טקסט.
    כשמשתמש לוחץ על הכפתור הזה, וואטסאפ נפתח עם טקסט מוכן (כולל הקישור גלוי)
    שאפשר להדביק בכל קבוצה/שיחה.
    """
    title = event.get("title", "")
    date = event.get("event_date", "")
    time_str = event.get("event_time", "")
    end_time = event.get("end_time", "")
    location = event.get("location", "")
    age_group = event.get("age_group", "")
    link = event.get("link", "")

    lines = [f"📌 {title}"]
    when = []
    if date:
        when.append(f"📅 {date}")
    if time_str:
        t = f"🕐 {time_str}"
        if end_time:
            t += f"-{end_time}"
        when.append(t)
    if when:
        lines.append(" | ".join(when))
    if location:
        lines.append(f"📍 {location}")
    if age_group:
        lines.append(f"👶 גילאי {age_group}")
    if link:
        lines.append("")
        lines.append(f"להרשמה: {link}")

    # Credit travels with every share — plain text so it survives any platform.
    lines.append("")
    lines.append("✍️ נוצר ע\"י מירב טלר ושדי | הטכנולוגית")
    lines.append("כל הפעילויות בבת ים: https://meravtech.com/batyam/")

    text = "\n".join(lines)
    return f"https://wa.me/?text={urllib.parse.quote(text)}"

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

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batyam_dispatcher.log")


def log(msg):
    line = f"[{datetime.datetime.now(IL_TZ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_shabbat():
    """Check if it's Shabbat (Friday 16:00 to Saturday 20:00 Israel time)."""
    now = datetime.datetime.now(IL_TZ)
    weekday = now.weekday()  # 0=Monday, 4=Friday, 5=Saturday
    hour = now.hour
    if weekday == 4 and hour >= 16:  # Friday after 16:00
        return True
    if weekday == 5 and hour < 20:  # Saturday before 20:00
        return True
    return False


def is_quiet_hours(user):
    """Check if it's quiet hours for this user (includes Shabbat)."""
    # Shabbat — quiet for everyone by default
    if is_shabbat():
        return True

    now = datetime.datetime.now(IL_TZ)
    current_time = now.strftime("%H:%M")
    quiet_start = user.get("quiet_start", "22:00") or "22:00"
    quiet_end = user.get("quiet_end", "07:00") or "07:00"

    if quiet_start > quiet_end:  # crosses midnight
        return current_time >= quiet_start or current_time < quiet_end
    else:
        return quiet_start <= current_time < quiet_end


def send_telegram(chat_id, message, reply_markup=None):
    # קרדיט בכל הודעה, תמיד (בקשה מפורשת של מירב) — אם הפורמט לא הוסיף, מוסיפים כאן.
    if "הטכנולוגית" not in message:
        message = message + "\n\n<i>✍️ נוצר על ידי מירב טלר ושדי | הטכנולוגית</i>\nmeravtech.com"
    """Send a Telegram message to a specific user."""
    if not TELEGRAM_BOT_TOKEN:
        log("  טלגרם לא מוגדר - מדלג")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={k: v for k, v in {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": reply_markup,
            }.items() if v is not None},
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        else:
            log(f"  שגיאת טלגרם ({resp.status_code}): {resp.text[:100]}")
            return False
    except Exception as e:
        log(f"  שגיאת טלגרם: {e}")
        return False


def format_event_message(event, matched_keyword=None):
    """Format a single event for Telegram with explanation."""
    title = html_mod.escape(event.get("title", "")[:60])
    date = event.get("event_date", "")
    time_str = event.get("event_time", "")
    end_time = event.get("end_time", "")
    reg = event.get("registered", 0)
    cap = event.get("capacity", 0)
    link = event.get("link", "")
    location = event.get("location", "")

    spots = cap - reg if cap > reg else 0

    was_full = event.get("was_full", 0)

    parts = []
    # Headline:
    #   was_full == True  → user is tracking THIS event because it was full;
    #                       now a spot opened up. Use the "spot opened" wording.
    #   was_full == False → this is a new event matching a topic/keyword the
    #                       user follows. Use the "newly published" wording.
    if was_full:
        if matched_keyword:
            parts.append(f"🔥 <b>מקום התפנה!</b> ({html_mod.escape(matched_keyword)})")
        else:
            parts.append(f"🔥 <b>מקום התפנה!</b>")
    else:
        if matched_keyword:
            parts.append(f"📢 <b>פורסמה פעילות חדשה בתחום שעוקבים: {html_mod.escape(matched_keyword)}</b>")
        else:
            parts.append(f"📢 <b>פורסמה פעילות חדשה</b>")
    parts.append(f"📌 <b>{title}</b>")

    meta = []
    if time_str:
        t = f"🕐 {time_str}"
        if end_time:
            t += f"-{end_time}"
        meta.append(t)
    if date:
        meta.append(f"📅 {date}")
    if location:
        meta.append(f"📍 {location}")
    age_group = event.get("age_group", "")
    if age_group:
        meta.append(f"👶 גיל {age_group}")
    if cap > 0:
        meta.append(f"👥 {reg}/{cap} ({spots} פנויים)")
    if meta:
        parts.append(" | ".join(meta))

    if link:
        # Plain URL (not an <a> anchor) — users copy-paste these messages into
        # WhatsApp and other apps; anchor links lose their URL on copy.
        parts.append(f"\n👉 להרשמה: {link}")

    # Tiny attribution so anyone receiving an unprompted alert knows the
    # source. Kept on its own line at the bottom, italicized.
    # Don't remove without asking Merav.
    # Plain text + bare URL (no <a> anchor): users copy these messages into
    # WhatsApp, and anchor links lose both the URL and the credit on paste.
    # Telegram auto-links the bare domain on its own line, so it stays clickable.
    parts.append('\n<i>✍️ נוצר על ידי מירב טלר ושדי | הטכנולוגית</i>\nmeravtech.com')

    return "\n".join(parts)


def _match_keyword(event, user_prefs):
    """Find which user preference matched this event. Returns keyword or None.

    Delegates to db.event_matches_keyword — the same matcher used to decide WHO
    gets notified — so the label always agrees with the actual match reason."""
    for pref in user_prefs:
        if db.event_matches_keyword(pref["keyword"], event):
            return pref["keyword"]
    return None


def format_event_line(event):
    """Format a single event as a compact block for batch digest messages."""
    title = html_mod.escape(event.get("title", "")[:80])
    date = event.get("event_date", "")
    time_str = event.get("event_time", "")
    location = event.get("location", "")
    age_group = event.get("age_group", "")
    link = event.get("link", "")

    line = f"📌 <b>{title}</b>"
    meta = []
    if date:
        meta.append(f"📅 {date}")
    if time_str:
        meta.append(f"🕐 {time_str}")
    if location:
        meta.append(f"📍 {html_mod.escape(location)}")
    if age_group:
        meta.append(f"👶 גיל {html_mod.escape(age_group)}")
    if meta:
        line += "\n   " + " | ".join(meta)
    if link:
        # Plain URL so the message survives copy-paste to WhatsApp (see format_event_message)
        line += f'\n   👉 להרשמה: {link}'
    return line


def format_batch_message(user_name, events_with_keywords):
    """Format a batched digest of multiple events for one user.

    events_with_keywords: list of (event, matched_keyword) tuples.
    """
    name = user_name or "שלום"
    n = len(events_with_keywords)
    parts = [f"📬 <b>שלום {html_mod.escape(name)}, יש {n} פעילויות חדשות עבורך</b>", ""]

    # קבץ לפי מילת חיפוש
    by_kw = {}
    for ev, kw in events_with_keywords:
        key = kw or "(כללי)"
        by_kw.setdefault(key, []).append(ev)

    # הגבל לאורך הודעה של טלגרם (4096 תווים). הקישורים גלויים עכשיו (לא עוגני
    # HTML) ולכן כל אירוע ארוך יותר — 15 אירועים זה הגבול הבטוח.
    MAX_EVENTS = 15
    shown = 0
    truncated = 0
    for kw, evs in by_kw.items():
        parts.append(f"━━━ <b>בנושא שעוקבים: {html_mod.escape(kw)}</b> ({len(evs)}) ━━━")
        for ev in evs:
            if shown >= MAX_EVENTS:
                truncated += 1
                continue
            parts.append(format_event_line(ev))
            parts.append("")
            shown += 1

    if truncated:
        parts.append(f"<i>...ועוד {truncated} פעילויות נוספות. ראו את כולן באתר:</i>")
        parts.append('<a href="https://meravtech.com/batyam/">meravtech.com/batyam</a>')

    parts.append("")
    parts.append('<i>✍️ נוצר על ידי <a href="https://meravtech.com">מירב טלר ושדי | הטכנולוגית</a></i>')
    return "\n".join(parts)


def dispatch():
    """Aggregate matches per user, send ONE consolidated message each.

    במקום הודעה לכל אירוע (פלאד של עשרות הודעות אחרי הפסקה בסקרייפר),
    אוספים את כל ההתאמות לכל משתמש ושולחים הודעה אחת מרוכזת.
    """
    log("=" * 50)
    log("BatYam Today — שיגור התראות")

    # Kill switch: when DISPATCHER_ENABLED=false, run in dry-run mode — log what
    # WOULD be sent without actually calling Telegram. Lets us re-enable the
    # scraper without spamming users while we verify a code change is safe.
    # שלוש מצבי הפעלה:
    #   normal (DISPATCHER_ENABLED=true): שולח טלגרם + מסמן כנשלח. ברירת המחדל.
    #   dry-run (DISPATCHER_ENABLED=false): רק רושם בלוג. שום שינוי. לבדיקות.
    #   catch-up (DISPATCHER_CATCH_UP_SKIP=true): לא שולח, אבל כן מסמן כנשלח —
    #     משמש פעם אחת אחרי עצירה ממושכת כדי "לדלג" על הצטברות אירועים בלי
    #     להציף משתמשים. אחרי הריצה הזו, חוזרים ל-normal והבוט שולח רק אירועים
    #     באמת חדשים שיתגלו מכאן ולהבא.
    enabled = os.environ.get("DISPATCHER_ENABLED", "true").lower() not in ("false", "0", "no")
    catch_up_skip = os.environ.get("DISPATCHER_CATCH_UP_SKIP", "false").lower() in ("true", "1", "yes")
    dry_run = not enabled and not catch_up_skip

    available_events = db.get_available_events()
    users = db.get_all_active_users()

    log(f"אירועים עם מקום: {len(available_events)}, משתמשים פעילים: {len(users)}")
    if catch_up_skip:
        log("⏭️  DISPATCHER_CATCH_UP_SKIP=true — מסמן הכל כנשלח בלי לשלוח בפועל")
    elif dry_run:
        log("⚠️  DISPATCHER_ENABLED=false — מצב dry-run: לא יישלחו התראות בפועל")

    if not available_events or not users:
        log("אין אירועים או משתמשים — יוצא")
        log("=" * 50)
        return

    # שלב 1: צבירת אירועים לפי משתמש
    per_user = {}  # user_id → {"user": user_dict, "events": [(event, matched_kw), ...]}
    skipped_already = 0
    skipped_quiet = 0

    for event in available_events:
        matched_users = db.get_users_for_event(event)
        if event.get("was_full"):
            db.clear_was_full(event["event_id"])

        for user in matched_users:
            uid = user["id"]
            if db.was_notified(uid, event["event_id"]):
                skipped_already += 1
                continue
            if db.is_confirmed(uid, event["event_id"]):
                skipped_already += 1
                continue
            if is_quiet_hours(user):
                skipped_quiet += 1
                continue
            if not user.get("notify_instant", 1):
                continue

            user_prefs = db.get_user_preferences(uid)
            matched_kw = _match_keyword(event, user_prefs)

            slot = per_user.setdefault(uid, {"user": user, "events": []})
            slot["events"].append((event, matched_kw))

    # שלב 2: שלח התראה נפרדת לכל אירוע (UX מיידי עם כפתורי פעולה).
    # בריצה רגילה כל 2 דק' יש 0-2 אירועים חדשים — אין בעיית flood.
    # מצב catch-up (אם מופעל) מסמן הכל כנשלח בלי לשלוח. הפורמט המרוכז
    # (format_batch_message) שמור לשימוש עתידי בדיג'סט יומי וכד'.
    sent_users = 0
    sent_events = 0
    for uid, slot in per_user.items():
        user = slot["user"]
        events_with_kw = slot["events"]
        n = len(events_with_kw)

        if dry_run:
            sent_users += 1
            sent_events += n
            log(f"  [dry-run] היה נשלח ל-{user.get('name', user['telegram_chat_id'])}: {n} אירועים נפרדים")
            for ev, _ in events_with_kw[:3]:
                log(f"    • {ev['title'][:60]}")
            if n > 3:
                log(f"    ועוד {n - 3} אירועים...")
            continue

        if catch_up_skip:
            for ev, _ in events_with_kw:
                db.log_notification(uid, ev["event_id"], "telegram")
            sent_users += 1
            sent_events += n
            log(f"  [catch-up] סומנו כנשלחו ל-{user.get('name', user['telegram_chat_id'])}: {n} אירועים")
            continue

        # ברירת מחדל: שליחה נפרדת לכל אירוע
        # הגנת הצפה: בריצה רגילה יש 0-2 אירועים חדשים למשתמש והודעה נפרדת עם
        # כפתורים היא ה-UX הטוב ביותר. אבל אחרי שינוי בלוגיקת ההתאמה (למשל
        # הוספת מילים נרדפות) עשרות אירועים "ישנים" מתאימים פתאום בבת אחת —
        # במקרה כזה שולחים הודעה מרוכזת אחת במקום להציף בעשרות הודעות.
        MAX_INDIVIDUAL = 3
        user_sent = 0
        if len(events_with_kw) > MAX_INDIVIDUAL:
            batch_msg = format_batch_message(user.get("name"), events_with_kw)
            if send_telegram(user["telegram_chat_id"], batch_msg, reply_markup={
                "inline_keyboard": [[
                    {"text": "⚙️ הגדרות מעקב", "callback_data": "cmd:settings"},
                ]]
            }):
                for event, _ in events_with_kw:
                    db.log_notification(uid, event["event_id"], "telegram")
                user_sent = len(events_with_kw)
                log(f"  נשלחה הודעה מרוכזת ל-{user.get('name', user['telegram_chat_id'])}: {user_sent} אירועים")
        else:
            for event, matched_kw in events_with_kw:
                msg = format_event_message(event, matched_keyword=matched_kw)
                share_url = build_whatsapp_share_url(event)
                reply_markup = {
                    "inline_keyboard": [
                        [
                            {"text": "✅ נרשמתי!", "callback_data": f"confirm:{event['event_id']}"},
                            {"text": "🔇 עצרו", "callback_data": f"mute:{event['event_id']}"},
                        ],
                        [
                            {"text": "📤 שתפו בוואטסאפ", "url": share_url},
                        ],
                        [
                            {"text": "⚙️ הגדרות מעקב", "callback_data": "cmd:settings"},
                        ],
                    ]
                }
                if send_telegram(user["telegram_chat_id"], msg, reply_markup=reply_markup):
                    db.log_notification(uid, event["event_id"], "telegram")
                    user_sent += 1
                    log(f"  נשלח ל-{user.get('name', user['telegram_chat_id'])}: {event['title'][:50]}")
        if user_sent:
            sent_users += 1
            sent_events += user_sent

    if catch_up_skip:
        log(f"סיכום [catch-up]: {sent_events} אירועים סומנו כנשלחו ל-{sent_users} משתמשים בלי לשלוח בפועל. {skipped_already} כבר היו מסומנים, {skipped_quiet} בשעות שקט.")
    elif dry_run:
        log(f"סיכום [dry-run]: היו נשלחות {sent_events} התראות ל-{sent_users} משתמשים. {skipped_already} כבר נשלחו, {skipped_quiet} בשעות שקט.")
    else:
        log(f"סיכום: {sent_events} התראות נשלחו ל-{sent_users} משתמשים. {skipped_already} כבר נשלחו, {skipped_quiet} בשעות שקט.")
    log("=" * 50)


if __name__ == "__main__":
    dispatch()
