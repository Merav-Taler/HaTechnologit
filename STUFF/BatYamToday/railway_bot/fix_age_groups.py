"""
תיקון חירום: ניקוי גילאים שנוצרו מהיוריסטיקות הישנות.

המוטיבציה: עד עכשיו, אם בטקסט הופיעה המילה "תינוקות" — הסקרייפר תייג את האירוע
"0-1" אוטומטית, גם אם בפועל מדובר בטווח גיל אחר לחלוטין. אנשים נרשמו ושילמו
לפעילויות שלא מתאימות לילדיהם.

הסקריפט הזה רץ מחדש את AGE_PATTERNS המעודכן (רק מספרים מפורשים) על כל
האירועים שכבר במסד הנתונים, ומעדכן/מנקה את age_group בהתאם.
"""
import os
import sys
import sqlite3

# יבוא AGE_PATTERNS המעודכן מהסקרייפר
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from batyam_scraper import AGE_PATTERNS, detect_age_group

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "batyam_data.db",
)


def main(dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT id, event_id, title, age_group, raw_text FROM events"
    ).fetchall()

    cleared = 0
    updated = 0
    kept = 0
    for r in rows:
        old = r["age_group"] or ""
        text = (r["title"] or "") + " " + (r["raw_text"] or "")
        new = detect_age_group(text) or ""

        if old == new:
            kept += 1
            continue

        if not new and old:
            cleared += 1
            action = "נקה (היה היוריסטיקה)"
        elif new and old != new:
            updated += 1
            action = f"עדכן '{old}' → '{new}'"
        else:
            continue

        print(f"  [{r['event_id']}] {action}: {r['title'][:60]}")

        if not dry_run:
            cur.execute(
                "UPDATE events SET age_group = ? WHERE id = ?",
                (new or None, r["id"]),
            )

    if not dry_run:
        conn.commit()

    print()
    print(f"סה\"כ {len(rows)} אירועים נסרקו.")
    print(f"  ✓ ללא שינוי: {kept}")
    print(f"  ✏️  עודכנו לגיל אחר: {updated}")
    print(f"  🧹 נוקו (היו ניחוש שגוי): {cleared}")
    if dry_run:
        print("\n(הרצה יבשה — שום שינוי לא נשמר. הריצו ללא --dry-run כדי לבצע.)")
    conn.close()


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
