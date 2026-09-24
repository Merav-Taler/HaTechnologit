# תוכנית מיגרציה מלאה ל-Railway

**תאריך:** 25 באפריל 2026
**מטרה:** להעביר את כל הקוד וה-DB ל-Railway, באותה ארכיטקטורה כמו דורין-בוט (שהוכח שעובד עם 4,800 משתמשים).
**עיקרון מנחה:** מיגרציה מדורגת עם **rollback בכל שלב**.

---

## מה גילינו על דורין

מבדיקה של dorin.app:
- האירוח: Railway (אותה פלטפורמה שלנו)
- Frontend: Vite + React
- Backend: Python/Node (ב-Railway, לא נחשף איזה)
- DB: כנראה SQLite על volume או PostgreSQL מבית Railway
- Analytics: Umami self-hosted

**המסקנה:** הארכיטקטורה הזו עובדת בקנה מידה ענק. צריך רק להעביר אליה.

---

## הארכיטקטורה החדשה

```
┌─────── Railway ───────┐         ┌────── SiteGround ──────┐
│                       │         │                        │
│  📦 Volume /data      │         │  🌐 meravtech.com      │
│   ├─ batyam_data.db   │         │   (אתר תדמית עסקי)     │
│                       │         │                        │
│  🤖 bot (web service) │         │  🌐 /batyam/           │
│      → /webhook       │         │   (דשבורד סטטי)        │
│      → /healthz       │         │   index.html           │
│                       │         │   preview_data.js ────┐│
│  🕷️ scraper (cron)    │ writes  │   (דרך CORS מ-Railway)││
│   כל 5 דק'             │ ──────► │                       ││
│                       │         │                        ││
│  📨 dispatcher (cron) │ pushes  │                        ││
│   לפי לו"ז             │ ──────► │   Telegram API        ││
│                       │         │                        ││
│  📅 digest (cron)     │         │                        ││
│   07:00 יומי           │ ──────► │   Telegram API        ││
│                       │         │                        ││
│  📊 dashboard_data    │ writes  │                        ││
│   כל 15 דק'            │ ──────► │   /api/preview ───────┘│
│                       │         │                        │
└───────────────────────┘         └────────────────────────┘

הבוט בטלגרם → webhook ל-Railway → קורא DB מקומית → תגובה מיידית
```

---

## מה מועבר, מה נשאר

### 🚂 עובר ל-Railway
- `batyam_bot.py` (כבר שם — נחזיר לגרסה הפשוטה שמשתמשת ב-SQLite ישירות)
- `batyam_db.py` (חוזר לגרסה המקורית — SQLite מקומי, לא HTTP)
- `batyam_scraper.py` (חדש על Railway, כ-cron service)
- `batyam_dispatcher.py` (חדש על Railway, כ-cron service)
- `batyam_digest.py` (חדש על Railway, כ-cron service)
- `generate_dashboard_data.py` (חדש על Railway)
- `batyam_data.db` (על persistent volume)

### 🏠 נשאר על SiteGround (ללא שינוי)
- `meravtech.com` (אתר תדמית עסקי) — לא נוגעים
- `public_html/batyam/index.html` (דשבורד) — שינוי קטן בלבד: URL של preview_data.js
- `public_html/batyam/` (תמונות, CSS, סטטי)
- `tg_echo.php`, `webhook.php` — נשארים כ-fallback (לא פעילים)

### 🗑️ ניקוי ב-SiteGround (אחרי שהמיגרציה יציבה)
- Cron של scraper/dispatcher/digest — מתבטל
- `api.php` — נמחק (לא צריך יותר)
- `webhook_payloads/` — נמחק (לא צריך יותר)

---

## עלויות צפויות

| סעיף | עלות חודשית |
|---|---|
| Railway compute (web bot, רץ 24/7) | ~$2 |
| Railway compute (cron services, פעמים מועטות) | ~$1 |
| Railway persistent volume (1GB) | $0.25 |
| Railway Postgres (אם נבחר במקום SQLite) | חינם עד 500MB |
| **סה"כ** | **~$3-5/חודש** |

ה-$5 קרדיט החינמי שמסופק על-ידי Railway מכסה את זה לחלוטין בחודשיים-שלושה הראשונים. אחר כך עוברים ל-Hobby tier שעולה $5/חודש.

---

## התוכנית המדויקת (5 שלבים)

### שלב 1 — גיבוי וכן Volume (45 דקות)

1. **גיבוי DB מ-SiteGround** ⬇️
   - להוריד את `batyam_data.db` מ-`meravtech.com/` (השורש)
   - לשמור ב-`workspace/backup/batyam_data.db.YYYY-MM-DD.bak`
2. **יצירת Volume ב-Railway**
   - בפרויקט הקיים → Service Settings → Volumes → New Volume
   - שם: `batyam-data`
   - Mount path: `/data`
   - גודל: 1GB (יותר מספיק)
3. **העלאת ה-DB ל-Volume**
   - דרך Railway CLI אם זמין במחשב, או דרך service זמני שמעלה את הקובץ
4. **שינוי env var:** `BATYAM_DB_PATH=/data/batyam_data.db`

**Rollback:** אם משהו נכשל — להשאיר הכל כמו שזה. הבוט הנוכחי עדיין רץ על SiteGround עם DB נפרד.

---

### שלב 2 — החזרת הבוט ל-SQLite מקומי (30 דקות)

המטרה: הבוט ב-Railway לא יקרא יותר ל-api.php (שחסום) אלא ישתמש בקובץ DB המקומי.

