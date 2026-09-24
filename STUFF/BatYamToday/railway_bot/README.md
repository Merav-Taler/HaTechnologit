# BatYam Today Bot — Railway Deployment

Python Telegram bot for `@BatYamTodayBot`, deployed to Railway.
All database access goes over HTTP to `api.php` hosted on SiteGround
(where the real `batyam_data.db` lives — along with the scraper, dispatcher,
digest, and public dashboard, which are unchanged).

## Files

| File | Purpose |
|------|---------|
| `main.py` | Flask app; entry point; wires env vars into `batyam_bot` |
| `batyam_bot.py` | The actual bot logic (copied from SiteGround, 5 lines patched to use API helpers) |
| `batyam_db.py` | HTTP client that mirrors the original DB interface; calls `api.php` |
| `requirements.txt` | Python dependencies (Flask, gunicorn, requests) |
| `Procfile` | Gunicorn command for Railway |
| `railway.toml` | Railway config (health check, restart policy) |
| `.env.example` | Template for environment variables — **never commit real `.env`** |
| `.gitignore` | Excludes secrets and cache files from git |

## What's different from the original bot code

- `batyam_db.py` replaced with an HTTP client (same interface)
- 5 lines in `batyam_bot.py` where `db.get_db()` was used for custom SQL have
  been replaced with calls to new helper functions:
  - `db.get_events_by_date(date_iso)`
  - `db.get_all_events_for_matching()`
  - `db.get_event_by_id(event_id)`
  - `db.get_or_create_manual_section()`
- All 1,450+ other lines of bot logic — including Hebrew NLU, tracking,
  callbacks — are **unchanged**.

## Local testing

```bash
cd railway_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with real values
set -a; source .env; set +a
python main.py
```

Then POST a fake Telegram update:

```bash
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: $WEBHOOK_SECRET" \
  -d '{"update_id":1,"message":{"message_id":1,"from":{"id":543343249,"first_name":"Merav","is_bot":false},"chat":{"id":543343249,"type":"private"},"date":1700000000,"text":"/help"}}'
```

## Deployment to Railway

See `DEPLOY_GUIDE.md` in the parent folder for step-by-step deployment.

## Architecture

```
User → Telegram → Railway (/webhook) → batyam_bot.handle_webhook()
                                          │
                                          ├─ db.get_* / db.add_* / db.update_*
                                          │       │
                                          │       ▼
                                          │   batyam_db.py (HTTP client)
                                          │       │
                                          │       ▼
                                          │   https://meravtech.com/batyam/api.php
                                          │       │
                                          │       ▼
                                          │   batyam_data.db (SiteGround)
                                          │
                                          └─ send_telegram → api.telegram.org
                                                                │
                                                                ▼
                                                              User
```

Only the bot moved to Railway. Scraper, dispatcher, digest, and dashboard
stay on SiteGround with their existing cron jobs.

## Rollback

If something breaks after switching Telegram webhook to Railway:

```
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://meravtech.com/batyam/webhook.php&secret_token=<SECRET>"
```

Telegram will resume sending POSTs to SiteGround. The bot on Railway stays
idle (unused) but doesn't interfere.
