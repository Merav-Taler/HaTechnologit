# מדריך פריסה — BatYam Today Bot → Railway

מדריך שלב-אחר-שלב להעברת הבוט ל-Railway. מהתחלה ועד סוף (כולל rollback).

**זמן משוער:** 1-2 שעות.

**לפני שמתחילים:** ודאי שיש לך:
- חשבון GitHub (חינם)
- כרטיס אשראי לרישום ל-Railway (לא גובים בחינם, אבל דורשים כרטיס תקף)
- גישה ל-SiteGround Site Tools (File Manager)

---

## שלב 1 — הכנת הסודות (10 דק')

### 1.1 ייצור `API_KEY` חדש

ב-terminal במחשב שלך:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

תקבלי מחרוזת באורך 64 תווים, למשל `3f8a9b...`. שמרי אותה — נשתמש בה פעמיים.

### 1.2 עדכון `batyam_secrets.json` בשרת SiteGround

נכנסי ל-Site Tools → File Manager → navigate לתיקייה הראשית של `meravtech.com`.
פתחי את `batyam_secrets.json`. הקובץ כרגע:

```json
{
  "TELEGRAM_BOT_TOKEN": "<TELEGRAM_BOT_TOKEN — נמצא ב-batyam_secrets.json / Railway>",
  "DASHBOARD_URL": "https://meravtech.com/batyam/",
  "ADMIN_CHAT_IDS": [543343249],
  "WEBHOOK_SECRET": "72eee276..."
}
```

הוסיפי שדה `API_KEY` חדש עם ה-hex שיצרת למעלה:

```json
{
  "TELEGRAM_BOT_TOKEN": "<TELEGRAM_BOT_TOKEN — נמצא ב-batyam_secrets.json / Railway>",
  "DASHBOARD_URL": "https://meravtech.com/batyam/",
  "ADMIN_CHAT_IDS": [543343249],
  "WEBHOOK_SECRET": "72eee276...",
  "API_KEY": "ה-hex-שלך-כאן"
}
```

שמרי.

### 1.3 העלאת `api.php` ל-SiteGround

ב-File Manager, navigate ל-`public_html/batyam/`. העלי את הקובץ `api.php` (שנמצא בתיקיית הפרויקט המקומית שלך). הרשאות: 644.

### 1.4 בדיקה שה-API עובד

בדפדפן או curl:

```bash
curl -X POST https://meravtech.com/batyam/api.php \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ה-hex-שלך" \
  -d '{"action":"ping"}'
```

צפוי:
```json
{"ok":true,"result":{"pong":true,"db":"batyam_data.db","time":"..."}}
```

אם יש שגיאה: בדקי שהעלית את `api.php` למיקום הנכון ושה-API_KEY ב-secrets מתאים.

---

## שלב 2 — הקמת repo ב-GitHub (10 דק')

### 2.1 יצירת repo חדש

- היכנסי ל-github.com
- New repository → שם: `batyam-bot-railway` (או כל שם שתרצי)
- **פרטי** (Private) — חשוב! הקוד מכיל לוגיקה עסקית
- בלי README, .gitignore, או license

### 2.2 הקמת git מקומי

ב-terminal, בתיקיית `railway_bot/`:

```bash
cd /path/to/BatYamToday/railway_bot
git init
git add .
git commit -m "Initial Railway deployment"
git branch -M main
git remote add origin git@github.com:YOUR_USERNAME/batyam-bot-railway.git
git push -u origin main
```

(החליפי `YOUR_USERNAME` בשם המשתמש שלך ב-GitHub.)

**ודאי ש-`.env` ו-`batyam_secrets.json` לא ב-git!** הם ב-`.gitignore` אז זה אמור להיות בטוח. אם אינך רואה `.env` בתוצאה של `git status`, הכל בסדר.

---

## שלב 3 — רישום ב-Railway והעלאה (20 דק')

### 3.1 רישום

- railway.app → Sign up with GitHub
- אישור גישה של Railway ל-repos שלך
- קבלת $5 קרדיט חודשי חינם

### 3.2 יצירת פרויקט חדש

