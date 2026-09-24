#!/usr/bin/env python3
"""Generate dashboard_data.js for the admin analytics dashboard."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import batyam_db as db

def main():
    stats = db.get_stats()
    history = db.get_stats_history(30)

    # Parse top_keywords JSON in history
    for h in history:
        if isinstance(h.get("top_keywords"), str):
            try:
                h["top_keywords"] = json.loads(h["top_keywords"])
            except:
                h["top_keywords"] = []

    # Get user preference breakdown
    conn = db.get_db()
    all_prefs = [dict(r) for r in conn.execute("""
        SELECT keyword, COUNT(*) as cnt FROM user_preferences
        WHERE active=1 GROUP BY keyword ORDER BY cnt DESC
    """).fetchall()]

    # Get hourly notification distribution
    hourly = [dict(r) for r in conn.execute("""
        SELECT strftime('%H', sent_at) as hour, COUNT(*) as cnt
        FROM notifications
        WHERE sent_at >= datetime('now', 'localtime', '-7 days')
        GROUP BY hour ORDER BY hour
    """).fetchall()]

    # Get daily new users
    daily_users = [dict(r) for r in conn.execute("""
        SELECT date(registered_at) as day, COUNT(*) as cnt
        FROM users
        WHERE registered_at >= datetime('now', 'localtime', '-30 days')
        GROUP BY day ORDER BY day
    """).fetchall()]

    # Get events by section
    by_section = [dict(r) for r in conn.execute("""
        SELECT s.name, COUNT(*) as cnt,
               SUM(CASE WHEN e.is_full=0 AND e.is_past=0 THEN 1 ELSE 0 END) as available
        FROM events e
        JOIN sections s ON e.section_id = s.id
        WHERE e.is_past=0
        GROUP BY s.name ORDER BY cnt DESC
    """).fetchall()]

    conn.close()

    data = {
        "stats": stats,
        "history": list(reversed(history)),
        "preferences": all_prefs,
        "hourly_notifications": hourly,
        "daily_users": daily_users,
        "events_by_section": by_section,
        "generated": db._today_il().isoformat(),
    }

    # Railway: write into BATYAM_DATA_DIR (served via /dashboard_data.js).
    # SG legacy: ../public_html/batyam/admin/dashboard_data.js
    # Local dev: same directory as scripts.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.environ.get("BATYAM_DATA_DIR") or os.path.dirname(os.environ.get("BATYAM_DB_PATH", ""))
    paths = []
    if data_dir and os.path.isdir(data_dir):
        paths.append(os.path.join(data_dir, "dashboard_data.js"))
    paths.extend([
        os.path.join(os.path.dirname(script_dir), "public_html", "batyam", "admin", "dashboard_data.js"),
        os.path.join(script_dir, "dashboard_data.js"),
    ])
    for out_path in paths:
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(f"const DASH = {json.dumps(data, ensure_ascii=False)};")
            print(f"Dashboard data written: {out_path}")
            break
        except FileNotFoundError:
            continue


if __name__ == "__main__":
    main()
