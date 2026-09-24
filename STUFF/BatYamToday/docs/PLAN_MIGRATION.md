# תוכנית מיגרציה — BatYam Today Bot → Railway

**עדכון אחרון:** 24 באפריל 2026
**מטרה:** להעביר את קבלת ההודעות מטלגרם ל-Railway, בלי לפגוע בשום דבר אחר.
**מסלול שנבחר:** A — מיגרציה חלקית. רק הבוט עובר. אתר `meravtech.com` והאתר העסקי שלך נשארים ב-SiteGround.

---

## השפעת המיגרציה על CPU של SiteGround

זה אחד היעדים המרכזיים של המהלך — לא להקל על הבוט בלבד, אלא **להוריד את העומס על SiteGround**.

**מה היה קורה קודם (המצב שגרם ל-CPU overload):**
- `batyam_bot.py --poll` רץ **כל דקה** ב-cron
- כל הרצה עשתה long-poll של עד 4 דק' (פקודת `getUpdates` עם timeout גבוה)
- בכל רגע נתון — **4 תהליכי Python מקבילים** פעילים על השרת, כל אחד טוען 1,500+ שורות קוד, פותח חיבור TCP ל-telegram.org, מחזיק handle פתוח ל-`batyam_data.db`
- בנוסף, webhook.php היה spawner של Python על **כל הודעה נכנסת** (מודל לא טוב תחת עומס)

**מה יהיה אחרי המיגרציה:**
- `batyam_bot.py --poll` cron **מבוטל לחלוטין**
- webhook.php נשאר בקובץ אבל **לא נרשם אצל טלגרם** — אף פעם לא נקרא יותר
- **אף פעילות של הבוט לא רצה יותר על SiteGround**

**מה נשאר לרוץ על SiteGround:**