- Dashboard → **+ New Project**
- **Deploy from GitHub repo** → בחרי את `batyam-bot-railway`
- Railway יתחיל לבנות אוטומטית (נמשך 2-3 דק')

### 3.3 הגדרת משתני סביבה

בפרויקט שלך → לשונית **Variables**. הוסיפי אחד-אחד:

| Variable | Value |
|----------|-------|
| `TELEGRAM_BOT_TOKEN` | (מתוך batyam_secrets.json) `<TELEGRAM_BOT_TOKEN — נמצא ב-batyam_secrets.json / Railway>` |
| `WEBHOOK_SECRET` | (מתוך batyam_secrets.json) `72eee276...` |
| `API_URL` | `https://meravtech.com/batyam/api.php` |
| `API_KEY` | (אותו hex שהוספת ל-batyam_secrets.json) |
| `ADMIN_CHAT_IDS` | `[543343249]` |
| `DASHBOARD_URL` | `https://meravtech.com/batyam/` |

אחרי ההוספה, Railway ידפלוי אוטומטית שוב.

### 3.4 יצירת public URL

בפרויקט → **Settings** → **Networking** → **Generate Domain**.

תקבלי URL כמו `batyam-bot-railway-production.up.railway.app`. שמרי את זה.

### 3.5 בדיקת health

פתחי בדפדפן:
```
https://YOUR-URL.up.railway.app/healthz
```
צפוי: `{"ok":true}`

אם `500` או `Error` — בדקי את ה-Deployments → View Logs לראות מה השגיאה.

---

## שלב 4 — בדיקה מקצה-לקצה לפני החלפת webhook (15 דק')

**חשוב: אל תחליפי את ה-webhook של טלגרם עד שאת בטוחה שה-bot ב-Railway עובד!**

### 4.1 שליחת POST מדומה

ב-terminal:

```bash
curl -X POST https://YOUR-URL.up.railway.app/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: YOUR_WEBHOOK_SECRET" \
  -d '{
    "update_id": 999999999,
    "message": {
      "message_id": 1,
      "from": {"id": 543343249, "first_name": "Merav", "is_bot": false},
      "chat": {"id": 543343249, "type": "private"},
      "date": 1700000000,
      "text": "/help"
    }
  }'
```

צפוי: `ok` (body), status 200.

### 4.2 בדיקה שקיבלת הודעה בטלגרם

פתחי את הצ'אט עם `@BatYamTodayBot` — אמורה להגיע תשובה עם ה-help. אם קיבלת — **הכל עובד**.

### 4.3 בדיקת שאילתה עם DB

```bash
curl -X POST https://YOUR-URL.up.railway.app/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: YOUR_WEBHOOK_SECRET" \
  -d '{
    "update_id": 999999998,
    "message": {
      "message_id": 2,
      "from": {"id": 543343249, "first_name": "Merav", "is_bot": false},
      "chat": {"id": 543343249, "type": "private"},
      "date": 1700000000,
      "text": "מה יש היום?"
    }
  }'
```

צפוי: תגובה בטלגרם עם אירועי היום. זה מאמת שהבוט ב-Railway מצליח לגשת ל-DB דרך api.php ב-SiteGround.

אם נכשל — פתחי את Railway Logs ובדקי מה השגיאה.

---

## שלב 5 — החלפת ה-webhook בטלגרם (5 דק')

זהו הרגע שבו טלגרם מתחיל לשלוח את ההודעות אל Railway במקום אל SiteGround.

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://YOUR-URL.up.railway.app/webhook",
    "secret_token": "YOUR_WEBHOOK_SECRET",
    "allowed_updates": ["message", "callback_query"]
  }'
