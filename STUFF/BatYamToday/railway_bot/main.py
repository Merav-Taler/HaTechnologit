"""
BatYam Today Bot — Flask entry point for Railway.

This is a thin HTTP wrapper around batyam_bot.handle_webhook().
Railway runs this module with gunicorn (see Procfile).

Endpoints:
  GET  /              — health check (returns bot name)
  GET  /healthz       — used by Railway's health probe and external pings
  POST /webhook       — Telegram webhook receiver
  POST /sync_db       — accepts a fresh batyam_data.db push from SiteGround
  GET  /pull_users    — returns users + user_preferences for SG digest sync-back
  GET  /preview_data.js   — serves the dashboard data file from /data
  GET  /dashboard_data.js — serves the admin dashboard data file from /data

Environment variables (set in Railway dashboard):
  TELEGRAM_BOT_TOKEN              — the bot token
  WEBHOOK_SECRET                  — shared with Telegram setWebhook
  ADMIN_CHAT_IDS                  — JSON array, e.g. [543343249]
  DASHBOARD_URL                   — https://batyamtoday.meravtech.com/
  BATYAM_DB_PATH                  — /data/batyam_data.db
  BATYAM_DATA_DIR                 — /data (preview_data.js + dashboard_data.js live here)
  SYNC_SECRET                     — shared with SG scraper for /sync_db + /pull_users auth
  ENABLE_APSCHEDULER              — "true" to wire up the in-process cron jobs
  RAILWAY_SCRAPER_ENABLED         — "true" to run batyam_scraper.main() every SCRAPER_INTERVAL_MIN
  RAILWAY_DIGEST_ENABLED          — "true" to run batyam_digest at 07:00 Asia/Jerusalem
  RAILWAY_DASHBOARD_ENABLED       — "true" to run generate_dashboard_data every 15 min
  SCRAPER_INTERVAL_MIN            — int, default 2

Logging goes to stdout (Railway captures it automatically).
"""

import hmac
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile

# --- 1. Write a batyam_secrets.json file BEFORE importing the bot. ---
# This way batyam_bot.py's load_secrets() picks it up naturally, and all the
# module-level globals (TELEGRAM_BOT_TOKEN, ADMIN_CHAT_IDS, DASHBOARD_URL) are
# set correctly on first import.

_secrets = {
    "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    "DASHBOARD_URL": os.environ.get("DASHBOARD_URL", "https://batyamtoday.meravtech.com/"),
    "WEBHOOK_SECRET": os.environ.get("WEBHOOK_SECRET", ""),
}
_admin_ids_raw = os.environ.get("ADMIN_CHAT_IDS", "[]")
try:
    _secrets["ADMIN_CHAT_IDS"] = json.loads(_admin_ids_raw)
except ValueError:
    _secrets["ADMIN_CHAT_IDS"] = []

_here = os.path.dirname(os.path.abspath(__file__))
_secrets_path = os.path.join(_here, "batyam_secrets.json")
# Write owner-only so a future shared-volume mistake or path-disclosure bug
# doesn't expose the token to other processes.
_old_umask = os.umask(0o077)
try:
    with open(_secrets_path, "w", encoding="utf-8") as _f:
        json.dump(_secrets, _f, ensure_ascii=False)
    os.chmod(_secrets_path, 0o600)
finally:
    os.umask(_old_umask)

# --- 2. Configure logging before importing the bot. ---

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("main")

# --- 3. Now import Flask and the bot module. ---

from flask import Flask, request, abort, jsonify  # noqa: E402
import batyam_bot  # noqa: E402

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
SYNC_SECRET = os.environ.get("SYNC_SECRET", "")
BATYAM_DB_PATH = os.environ.get("BATYAM_DB_PATH", "/data/batyam_data.db")
BATYAM_DATA_DIR = os.environ.get("BATYAM_DATA_DIR") or os.path.dirname(BATYAM_DB_PATH) or "/data"
# Make sure scraper / dashboard scripts pick up the same data dir if they look it up.
os.environ.setdefault("BATYAM_DATA_DIR", BATYAM_DATA_DIR)

log.info("Bot initialized: token=%s... admin_ids=%s",
         batyam_bot.TELEGRAM_BOT_TOKEN[:12] if batyam_bot.TELEGRAM_BOT_TOKEN else "(empty)",
         sorted(batyam_bot.ADMIN_CHAT_IDS))

