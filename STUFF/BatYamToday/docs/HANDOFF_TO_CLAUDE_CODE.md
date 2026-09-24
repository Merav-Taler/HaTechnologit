# מסמך העברה ל-Claude Code

**תאריך:** 25 באפריל 2026
**מטרה:** להמשיך את המיגרציה של @BatYamTodayBot ל-Railway, מהמקום שעצרנו ב-Cowork.

---

## TL;DR — איפה אנחנו

✅ **גיליתי שדורין-בוט (4,800 משתמשים) רץ על Railway** — אז המסלול שלנו נכון. הוכחה: response header `server: railway-edge` ב-`dorin.app`.

⚠️ **הבוט לא מגיב כרגע למשתמשים.** Telegram webhook מצביע על Railway, אבל Railway לא יכול לגשת ל-DB ב-SiteGround כי SiteGround WAF חוסם את ה-IPs של Railway. השלכות: השיחה החופשית מפסיקה לעבוד. **ה-Push notifications, Digest יומי, והאתר ממשיכים לעבוד תקין** (הם רצים על SiteGround עם DB מקומי).

🎯 **התוכנית המאושרת:** מיגרציה מלאה של DB + scripts ל-Railway, באותה ארכיטקטורה כמו דורין.

---

## מצב מערכת מפורט

### Railway (פרויקט קיים)
- **Project name:** `adorable-nurturing`
- **Project URL:** `https://railway.com/project/cf414f82-4d89-4ce3-832b-aaaf31f5d19f`
- **Service URL:** `https://web-production-7e8ff.up.railway.app`
- **Service ID:** `8f13241c-e4b1-41ab-8bcd-627b7d3b375a`
- **Environment ID:** `a90f3a56-c9df-4f2a-991b-6b0b1b7a21d7`
- **GitHub repo:** `Merav-Taler/batyam-bot-railway` (private)
- **Status:** Online, אבל הבוט קורס בכל בקשה (DB מנותק)

**Environment Variables קיימים:**
```
TELEGRAM_BOT_TOKEN=<TELEGRAM_BOT_TOKEN — נמצא ב-batyam_secrets.json / Railway>
WEBHOOK_SECRET=<ב-batyam_secrets.json / Railway>
API_URL=https://meravtech.com/batyam/api.php   ← ⚠️ צריך להיעלם אחרי המיגרציה
API_KEY=<ב-batyam_secrets.json / Railway>
ADMIN_CHAT_IDS=[543343249]
DASHBOARD_URL=https://meravtech.com/batyam/
```