| רכיב | תדירות | עומס CPU משוער |
|---|---|---|
| `batyam_scraper.py` | כל 5 דק' | 5-15 שניות CPU לכל הרצה — זניח |
| `batyam_dispatcher.py` | לפי cron (כל 15 דק' בד"כ) | 2-5 שניות CPU — זניח |
| `batyam_digest.py` | פעם ביום (07:00) | 10-30 שניות CPU — זניח |
| `generate_dashboard_data.py` | כל 15 דק' | שניות בודדות — זניח |
| `api.php` (חדש) | לפי בקשות מהבוט | millisecond-level — זניח |
| Apache + PHP של האתר | continuous | כרגיל, לא מושפע |

**הערכה איכותית של החיסכון:** ירידה של **60-80% בממוצע CPU** של השרת. כל "הרעש" הקבוע של הבוט נעלם. שאר המשימות הן batch processing קצרצר שלא מעמיס.

זה גם פותר ברמה עקרונית את הבעיה שגרמה לך להגיע לכאן מלכתחילה.

---

---

## עקרון יסוד

- **אותו בוט בטלגרם** (`@BatYamTodayBot`) — הטוקן לא משתנה
- **אותם משתמשים** — לא מזיזים, לא מודיעים, לא מבקשים להירשם מחדש
- **אותן הפקודות** — `/today`, `/track`, "מה יש היום?" וכו' — קוד זהה
- **אותו NLU** — הבנת עברית חופשית — קוד Python קיים, ללא שינוי
- **אותו אתר** — `meravtech.com/batyam/` בכלל לא נוגעים
- **מה שמשתנה:** רק *איפה* ה-Python רץ. מ-SiteGround → ל-Railway.

מבחינת המשתמש הקיים: **שום שינוי נראה לעין**. ממשיכים לשלוח הודעות לאותו הבוט ולקבל תשובות כרגיל.

---

## לפני ואחרי

### לפני (היום)
```
משתמש → Telegram → meravtech.com/batyam/webhook.php → python3 batyam_bot.py → sendMessage → משתמש
                                   ❌ WAF של SiteGround בולע את ה-POST
```

### אחרי
```
משתמש → Telegram → batyam-bot.up.railway.app/webhook → Flask → handle_webhook() → sendMessage → משתמש
                                   ✅ Railway לא חוסם את טלגרם

# DB:
בוט ב-Railway → GET https://meravtech.com/batyam/api.php?... → JSON → תשובה
```

---

## מה נשאר על SiteGround (לא נוגעים)

| רכיב | תפקיד | סטטוס |
|---|---|---|
| `public_html/batyam/` (index.html + preview_data.js + images) | האתר | ✓ ללא שינוי |
| `scripts/batyam_scraper.py` | סורק קוינג | ✓ ללא שינוי |
| `scripts/batyam_dispatcher.py` | שולח push notifications | ✓ ללא שינוי |
| `scripts/batyam_digest.py` | תקציר יומי 07:00 | ✓ ללא שינוי |
| `scripts/batyam_db.py` | ממשק DB | ✓ ללא שינוי |
| `scripts/generate_dashboard_data.py` | מייצר את preview_data.js | ✓ ללא שינוי |
| `batyam_data.db` | מסד נתונים | ✓ ללא שינוי |
| `batyam_secrets.json` | טוקנים | ✓ ללא שינוי |
| ה-cron jobs: scraper, dispatcher, digest | תזמונים | ✓ ללא שינוי |

## מה עובר ל-Railway

רק הקוד של `batyam_bot.py` (קבלת הודעות נכנסות).

## מה חדש (שני קבצים)

1. **`public_html/batyam/api.php`** חדש ב-SiteGround — endpoint קריאה-בלבד שהבוט ב-Railway קורא ממנו נתונים
2. **`main.py`** חדש ב-Railway — מעטפת Flask דקה שמקבלת POST מטלגרם וקוראת ל-`handle_webhook()` הקיים

---

## שלבים מפורטים

### שלב 0 — הכנה מקומית (30 דק')

- [ ] יצירת repo פרטי ב-GitHub (אם עוד אין): `batyam-bot-railway`
- [ ] העתקת הקוד הרלוונטי:
  - `batyam_bot.py` (הקיים, ללא שינוי)
  - `batyam_db.py` (צריך לשנות: במקום קריאה ישירה ל-sqlite, להפנות ל-api.php)
  - קובץ חדש `main.py` — מעטפת Flask
  - `requirements.txt` — רשימת תלויות Python
  - `Procfile` או `railway.toml` — איך Railway מריץ את האפליקציה
  - `.env.example` — רשימת משתני סביבה (ללא ערכים)

### שלב 1 — כתיבת `api.php` ב-SiteGround (1 שעה)

קובץ PHP בודד שמייצא פעולות קריאה על `batyam_data.db`:

```
GET /batyam/api.php?action=events_today&api_key=XXX
GET /batyam/api.php?action=events_by_date&date=2026-04-25&api_key=XXX
GET /batyam/api.php?action=search&q=יצירה&api_key=XXX
GET /batyam/api.php?action=user_tracks&chat_id=543343249&api_key=XXX
POST /batyam/api.php?action=add_track&chat_id=...&api_key=XXX
POST /batyam/api.php?action=remove_track&... (וכד')
```

- אימות דרך `api_key` בוsecrets.json (לא ה-webhook_secret — חדש, נפרד)
- החזרת JSON
- הרשאות DB 600 נשמרות (PHP רץ בהקשר השרת)
- אם יש שאילתות שמשתמשות בפונקציות Python ספציפיות — נעביר אותן ל-api.php כ-endpoint נפרד, או נממש אותן מחדש בבוט

### שלב 2 — הכנת הבוט ל-Railway (2 שעות)

- [ ] כתיבת `main.py`:
  ```python
  from flask import Flask, request
  import batyam_bot
  app = Flask(__name__)

  @app.post("/webhook")
  def webhook():
      # אימות secret token של טלגרם
      # קריאה ל-batyam_bot.handle_webhook(payload)
      # החזרת 200
  ```
- [ ] שינוי `batyam_db.py`: במקום קריאה ישירה ל-sqlite, לקרוא ל-api.php
- [ ] `requirements.txt`: flask, requests, (וכו')
- [ ] בדיקה מקומית: להריץ את Flask מקומית ולשלוח POST ידני

### שלב 3 — הקמת Railway (1 שעה)

- [ ] פתיחת חשבון ב-railway.app (מופעל דרך GitHub)
- [ ] New Project → Deploy from GitHub repo → בחירת ה-repo
- [ ] Railway מזהה אוטומטית Python ובונה container
- [ ] הגדרת Environment Variables:
  - `TELEGRAM_BOT_TOKEN` (אותו אחד)
  - `WEBHOOK_SECRET` (אותו אחד שכבר ב-secrets.json)
  - `API_URL` = `https://meravtech.com/batyam/api.php`
  - `API_KEY` = (חדש, נייצר)
  - `ADMIN_CHAT_IDS` = 543343249
- [ ] קבלת URL ציבורי, למשל `batyam-bot-production.up.railway.app`
- [ ] בדיקה: `curl POST` ידני ל-`/webhook` עם payload פיקטיבי

### שלב 4 — בדיקה בצד (30 דק')

**חשוב: לפני שמזיזים את ה-webhook של טלגרם אליו — לבדוק שהכל עובד.**

- [ ] שליחת POST ידני ל-Railway עם payload של "מה יש היום?"
- [ ] לוודא שהבוט מזהה את חשבון הניסוי ולא שולח הודעות אמיתיות (או: להשתמש ב-chat_id של Merav לבדיקה מבוקרת)
- [ ] לאמת ש-api.php ב-SiteGround מחזיר נתונים תקינים
- [ ] להסתכל בלוגים ב-Railway ולוודא שאין שגיאות

### שלב 5 — החלפת ה-webhook בטלגרם (5 דקות)

- [ ] `deleteWebhook` (מסיר את meravtech.com)
- [ ] `setWebhook` ל-URL של Railway עם ה-secret token
- [ ] `getWebhookInfo` לאימות

**מהרגע הזה — כל ההודעות של המשתמשים עוברות ל-Railway.**

### שלב 6 — מוניטורינג (יום-יומיים)

- [ ] לעקוב אחרי הלוגים ב-Railway 24 שעות ראשונות
- [ ] לבדוק שכל הפקודות עובדות: `/today`, `/week`, `/track`, "מה יש היום?", etc.
- [ ] לוודא שהדיספצ'ר (push) ממשיך לעבוד (הוא ב-SiteGround, לא אמור להיות מושפע)

---

## תוכנית Rollback (חזרה אחורה אם משהו נשבר)

אם משהו לא עובד אחרי שלב 5:

```
# החזרת webhook חזרה לשרת הישן
setWebhook(url=https://meravtech.com/batyam/webhook.php, secret_token=XXX)
```

זהו. בעיות ל-Railway לא משפיעות על האתר, scraper, dispatcher או digest — הם ב-SiteGround ולא תלויים.

---

## עלויות צפויות

- **Railway Free Tier**: $5 קרדיט/חודש (יותר מדי לבוט קטן)
- **Railway Hobby**: $5/חודש אם עוברים (כנראה לא יידרש בתחילה)
- בהערכה: **0-$5/חודש**

---

## פתיחת הלוגיקה ב-api.php

להלן רשימה ראשונית של endpoints שה-api.php יצטרך לתמוך בהם (נבנה סופית לפי מה שהבוט משתמש):

**קריאות (GET):**
- `events_today` — כל האירועים של היום
- `events_by_date?date=YYYY-MM-DD` — אירועים בתאריך ספציפי
- `events_this_week` — אירועים בשבוע הקרוב
- `search?q=TEXT&age=N&location=...` — חיפוש חופשי
- `user_profile?chat_id=X` — העדפות של משתמש
- `user_tracks?chat_id=X` — רשימת מעקבים

**כתיבות (POST):**
- `start_user` — יצירת משתמש חדש (`/start`)
- `add_track` — הוספת מעקב
- `remove_track` — הסרת מעקב
- `update_preferences` — שינוי העדפות
- `log_interaction` — לתיעוד בלבד

---

## סיכונים והקלה

| סיכון | הסתברות | השפעה | הקלה |
|---|---|---|---|
| api.php לא מחזיר כל הנתונים שהבוט צריך | בינונית | בינונית | לבדוק מראש בקוד של batyam_bot.py את כל השאילתות |
| Railway יקר יותר מהצפוי | נמוכה | נמוכה | יש התראה ב-$4 לפני שחוצים את החינמי |
| WAF של SiteGround יחסום גם את api.php | נמוכה מאוד | בינונית | api.php זה GET רגיל, לא דומה ל-Telegram POST; יש לנו כבר 100+ hits יומיים של preview_data.js שעובדים |
| הבוט נתקע במהלך deploy | בינונית | נמוכה | Railway תומך ב-zero-downtime deploys, ו-webhook מחזיר 200 גם על שגיאה (טלגרם לא מתנסה שוב מייד) |
| שכחנו migration של נתוני משתמשים | נמוכה | בינונית | כל נתוני המשתמשים נשארים ב-batyam_data.db על SiteGround, הבוט ניגש אליהם דרך api.php — לא עוברים כלום |

---

## שאלות שעדיין לטיפול (אחר כך)

- מה עם ה-cron של `batyam_bot.py --poll` שעדיין רשום? נבטל אותו (לא צריך יותר)
- האם להסיר את `tg_echo.php` מהשרת? (כן, מומלץ לניקיון)
- האם להחליף את ה-`WEBHOOK_SECRET`? (אופציונלי, אבל חכם)
- האם להגן על api.php ע"י IP whitelist של Railway? (מומלץ — Railway יש להם טווח IPs קבוע)

---

## זמן משוער

- שלב 0: 30 דק'
- שלב 1 (api.php): 1-2 שעות
- שלב 2 (main.py + שינויים ב-batyam_db): 2-3 שעות
- שלב 3 (Railway deploy): 1 שעה
- שלב 4 (בדיקות): 30 דק' — 1 שעה
- שלב 5 (החלפת webhook): 5 דק'
- שלב 6 (מוניטורינג): פסיבי

**סה"כ: יום עבודה רגוע (6-8 שעות פעילות).**

---

## הבא בתור

ברגע שתאשרי את התוכנית הזאת — אני מתחיל:

1. כתיבת `api.php` (קובץ ממוקד, ~200 שורות)
2. כתיבת `main.py` (מעטפת Flask, ~50 שורות)
3. שינויים ב-`batyam_db.py` להפנות את כל הקריאות ל-api.php
4. `requirements.txt`, `Procfile`, `README.md` לכל הקבצים
5. הדרכה לפתיחת חשבון Railway וה-deploy הראשון

לא נוגעים בקוד הקיים של `batyam_bot.py` — הוא יישאר זהה.

---

## הערה לעתיד — אופציית קונסולידציה מלאה (מסלול B)

אם בעתיד תרצי להוריד לחלוטין את SiteGround ולעבור לפלטפורמה אחת, זה אפשרי ואפילו חוסך כסף:

- האתר העסקי `meravtech.com` עצמו → Cloudflare Pages (חינם, CDN גלובלי)
- כל קוד Python (scraper, dispatcher, digest, bot) → Railway
- DNS + Email → Cloudflare + Zoho Mail (חינם) או Google Workspace ($6/חודש)
- DB → PostgreSQL של Railway (חינם עד 500MB)

עלות צפויה: $5-10/חודש סה"כ, במקום SiteGround + Railway.

**אבל — לא עושים את זה עכשיו.** מתמקדים במסלול A שעובד עם הכי פחות סיכון. מסלול B נשאר בצד ככיוון אפשרי אחרי שמסלול A יציב וההנה.