# --- 4. Flask app ---

app = Flask(__name__)
# Reject any request body larger than 50MB before reading it (production DB is ~750KB).
# Flask returns 413 automatically once the limit is hit.
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": "BatYam Today Bot",
        "status": "ok",
        "bot": "BatYamTodayBot",
        # Railway מזריק את ה-SHA של ה-commit הפרוס — מאפשר לאמת דיפלוי מבחוץ.
        "commit": (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:7],
    })


@app.route("/healthz", methods=["GET"])
def healthz():
    """Lightweight health check for Railway."""
    return jsonify({"ok": True}), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive Telegram updates and dispatch to batyam_bot.handle_webhook()."""
    # Verify Telegram secret header (constant-time compare)
    if WEBHOOK_SECRET:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided, WEBHOOK_SECRET):
            log.warning("webhook: bad secret header from %s", request.remote_addr)
            abort(403)

    try:
        payload = request.get_json(force=True, silent=False)
    except Exception as e:
        log.warning("webhook: invalid JSON: %s", e)
        return "bad json", 400

    if not payload or "update_id" not in payload:
        log.warning("webhook: missing update_id")
        return "bad payload", 400

    log.info("webhook: update_id=%s", payload.get("update_id"))

    try:
        batyam_bot.handle_webhook(payload)
    except Exception as e:
        # Log but still return 200 — we don't want Telegram to retry on app bugs
        log.exception("handle_webhook failed: %s", e)

    return "ok", 200


# Tables that the SiteGround scraper owns; we copy these from the incoming snapshot.
# Everything else (users, user_preferences, notifications, confirmations, daily_stats)
# lives only on Railway and must be preserved across syncs.
SCRAPER_OWNED_TABLES = ("sections", "events")


@app.route("/sync_db", methods=["POST"])
def sync_db():
    """Accept a fresh batyam_data.db pushed by SiteGround scraper.

    Auth: X-Sync-Secret header must match SYNC_SECRET env var.
    Body: raw SQLite bytes.
    Behavior: copies SCRAPER_OWNED_TABLES rows from the incoming snapshot into
    the live Railway DB, leaving user/preferences/notifications untouched.
    """
    if not SYNC_SECRET:
        log.warning("sync_db: SYNC_SECRET not configured")
        abort(503)

    provided = request.headers.get("X-Sync-Secret", "")
    if not hmac.compare_digest(provided, SYNC_SECRET):
        log.warning("sync_db: bad secret from %s", request.remote_addr)
        abort(403)

    body = request.get_data(cache=False)
    if not body or len(body) < 1024:
        log.warning("sync_db: body too small (%d bytes) from %s", len(body), request.remote_addr)
        return jsonify({"ok": False, "error": "body too small"}), 400

    if not body.startswith(b"SQLite format 3\x00"):
        log.warning("sync_db: not a SQLite file (header=%r) from %s", body[:16], request.remote_addr)
        return jsonify({"ok": False, "error": "not a SQLite file"}), 400

    target_dir = os.path.dirname(BATYAM_DB_PATH) or "/data"
    try:
        os.makedirs(target_dir, exist_ok=True)

        # 1. Persist incoming snapshot to a temp file in the same dir as the live DB.
        fd, snapshot_path = tempfile.mkstemp(prefix=".sync_snap_", suffix=".db", dir=target_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(body)

            # 2. If the live DB does not exist yet, just promote the snapshot.
            if not os.path.exists(BATYAM_DB_PATH):
                os.replace(snapshot_path, BATYAM_DB_PATH)
                log.info("sync_db: bootstrap install (no existing DB), wrote %d bytes", len(body))
                return jsonify({"ok": True, "bytes": len(body), "mode": "bootstrap"}), 200

            # 3. Merge: copy SCRAPER_OWNED_TABLES from snapshot into live DB.
            stats = _merge_scraper_tables(BATYAM_DB_PATH, snapshot_path)

        finally:
            try:
                os.unlink(snapshot_path)
            except OSError:
                pass
    except Exception as e:
        log.exception("sync_db: merge failed: %s", e)
        return jsonify({"ok": False, "error": "merge failed"}), 500

    log.info("sync_db: merged %s from %s (%d bytes)", stats, request.remote_addr, len(body))
    return jsonify({"ok": True, "bytes": len(body), "mode": "merge", **stats}), 200


def _merge_scraper_tables(live_path, snapshot_path):
    """Replace SCRAPER_OWNED_TABLES rows in live DB with rows from snapshot.

    sections is upserted by primary key (so user_preferences.section_id stays valid).
    events is fully replaced (no FK references it).
    Runs inside one transaction so a failure leaves the live DB unchanged.
    """
    conn = sqlite3.connect(live_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=OFF")  # We control the order; FKs would block sections updates
        conn.execute(f"ATTACH DATABASE ? AS snap", (snapshot_path,))
        conn.execute("BEGIN IMMEDIATE")

        # sections: upsert by id so existing user_preferences.section_id refs stay valid.
        sec_cols = [r[1] for r in conn.execute("PRAGMA snap.table_info(sections)").fetchall()]
        if not sec_cols:
            raise RuntimeError("snapshot missing 'sections' table")
        col_list = ",".join(sec_cols)
        placeholders = ",".join(["?"] * len(sec_cols))
        new_secs = conn.execute(f"SELECT {col_list} FROM snap.sections").fetchall()
        sec_count = 0
        for row in new_secs:
            conn.execute(
                f"INSERT OR REPLACE INTO sections ({col_list}) VALUES ({placeholders})",
                row,
            )
            sec_count += 1

        # events: full replace. Nothing in this DB has a FK to events.id (notifications.event_id is TEXT).
        conn.execute("DELETE FROM events")
        ev_cols = [r[1] for r in conn.execute("PRAGMA snap.table_info(events)").fetchall()]
        if not ev_cols:
            raise RuntimeError("snapshot missing 'events' table")
        ev_col_list = ",".join(ev_cols)
        ev_count = conn.execute(
            f"INSERT INTO events ({ev_col_list}) SELECT {ev_col_list} FROM snap.events"
        ).rowcount

        conn.execute("COMMIT")
        return {"sections": sec_count, "events": ev_count}
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        try:
            conn.execute("DETACH DATABASE snap")
        except sqlite3.Error:
            pass
        conn.close()


@app.route("/preview_data.js", methods=["GET"])
def preview_data_js():
    """Serve the dashboard preview file generated by the in-process scraper.

    Cached for 30 s so a hot dashboard page doesn't hammer the file. Returns
    a small placeholder until the first scraper run produces the file.
    """
    p = os.path.join(BATYAM_DATA_DIR, "preview_data.js")
    if not os.path.exists(p):
        body = "const DATA = {events: [], stats: {}, today: '', filters: {locations: []}};"
        return body, 200, {
            "Content-Type": "application/javascript; charset=utf-8",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        }
    with open(p, "rb") as f:
        body = f.read()
    return body, 200, {
        "Content-Type": "application/javascript; charset=utf-8",
        "Cache-Control": "public, max-age=30",
        "Access-Control-Allow-Origin": "*",
    }


@app.route("/dashboard_data.js", methods=["GET"])
def dashboard_data_js():
    """Serve the admin dashboard file (generate_dashboard_data.py output)."""
    p = os.path.join(BATYAM_DATA_DIR, "dashboard_data.js")
    if not os.path.exists(p):
        return "const DASH = {};", 200, {
            "Content-Type": "application/javascript; charset=utf-8",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        }
    with open(p, "rb") as f:
        body = f.read()
    return body, 200, {
        "Content-Type": "application/javascript; charset=utf-8",
        "Cache-Control": "public, max-age=60",
        "Access-Control-Allow-Origin": "*",
    }


@app.route("/pull_users", methods=["GET"])
def pull_users():
    """Return Railway-side user-owned tables as JSON for SG to merge back.

    Auth: same X-Sync-Secret header as /sync_db.
    Body: JSON with 'users' and 'user_preferences' arrays. Other Railway-only
    tables (notifications, confirmations, daily_stats) are NOT exposed —
    they are large and only the bot itself needs them.
    """
    if not SYNC_SECRET:
        log.warning("pull_users: SYNC_SECRET not configured")
        abort(503)

    provided = request.headers.get("X-Sync-Secret", "")
    if not hmac.compare_digest(provided, SYNC_SECRET):
        log.warning("pull_users: bad secret from %s", request.remote_addr)
        abort(403)

    try:
        conn = sqlite3.connect(BATYAM_DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        users = [dict(r) for r in conn.execute("SELECT * FROM users").fetchall()]
        prefs = [dict(r) for r in conn.execute("SELECT * FROM user_preferences").fetchall()]
        conn.close()
    except Exception as e:
        log.exception("pull_users: read failed: %s", e)
        return jsonify({"ok": False, "error": "read failed"}), 500

    log.info("pull_users: served %d users + %d prefs to %s",
             len(users), len(prefs), request.remote_addr)
    return jsonify({"ok": True, "users": users, "user_preferences": prefs}), 200


# --- 5. APScheduler — runs scraper / digest / dashboard inside this process. ---
# Guarded by per-job env flags so we can roll out incrementally.
# Single-worker gunicorn (see Procfile) keeps each job from running twice.

ENABLE_APSCHEDULER = os.environ.get("ENABLE_APSCHEDULER", "false").lower() == "true"
SCRAPER_FLAG = os.environ.get("RAILWAY_SCRAPER_ENABLED", "false").lower() == "true"
DIGEST_FLAG = os.environ.get("RAILWAY_DIGEST_ENABLED", "false").lower() == "true"
DASHBOARD_FLAG = os.environ.get("RAILWAY_DASHBOARD_ENABLED", "false").lower() == "true"
SCRAPER_INTERVAL_MIN = int(os.environ.get("SCRAPER_INTERVAL_MIN", "2"))


def _job_scraper():
    log.info("[apscheduler] scraper run starting")
    try:
        import batyam_scraper
        batyam_scraper.main()
        log.info("[apscheduler] scraper run done")
    except Exception as e:
        log.exception("[apscheduler] scraper failed: %s", e)


def _job_digest():
    log.info("[apscheduler] digest run starting")
    try:
        import batyam_digest
        if hasattr(batyam_digest, "main"):
            batyam_digest.main()
        elif hasattr(batyam_digest, "send_digest"):
            batyam_digest.send_digest()
        log.info("[apscheduler] digest run done")
    except Exception as e:
        log.exception("[apscheduler] digest failed: %s", e)


def _job_dashboard():
    log.info("[apscheduler] generate_dashboard run starting")
    try:
        import generate_dashboard_data
        generate_dashboard_data.main()
        log.info("[apscheduler] generate_dashboard run done")
    except Exception as e:
        log.exception("[apscheduler] generate_dashboard failed: %s", e)


_scheduler = None
if ENABLE_APSCHEDULER:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
        from zoneinfo import ZoneInfo

        IL_TZ = ZoneInfo("Asia/Jerusalem")
        _scheduler = BackgroundScheduler(timezone=IL_TZ)

        if SCRAPER_FLAG:
            _scheduler.add_job(
                _job_scraper,
                IntervalTrigger(minutes=SCRAPER_INTERVAL_MIN),
                id="scraper", coalesce=True, max_instances=1, misfire_grace_time=120,
            )
            log.info("[apscheduler] scraper job scheduled every %d min", SCRAPER_INTERVAL_MIN)
        if DIGEST_FLAG:
            _scheduler.add_job(
                _job_digest,
                CronTrigger(hour=9, minute=0, timezone=IL_TZ),
                id="digest", coalesce=True, max_instances=1,
            )
            log.info("[apscheduler] digest job scheduled at 09:00 IL daily")
        if DASHBOARD_FLAG:
            _scheduler.add_job(
                _job_dashboard,
                IntervalTrigger(minutes=15),
                id="dashboard", coalesce=True, max_instances=1, misfire_grace_time=300,
            )
            log.info("[apscheduler] generate_dashboard job scheduled every 15 min")

        if SCRAPER_FLAG or DIGEST_FLAG or DASHBOARD_FLAG:
            _scheduler.start()
            log.info("[apscheduler] BackgroundScheduler started")
        else:
            log.info("[apscheduler] enabled but no jobs flagged on — idle")
    except Exception as e:
        log.exception("[apscheduler] init failed: %s", e)


# For local testing: `python main.py`
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