```

צפוי: `{"ok":true,"result":true,"description":"Webhook was set"}`

אימות:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

הכתובת צריכה להיות כתובת Railway שלך.

### בדיקה חיה

שלחי הודעה לבוט מחשבון ה-Telegram שלך (לא curl) — "מה יש היום?" או "/today". ודאי שקיבלת תשובה.

---

## שלב 6 — ניקיון (10 דק', אפשר לדחות)

### 6.1 ביטול ה-cron ב-SiteGround

ב-Site Tools → Devs → **Cron Jobs**.

מצאי את ה-cron של הבוט (`batyam_bot.py --poll`) ומחקי אותו (או השבי).

**חשוב: אל תיגעי ב-cron של scraper, dispatcher, או digest — הם עדיין רצים ב-SiteGround.**

### 6.2 סגירת webhook.php הישן (אופציונלי)

`webhook.php` בשרת SiteGround לא פעיל יותר כי טלגרם לא שולחת אליו. אפשר להשאיר אותו כ-fallback לחירום. אין סכנה.

### 6.3 מחיקת tg_echo.php

לא צריך יותר. מחקי מ-`public_html/batyam/` כדי לא לבלבל.

---

## מוניטורינג (24-48 שעות ראשונות)

### מה לבדוק

- **Railway Dashboard** → **Metrics** — צריכת RAM ו-CPU. צריכה להיות נמוכה (עשרות מ"ב זיכרון, CPU פחות מ-5%).
- **Railway Logs** → לראות שהודעות מגיעות ומתעבדות.
- **batyam_bot.log ב-SiteGround** — לא יגדל יותר (הבוט לא רץ שם). זה תקין.
- **getWebhookInfo** — אמור להיות עקבי: `pending_update_count: 0` ואין `last_error_message`.

### אם משהו לא עובד — Rollback

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://meravtech.com/batyam/webhook.php&secret_token=YOUR_WEBHOOK_SECRET"
```

טלגרם תחזור לשלוח ל-SiteGround. (שים/י לב: זה עדיין לא אידיאלי בגלל בעיית ה-WAF המקורית — זה rollback זמני בלבד.)

---

## שאלות-ותשובות

**שאלה: האם התרגום משפיע על המשתמשים הקיימים?**
תשובה: לא. הם ממשיכים לדבר עם אותו בוט (`@BatYamTodayBot`). הם לא ידעו שמשהו השתנה. המעקבים שלהם, ההיסטוריה, וההעדפות נשארים.

**שאלה: מה קורה לדיספאצ'ר (push notifications)?**
תשובה: ממשיך לרוץ ב-SiteGround, אין שינוי. הוא משתמש ב-TOKEN של הבוט ישירות, לא תלוי ב-webhook.

**שאלה: האם אני צריכה לעדכן URL ב-Telegram BotFather?**
תשובה: לא. BotFather לא מכיר בכלל את הכתובת של webhook — זו הגדרה שלך באמצעות setWebhook API. ה-username של הבוט, שם וצבעים — כל זה נשאר.

**שאלה: כמה זמן קוד ה-Railway נשאר חי (sleep)?**
תשובה: ב-Railway Free Tier אין sleep. הבוט פעיל 24/7. אם תעברי ל-Hobby ($5/חודש) — גם שם, ללא sleep.

**שאלה: מה עם הלוגים של הבוט?**
תשובה: ב-Railway, הכל יוצא ל-stdout ו-Railway שומר אותם בכרטיסיית Logs. הם זמינים 7 ימים אחורה ב-Free Tier. אם רוצה יותר — מערכת לוגים חיצונית (Axiom, Logtail — חינם).

**שאלה: מה אם SiteGround api.php איטי/נופל?**
תשובה: הבוט יחזיר שגיאה פנימית אבל החזיר 200 לטלגרם (לא נכנס ל-retry loop). המשתמש יראה אי-תגובה. כדאי לעקוב אחרי זה ואם יש בעיות — נוכל לעבור למסלול B (הכל ב-Railway).

---

## צ'ק-ליסט סופי

- [ ] `api.php` הועלה ל-SiteGround ב-`public_html/batyam/`
- [ ] `API_KEY` נוסף ל-`batyam_secrets.json` ב-SiteGround
- [ ] בדיקת `ping` ל-api.php החזירה `pong:true`
- [ ] repo ב-GitHub נוצר (פרטי)
- [ ] פרויקט Railway מחובר ל-repo
- [ ] כל ה-environment variables ב-Railway מוגדרים
- [ ] Railway URL מוגדר (Networking → Generate Domain)
- [ ] `/healthz` מחזיר `{"ok":true}`
- [ ] בדיקת curl עם webhook מדומה החזירה תשובה בטלגרם
- [ ] `setWebhook` ל-URL של Railway בוצע בהצלחה
- [ ] הודעה חיה מ-Telegram התקבלה ונענתה
- [ ] `batyam_bot.py --poll` cron מבוטל ב-SiteGround
- [ ] `tg_echo.php` נמחק (אופציונלי)

אם סימנת הכל — **הסתיים בהצלחה!**
