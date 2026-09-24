# BatYamToday — הוראות פרויקט

פלטפורמה קהילתית לפעילויות בבת ים: אתר (batyamtoday.meravtech.com) + בוט טלגרם (@BatYamTodayBot)
שסורק את מערכת קוינג העירונית, מרכז אירועים, ושולח התראות מותאמות אישית.

**ממשיכים עבודה? לקרוא קודם את `docs/STATUS.md`** — סטטוס עסקי, נתוני baseline,
תוכנית הצמיחה, משימות הקוד הפתוחות וקישורי הארטיפקטים החיים.

## ⚠️ פרודקשן — לקרוא לפני כל שינוי

- **ה-DB החי נמצא רק ב-Railway** (volume ב-`/data`). ה-`batyam_data.db` המקומי הוא עותק בדיקות ישן — אסור להסיק ממנו נתוני משתמשים ואסור לדחוף אותו לפרודקשן.
- **פריסה ל-Railway**: דרך ריפו GitHub נפרד בשם `batyam-bot-railway` (התיקייה `railway_bot/` כאן היא עותק עבודה). push לריפו ההוא = דיפלוי אוטומטי.
- **פריסה ל-SiteGround** (האתר: `https://batyamtoday.meravtech.com`, מ-24.9.2026): העלאה ידנית דרך File Manager, אין CI. הסאב-דומיין הוא "אתר" נפרד ב-SiteGround עם תיקייה משלו: **`batyamtoday.meravtech.com/public_html/`** (לא בתוך `meravtech.com/public_html/`). מה יושב שם:
  - `index.html` = עותק של **`preview.html`** המקומי (אין `preview.html` בשרת)
  - `admin/index.html` = עותק של **`dashboard.html`** המקומי
  - `privacy.html`, `favicon.png`, `apple-touch-icon.png`, `og-image.png`, `.htaccess` (= `deploy/new-site.htaccess`)
  - **תהליך**: אחרי כל עריכה, לבנות מחדש את `deploy/upload/` (index.html + admin/index.html + נכסים) ולגרור ל-File Manager. `deploy/upload/` הוא רק עותק להעלאה, לא מקור.
  - **ה-301 מהנתיב הישן** יושב ב-`.htaccess` של **שורש meravtech.com** (`meravtech.com/public_html/.htaccess`, כלל `^batyam/(.*)$`; העתק ב-`deploy/old-batyam-path.htaccess`). לא להסיר — קישורים ישנים בוואטסאפ/טלגרם עדיין מגיעים לשם. תיקיית `public_html/batyam/` צריכה להישאר **ריקה**: SiteGround מגיש html/png סטטיים ישירות מ-nginx בלי rewrite, אז קובץ ישן שיישאר שם יוגש במקום להיות מופנה.
- **הבוט שולח הודעות לאנשים אמיתיים** (~100 משתמשים). כל שינוי בלוגיקת שליחה חייב הגנת הצפה (rate limit), ואסור לבדוק אותו מול ה-DB החי.
- **אסור להמציא גיל פעילות**: תיוג גיל מבוסס אך ורק על מספרים מפורשים בטקסט המקור של האירוע. אין היוריסטיקות.
- **קרדיט חובה**: הודעות דייג'סט/שיתוף כוללות קרדיט למירב + קישור לאתר. לא להסיר.
- **קוינג לא מפרסם רשימת קהילות**, ו-`plusi_all` לא מכסה הכול (למשל "צו 8"). הסקרייפר מגלה קהילות חדשות פעם ביום (`discover_communities`: עץ תת-קהילות + סריקת מספרי cid) ומתריע לאדמין. קהילה שצריך להוציא מהסריקה → `SECTION_BLACKLIST` בסקרייפר, לא מחיקה מה-DB.

## ארכיטקטורה

```
Railway (web-production-7e8ff.up.railway.app)
├── main.py            — Flask: webhook טלגרם, /sync_db, /pull_users, /dashboard_data.js, /preview_data.js
├── APScheduler        — scraper / digest / dashboard רצים בתוך אותו פרוסס (דגלי env)
├── batyam_bot.py      — לוגיקת הבוט (הרשמה, טרקרים, שאילתות בעברית)
├── batyam_scraper.py  — סריקת קוינג + סיווג סמנטי
├── batyam_db.py       — שכבת SQLite
└── /data (volume)     — batyam_data.db החי + קבצי dashboard

SiteGround (batyamtoday.meravtech.com)
├── preview.html       — האתר הציבורי (טוען preview_data.js מ-Railway)
├── dashboard.html     — דשבורד אדמין (Google login, נתוני Railway חיים + GA API)
├── privacy.html       — מדיניות פרטיות
└── *.php              — נקודות קצה ישנות (טרום-מיגרציה)
```

- **קבצים בשורש התיקייה** = הגרסה ה"מקומית" הישנה (טרום-Railway) + קבצי ה-web שמועלים ל-SiteGround.
- **`railway_bot/`** = הקוד שרץ בפרודקשן. שינויי בוט/סקרייפר עושים כאן, ואז מסנכרנים לריפו `batyam-bot-railway`.
- **`docs/`** = מסמכי תכנון, מדריך פריסה, הודעות הפצה. `docs/STATUS.md` = סטטוס והמשכיות; `docs/reports/` = הדוח העסקי ותוכנית הצמיחה (עותקי ה-HTML של הארטיפקטים).
- **`backup/`** = גרסאות ישנות ולוגים. לא בשימוש.

## אנליטיקות

- **Google Analytics** באתר: property ‏`G-QZRFH6TJG6` (מוטמע ב-`preview.html` ו-`privacy.html`).
- **דשבורד אדמין**: `dashboard.html` — מתחברים עם Google (poalim.campus מורשה) ורואים נתוני בוט חיים מ-Railway + נתוני GA.
- **נתוני בוט חיים** ללא לוגין: `https://web-production-7e8ff.up.railway.app/dashboard_data.js`
- **קישורי מעקב לבוט**: `t.me/BatYamTodayBot?start=track_<מילה>` — יוצרים ב-`track_link_generator.html`. משמשים למעקב מילות מפתח, לא לייחוס מקור הרשמה.

## סודות

- `batyam_secrets.json` (מקומי) ו-`DASHBOARD_PASSWORD.txt` — לא להעלות ל-git ולא להדפיס תוכן.
- ב-Railway הסודות במשתני סביבה (ראו `railway_bot/.env.example`).

## מוסכמות

- כל הטקסטים למשתמש בעברית; קישורים בהודעות טלגרם בפורמט בר-העתקה (URL מלא, לא markdown חבוי).
- שעות שקט למשתמשים: 22:00–07:00 כברירת מחדל — הדיספטצ'ר מכבד אותן.
- מפתחות חודש/תאריך: `YYYY-MM-DD`.
- הבוט לא שותק על שגיאות — עדיף הודעת שגיאה ידידותית מהיעדר תגובה.

## בדיקות מקומיות

```bash
cd railway_bot
python3 -c "import batyam_bot"          # בדיקת syntax מהירה
python3 batyam_scraper.py --dry-run     # אם נתמך — בלי כתיבה ל-DB
```

אין טסטים אוטומטיים. שינוי בלוגיקת שליחה → לבדוק מול צ'אט אדמין בלבד (ADMIN_CHAT_IDS) לפני דיפלוי.
