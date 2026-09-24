# איפה אנחנו — נקודת המשך

**תאריך עצירה:** 24 באפריל 2026
**סטטוס:** כל הקוד נכתב ונבדק. טרם הועלה לשום מקום. הבוט כרגע **לא פועל** (Telegram webhook רשום ל-webhook.php של SiteGround אבל ה-WAF חוסם אותו בשקט).

---

## 🎯 מה מוכן (כבר נכתב ונבדק)

### קבצים לשרת SiteGround (ב-workspace המקומי, מוכנים להעלאה)
- ✅ `api.php` — endpoint HTTP שחושף את ה-DB (17KB, 200+ שורות)
  - מיקום יעד: `public_html/batyam/api.php` בשרת
  - שינוי נדרש ב-`batyam_secrets.json`: הוספת `API_KEY`

### קבצים לפריסת Railway (ב-תיקייה `railway_bot/`)
- ✅ `main.py` — מעטפת Flask
- ✅ `batyam_bot.py` — הבוט המקורי, 5 מיקומי `db.get_db()` הוחלפו
- ✅ `batyam_db.py` — קליינט HTTP שקורא ל-api.php
- ✅ `requirements.txt`, `Procfile`, `railway.toml`, `.env.example`, `.gitignore`, `README.md`

### תיעוד
- ✅ `PLAN_MIGRATION.md` — תוכנית מלאה כולל CPU ועלויות
- ✅ `DEPLOY_GUIDE.md` — מדריך שלב-אחר-שלב מפורט
- ✅ `NEXT_STEPS.md` — הקובץ הזה

---

## ⏸️ איפה עצרנו

**לא בוצעה אף פעולה בשרת/בטלגרם.** כל הקוד לוקלי בלבד. הבוט ממשיך להיות שקט (בדיוק כמו לפני תחילת הסשן).

---

## 🚦 סדר פעולות כשחוזרים

### שלב 1: SiteGround (כ-15 דק') — אני יכול לבצע דרך Claude in Chrome

1. **ייצור `API_KEY`** — אני אריץ `python3 -c "import secrets; print(secrets.token_hex(32))"` ואשמור את המחרוזת
2. **פתיחת SiteGround File Manager** דרך הדפדפן (את כבר מחוברת)
3. **יצירת קובץ `api.php`** בתיקייה `public_html/batyam/` — אדביק את התוכן המקומי
4. **עדכון `batyam_secrets.json`** בשורש — הוספת שורה `"API_KEY": "..."`
5. **בדיקת `ping`** דרך curl — צפוי `{"ok":true,"result":{"pong":true}}`

**אחרי השלב הזה:** ה-API של SiteGround פעיל. הבוט עדיין לא רץ אצלך. שום דבר לא נשבר.

---

### שלב 2: GitHub (כ-10 דק') — צריך פעולה שלך

אני לא יכול ליצור repo בשמך, אבל אחרי שתהיי מחוברת — אני יכול להעלות קבצים דרך UI.

1. את נכנסת ל-github.com ויוצרת repo **פרטי** בשם `batyam-bot-railway`
2. את אומרת לי "מוכן" ואני דוחף את כל התיקייה `railway_bot/` דרך הדפדפן (או דרך git אם יש לך SSH setup במחשב)

---

### שלב 3: Railway (כ-20 דק') — צריך פעולה ראשונית שלך

1. את נרשמת ב-railway.app (GitHub Auth, כרטיס אשראי נדרש אבל לא מחויב ב-Free Tier)
2. Connect to GitHub → בחירת ה-repo
3. אחרי שאת מחוברת — אני ממלא את כל שאר השלבים (Environment Variables, Generate Domain, בדיקות)

---

### שלב 4: החלפת webhook (5 דק') — אני מבצע

אחרי שהכל עובד: שליחת `setWebhook` לטלגרם עם ה-URL החדש של Railway. רגע החלפה.

---

### שלב 5: ניקיון ומוניטורינג

- ביטול cron של `batyam_bot.py --poll` ב-SiteGround
- מחיקת `tg_echo.php`
- מעקב אחרי הלוגים ב-Railway למשך 24 שעות

---

## 📁 מפת קבצים בתיקייה

```
/sessions/hopeful-vibrant-hopper/mnt/BatYamToday/
├── PLAN_MIGRATION.md              ← תוכנית מפורטת
├── DEPLOY_GUIDE.md                ← מדריך פריסה
├── NEXT_STEPS.md                  ← הקובץ הזה
├── api.php                        ← להעלות ל-SiteGround
├── batyam_bot.py                  ← הגרסה המקורית (לא נוגעים)
├── batyam_db.py                   ← הגרסה המקורית (לא נוגעים)
├── batyam_secrets.json            ← בגיבוי, מסונכרן עם שרת
└── railway_bot/                   ← לדחוף ל-GitHub
    ├── main.py
    ├── batyam_bot.py              ← העתק מודיפיאד (5 שורות)
    ├── batyam_db.py               ← קליינט HTTP
    ├── requirements.txt
    ├── Procfile
    ├── railway.toml
    ├── .env.example
    ├── .gitignore
    └── README.md
```

---

## 🔐 סודות שכבר יש לנו

- `TELEGRAM_BOT_TOKEN`: `<TELEGRAM_BOT_TOKEN — נמצא ב-batyam_secrets.json / Railway>`
- `WEBHOOK_SECRET` (קיים בשרת): `<WEBHOOK_SECRET — ב-batyam_secrets.json / Railway>`
- `API_KEY`: **טרם נוצר** — ייווצר בשלב 1

## ⚠️ נקודה חשובה לזכור

- אל תיגעי בכלום בשרת לפני שנחזור
- אם בינתיים את שולחת הודעה לבוט — לא תקבלי תגובה (המצב הנוכחי, לא השתנה)
- אם בדחיפות צריך שהבוט יענה — ניתן לעשות rollback ל-polling דרך ה-cron הקיים. אבל זה יחזיר את בעיית ה-CPU הישנה

---

## 🔄 איך לחזור לסשן

פשוט הכניסי: **"בואי נמשיך מאיפה שעצרנו"** ואני אטען את הקובץ הזה ואדע בדיוק איפה אנחנו.