### SiteGround (פרויקט קיים — לא נוגעים)
- **Domain:** `meravtech.com`
- **SSH:** `ssh.meravtech.com:18765` user `u3362-rjcdi9ih3mwe`
- **Site Tools:** `https://tools.siteground.com` (Site ID: `SndIM1ozOE5JUT09`)
- **DB השרת (מאסטר):** `/home/u3362-rjcdi9ih3mwe/www/meravtech.com/scripts/batyam_data.db` (~724 KB, מתעדכן כל 5 דק')
- **DB ב-root:** `/home/.../meravtech.com/batyam_data.db` (260KB, ישן — לא בשימוש)
- **Cron jobs פעילים ב-SiteGround:**
  - `batyam_scraper.py` — כל 5 דקות
  - `batyam_dispatcher.py` — לפי לו"ז
  - `batyam_digest.py` — 07:00 יומי
  - `generate_dashboard_data.py` — כל 15 דקות
  - `batyam_bot.py --poll` — כל דקה (no-op כרגע)

### Telegram Webhook
- כרגע מצביע על: `https://web-production-7e8ff.up.railway.app/webhook`
- Secret: `<WEBHOOK_SECRET — ב-batyam_secrets.json / Railway>`
- ⚠️ **מצב לא תקין** — הבוט לא יכול לענות עד שיש לו DB מקומי

---

## גיבוי שכבר בוצע

מיקום: `/sessions/hopeful-vibrant-hopper/mnt/BatYamToday/backup/2026-04-25_pre-migration/`

16 קבצים: כל קוד הפייתון, הקבצי PHP, secrets, dashboard, הקישורים.

⚠️ **חסר:** ה-DB העדכני מ-SiteGround. צריך להוריד את `scripts/batyam_data.db` ולהוסיף ל-backup לפני שמתחילים.

---

## מבנה תיקיות בעבודה

```
/sessions/hopeful-vibrant-hopper/mnt/BatYamToday/
├── PLAN_FULL_MIGRATION.md         ← התוכנית המפורטת ל-5 שלבים
├── HANDOFF_TO_CLAUDE_CODE.md      ← הקובץ הזה
├── PLAN_MIGRATION.md              ← תוכנית קודמת (חלקית, אופציה A)
├── DEPLOY_GUIDE.md                ← מדריך deploy ל-Railway
├── NEXT_STEPS.md                  ← נקודת המשך מסשן קודם
│
├── batyam_bot.py                  ← הבוט המקורי (משתמש ב-SQLite ישירות)
├── batyam_db.py                   ← ה-DB layer המקורי (SQLite ישיר)
├── batyam_scraper.py              ← סקרפר מקורי
├── batyam_dispatcher.py           ← דיספאצ'ר מקורי
├── batyam_digest.py               ← דייג'סט מקורי
├── batyam_monitor.py              ← מוניטור מקורי
├── generate_dashboard_data.py     ← מחולל preview_data.js
├── batyam_data.db                 ← snapshot מקומי (14/4 — ישן!)
├── batyam_secrets.json            ← טוקנים (סונכרן עם השרת)
│
├── api.php                        ← מותקן ב-SiteGround, נמחק אחרי המיגרציה
├── webhook.php                    ← מותקן ב-SiteGround, fallback
├── tg_echo.php                    ← מותקן ב-SiteGround, נמחק
│
└── railway_bot/                   ← קוד Railway קיים
    ├── main.py                    ← Flask wrapper
    ├── batyam_bot.py              ← העתק עם 5 patches
    ├── batyam_db.py               ← קליינט HTTP (לא יידרש אחרי המיגרציה!)
    ├── requirements.txt
    ├── Procfile
    ├── railway.toml
    ├── .env.example
    ├── .gitignore
    └── README.md
```

---

## המשימות הנותרות (5 שלבים)

### שלב 1: גיבוי DB החי + הקמת Volume (~45 דק')

1. **הורדת `scripts/batyam_data.db` מ-SiteGround** ל-`backup/2026-04-25_pre-migration/`
   - דרך Site Tools File Manager → scripts/ → batyam_data.db → Download
   - או דרך SSH: `scp -P 18765 u3362-rjcdi9ih3mwe@ssh.meravtech.com:/home/.../scripts/batyam_data.db ./backup/`

2. **יצירת Volume ב-Railway**
   ```bash
   railway login
   railway link --project cf414f82-4d89-4ce3-832b-aaaf31f5d19f
   railway service web
   railway volume create --service web --mount-path /data --name batyam-data
   ```

3. **העלאת ה-DB ל-Volume**
   - דרך Railway CLI shell: `railway shell` → `cp file /data/`
   - או דרך service זמני שמעלה דרך HTTP

4. **הוספת env var:** `BATYAM_DB_PATH=/data/batyam_data.db`

### שלב 2: החזרת הבוט ל-SQLite מקומי (~30 דק')

1. **שינוי `railway_bot/batyam_db.py`** — להחזיר לגרסה המקורית של SQLite (העתק מ-`batyam_db.py` ב-root, לא מ-`railway_bot/`)
2. **שינוי `railway_bot/batyam_bot.py`** — להחזיר את 5 ה-patches שעשיתי (להחזיר `db.get_db()` במקום `db.get_events_by_date()`)
3. **commit + push** → Railway ידפלוי
4. **בדיקה:** שליחת POST ידני (כפי שעשינו עם `TEST_DIRECT_POST`) ובדיקת תשובה

### שלב 3: Scraper כ-cron service ב-Railway (~45 דק')

הוספת service חדש מאותו GitHub repo, עם:
- Start command: `python batyam_scraper.py`
- Cron schedule: `*/5 * * * *`
- Mount של אותו volume `/data`
- Env vars משותפים (TELEGRAM_BOT_TOKEN וכו')

צריך גם להעלות את `batyam_scraper.py` ל-repo.

### שלב 4: Dispatcher + Digest + Dashboard data (~45 דק')

3 services נוספים:
- Dispatcher: cron כפי שמוגדר ב-SiteGround כיום
- Digest: cron `0 7 * * *`
- Dashboard generator: cron `*/15 * * * *`, מייצר `preview_data.js` ומגיש ב-`/preview_data.js` (Flask endpoint)

עדכון `meravtech.com/batyam/index.html` — שורה אחת:
```html
<!-- מ -->
<script src="preview_data.js"></script>
<!-- ל -->
<script src="https://web-production-7e8ff.up.railway.app/preview_data.js"></script>
```

### שלב 5: ניקוי ויציבות (24 שעות מוניטורינג)

- ביטול Cron ב-SiteGround (scraper, dispatcher, digest, generate_dashboard_data, batyam_bot --poll)
- מחיקת `api.php`, `tg_echo.php` (אופציונלי)
- עדכון `קישורים.md`

---

## נקודות סיכון לשים לב אליהן

1. **DB drift** — בזמן שאת בונה את הסביבה החדשה, ה-scraper ב-SiteGround ממשיך לעדכן את ה-DB שם. בעת ה-cutover צריך **גיבוי טרי** של DB מ-SiteGround והעלאה ל-Railway, אחרת תאבדי שעות-יום של אירועים חדשים.

2. **Notifications כפולות** — בזמן שיש שני dispatchers (SG ו-Railway) הם עלולים לשלוח את אותה התראה פעמיים. הצעה: ה-dispatcher של Railway יכתוב בלוג בלבד עד שאת מעבירה.

3. **WAF של SiteGround עדיין קיים** — אם תצטרכי בעתיד שמשהו בענן יקרא ל-SiteGround, זה לא יעבוד. תכנני שכל הקריאות יוצאות מ-SiteGround, לא נכנסות אליו.

---

## פקודות שתצטרכי

### Railway CLI (Claude Code יוכל להריץ)
```bash
# התקנה
npm install -g @railway/cli

# כניסה
railway login

# חיבור לפרויקט קיים
railway link --project cf414f82-4d89-4ce3-832b-aaaf31f5d19f

# רשימת services
railway list

# Volume
railway volume create --mount-path /data
railway volume list

# Logs
railway logs --service web

# Env vars
railway variables --set "BATYAM_DB_PATH=/data/batyam_data.db"

# Deploy
railway up
```

### Git (לעדכוני קוד)
```bash
cd railway_bot
git add .
git commit -m "..."
git push
```

### Telegram API (לבדיקת webhook)
```
GET https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN — נמצא ב-batyam_secrets.json / Railway>/getWebhookInfo
```

---

## שאלת המוצא הראשונה ב-Claude Code

הצעה לפתיחת השיחה ב-Claude Code:

> "המשך את המיגרציה של @BatYamTodayBot ל-Railway. כל ההקשר במסמך `HANDOFF_TO_CLAUDE_CODE.md`. תתחיל משלב 1 — גיבוי DB החי מ-SiteGround והקמת Volume ב-Railway."

ואז Claude Code יקרא את הקובץ הזה ויידע בדיוק איפה אנחנו.

---

## אם משהו ישבר ורוצים לחזור אחורה — Rollback מהיר

```
# 1. החזרת ה-webhook לשרת הישן
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook?url=https://meravtech.com/batyam/webhook.php&secret_token=$WEBHOOK_SECRET"

# 2. החזרת ה-cron --poll ב-SiteGround (אם ביטלת)
# ב-Site Tools → Devs → Cron Jobs → enable: */5 * * * * cd /home/USER/scripts && python3 batyam_bot.py --poll

# 3. שחזור קבצים
# מ-backup/2026-04-25_pre-migration/* — להעלות ל-SiteGround/scripts/
```

---

## בהצלחה!

ההכנה כאן עומדת ב-90%. הצעדים הקריטיים שנותרו הם:
- גיבוי DB החי
- Volume ב-Railway
- שינוי 2 קבצי קוד והעלאתם ל-GitHub
- Cron services לסקרפר/דיספאצ'ר/דייג'סט

זמן משוער ב-Claude Code: **2-3 שעות עבודה רצופה.**