1. **שינוי `batyam_db.py`** — להחזיר לגרסה המקורית (SQLite ישירות)
2. **דחיפה ל-GitHub** — Railway ידפלוי אוטומטית
3. **בדיקה ב-Telegram** — שליחת `/today` ובדיקה שהבוט עונה

אחרי השלב הזה — הבוט עובד! עם DB מתאריך הגיבוי. שאר הסקריפטים עוד לא הועברו, אז אין עדכוני אירועים בזמן אמת. זה מצב ביניים ל-1-2 שעות הבאות.

**Rollback:** אם יש שגיאה — `setWebhook` חזרה לכתובת SiteGround וברירת המחדל הישנה (לא יעבוד אבל לא מזיק).

---

### שלב 3 — Scraper כ-cron service ב-Railway (45 דקות)

1. **יצירת service חדש ב-Railway** מאותו GitHub repo, אבל עם:
   - Start command: `python batyam_scraper.py`
   - Cron schedule: `*/5 * * * *` (כל 5 דקות)
   - אותו volume מותקן ב-`/data`
2. **בדיקה** — צפייה בלוגים, אימות ש-DB מתעדכן
3. **השוואה** — להריץ `SELECT COUNT(*) FROM events WHERE last_checked > now-10m` ולוודא שמתעדכן

**Rollback:** מבטלים את ה-service ב-Railway, מפעילים מחדש את ה-cron ב-SiteGround.

---

### שלב 4 — Dispatcher + Digest + Dashboard data (45 דקות)

1. **Dispatcher** — service על Railway עם schedule משלו
2. **Digest** — service על Railway עם cron `0 7 * * *` (07:00 יומי)
3. **Dashboard generator** — service על Railway עם cron `*/15 * * * *`
   - מייצר את `preview_data.js`
   - מאחסן ב-volume או חושף דרך endpoint `/preview_data.js` ב-Flask
4. **עדכון index.html ב-SiteGround** — שינוי שורה אחת ב-fetch URL ל-Railway

**Rollback:** מבטלים services, מפעילים מחדש cron ב-SiteGround.

---

### שלב 5 — ניקוי וייצוב (לאחר 24 שעות של ריצה תקינה)

1. **ביטול cron jobs ב-SiteGround:**
   - `batyam_scraper.py`
   - `batyam_dispatcher.py`
   - `batyam_digest.py`
2. **מחיקת קבצים מיותרים:**
   - `api.php` (לא נדרש יותר)
   - `webhook.php` (אפשר להשאיר fallback)
   - `tg_echo.php`
3. **תיעוד:** עדכון `קישורים.md` עם הארכיטקטורה החדשה

---

## נקודות החלטה לפני שמתחילים

### 1. SQLite או PostgreSQL?

| קריטריון | SQLite (על volume) | PostgreSQL (Railway) |
|---|---|---|
| שינויים בקוד | אפס | משמעותי (מעבר מ-`sqlite3` ל-`psycopg2`) |
| ביצועים | מעולים עד אלפי משתמשים | טובים יותר בקנה מידה גדול |
| עלות | $0.25/חודש (volume) | חינם עד 500MB |
| גיבוי אוטומטי | ידני | אוטומטי ב-Railway |

**המלצה:** SQLite — מינימום שינויים. נחליף ל-Postgres אם נצטרך בעתיד.

### 2. preview_data.js — איפה?

| אפשרות | יתרונות | חסרונות |
|---|---|---|
| Railway endpoint + CORS | פשוט, מתעדכן מיידית | תלות ב-Railway |
| Push ל-SiteGround כל 15 דק' | האתר 100% עצמאי | מורכבות SFTP/FTP |

**המלצה:** Railway endpoint עם CORS. אם Railway למטה — האתר עדיין נראה (סטטי) רק בלי דאטה עדכני.

### 3. סדר השלבים

האם להעביר הכל בבת אחת, או דרגתי?

**המלצה:** דרגתי — קל לאתר תקלות. שלב 1+2 מחזירים את הבוט לחיים. שלבים 3-4 משלימים את התמונה. שלב 5 ניקיון.

---

## סיכונים ומיטיגציה

| סיכון | סבירות | מיטיגציה |
|---|---|---|
| איבוד נתונים ב-DB | נמוכה | גיבוי בשלב 1 לפני כל פעולה |
| Volume של Railway נופל | נמוכה | גיבוי DB אוטומטי כל יום ל-S3/SiteGround |
| API של טלגרם נחסם | נמוכה מאוד | Railway IPs לא בעייתיים לטלגרם (לא כמו SiteGround) |
| Cron services לא רצים | בינונית בתחילה | צפייה בלוגים, אזהרות אמייל |
| עלות Railway מתפוצצת | נמוכה | נטרינג שימוש; אזעקה ב-$10 |

---

## מתי "סיימנו"?

המיגרציה תחשב מוצלחת כש:
- [ ] בוט מגיב להודעות תוך 1-3 שניות
- [ ] Dispatcher שולח התראות על אירועים חדשים
- [ ] Digest יומי מגיע ב-07:00
- [ ] דשבורד `meravtech.com/batyam` מציג נתונים עדכניים
- [ ] מעל 24 שעות של ריצה ללא שגיאות
- [ ] עלות חודשית מאומתת < $5

---

## הצעד הבא

מאשרים את התוכנית?
אם כן — מתחילים משלב 1 (גיבוי וכן volume).
