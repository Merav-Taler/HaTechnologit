# מעבר דומיין: meravtech.com/batyam → batyamtoday.meravtech.com (24.9.2026)

## מה כבר שונה בקוד (מקומית)
| קובץ | שינוי |
|---|---|
| `preview.html` | canonical / og:url / og:image / JSON-LD → דומיין חדש; favicon, apple-touch-icon, privacy.html → נתיבים יחסיים; לוגו → `https://meravtech.com/logo.png` (מוחלט, כי הוא באתר העסקי); טקסטי וואטסאפ → `batyamtoday.meravtech.com` |
| `privacy.html` | קישור "חזרה לאתר" → `/`; אזכורי הכתובת |
| `dashboard.html` | סינון כל דוחות GA לאתר בת ים בלבד (`hostName = batyamtoday.meravtech.com` **או** `pagePath` מתחיל ב-`/batyam/` להיסטוריה) — הנכס משותף עם meravtech.com ואחרי המעבר שני האתרים מדווחים `/` |
| `railway_bot/batyam_bot.py`, `batyam_dispatcher.py`, `batyam_digest.py`, `main.py`, `.env.example` | כל קישורי האתר בהודעות טלגרם + ברירת מחדל `DASHBOARD_URL` |
| `og-image.svg` + `og-image.png` | הכתובת בתמונת השיתוף רונדרה מחדש (1200×630) |
| `deploy/old-batyam-path.htaccess` | Redirect 301 מהנתיב הישן |
| קבצי legacy בשורש (`batyam_bot.py` וכו׳), `CLAUDE.md`, `docs/STATUS.md`, `docs/קישורים.md`, `docs/הפצה_BatYamToday.md` | אזכורים |

קרדיט "הטכנולוגית — meravtech.com" בהודעות **לא** שונה בכוונה: זה האתר העסקי, לא אתר בת ים.

## צ׳קליסט פריסה — לפי הסדר

### 1. SiteGround — סאב-דומיין
1. Site Tools → Domain → Subdomains → New Subdomain: `batyamtoday`. ✅ נעשה. **בפועל** SiteGround יצר "אתר" נפרד בעץ של File Manager: `batyamtoday.meravtech.com/public_html/` (אחות של `meravtech.com/`, לא בתוכה).
2. Site Tools → Security → SSL Manager → Let's Encrypt לסאב-דומיין החדש → ואז HTTPS Enforce.
3. File Manager → להעלות ל-`batyamtoday.meravtech.com/public_html/` (הכל מוכן ב-`deploy/upload/`): ✅ נעשה, אומת מבחוץ.
   - `preview.html` **בשם `index.html`**
   - `privacy.html`
   - `dashboard.html` **בשם `admin/index.html`** (כמו היום: הדשבורד יושב ב-`/admin/`)
   - `favicon.png`, `apple-touch-icon.png`, `og-image.png`
   - (קבצי ה-PHP הישנים לא נחוצים — הכל ב-Railway)
4. בדיקה: `https://batyamtoday.meravtech.com/` נטען, favicon, `privacy.html`, הלוגו בבאנר הקרדיט.

### 1ב. `.htaccess` לאתר החדש
להעלות את `deploy/new-site.htaccess` ל-`batyamtoday.meravtech.com/public_html/` ולשנות שם ל-`.htaccess`
(כותרות אבטחה, קאשינג, דחיסה, חסימת קבצים רגישים — הועתק מה-htaccess הישן, בלי חלק `preview_data.js`).
בדיקה: `curl -I https://batyamtoday.meravtech.com/` צריך להחזיר `x-frame-options: SAMEORIGIN`.
✅ פעיל (24.9 אחה"צ). **לקח**: File Manager של SiteGround לא יוצר/מעלה קובץ שמתחיל בנקודה — הפתרון שעבד: `deploy/htaccess-for-new-site.zip` (מכיל `.htaccess`) → Upload → Extract לתיקייה הנוכחית → Delete ל-zip.

### 1ג. HTTPS Enforce
✅ (24.9) כל המתגים היו כבויים — הודלקו לשני הדומיינים + www. אומת: 301 ל-https, וההפניה מ-/batyam/ שרדה. היסטוריה: `http://` לא הופנה ל-`https://` באף אחד מהאתרים (כללי SiteGround נמחקו כשהוחלף ה-htaccess בשורש meravtech.com; באתר החדש לא הופעל). Site Tools → Security → SSL Manager → HTTPS Enforce → להדליק לשניהם (ב-meravtech.com: לכבות ולהדליק). בדיקה: `curl -sI http://meravtech.com/` → 301 ל-https.

### 2. SiteGround — Redirect מהנתיב הישן (רק אחרי שסעיף 1 עובד)
1. ✅ (24.9) ההפניה יושבת בסוף ב-`.htaccess` של **שורש** `meravtech.com/public_html/` (כלל `^batyam/(.*)$`, ראו `deploy/old-batyam-path.htaccess`). גרסה ראשונה עם `^(.*)$` + `RewriteBase /batyam/` בשורש הפנתה בטעות את **כל** meravtech.com — תוקן. הדפדפן של מירב זכר את ה-301 השגוי; חלון פרטי מראה נכון.
   ✅ תיקיית `public_html/batyam/` נמחקה כולה — כל הנתיבים הישנים (כולל `privacy.html`, `admin/`) מופנים 301 נכון. אומת מבחוץ.
   בדיקה מבחוץ: `curl -sI https://meravtech.com/batyam/api.php` — קובץ PHP עובר תמיד דרך Apache בלי cache; אם מחזיר 301 ל-batyamtoday, ה-htaccess פעיל. מצב 24.9 13:30: ❌ לא פעיל (עדיין 500 + כותרות מה-htaccess הישן).
2. אפשר למחוק את שאר הקבצים מ-`public_html/batyam/` — אבל לא חובה; ה-redirect קודם לכל.
3. בדיקה: `https://meravtech.com/batyam/` ו-`https://meravtech.com/batyam/privacy.html` מפנים (301) לכתובת החדשה.

### 3. Railway — הבוט
1. לסנכרן את `railway_bot/` לריפו `batyam-bot-railway` ולדחוף (deploy אוטומטי). ✅ 24.9: commit `ec4b717` נדחף ופרוס (Deployment successful). אימות מבחוץ: **`https://web-production-7e8ff.up.railway.app/`** (השורש, לא `/healthz`) מחזיר `"commit":"ec4b717"`.
2. ✅ Railway → Variables → `DASHBOARD_URL` = `https://batyamtoday.meravtech.com/` (עודכן 24.9; שימו לב: הכתובת הולכת לעמודת Value, לא לשם המשתנה).
3. בדיקה מול צ׳אט אדמין בלבד: `/start`, `/help`, ודייג'סט ידני — לוודא שהקישור החדש מופיע ונפתח.

### 4. Google — הגדרות שרק מירב יכולה לעשות
**OAuth (דשבורד אדמין):** ✅ נוסף ב-24.9. console.cloud.google.com → APIs & Services → Credentials → ה-Client ID
`579522482283-...` → Authorized JavaScript origins → להוסיף `https://batyamtoday.meravtech.com`.
בלי זה ההתחברות ב-`admin/index.html` תיכשל בדומיין החדש (שגיאת origin_mismatch).

**Google Analytics (GA4, נכס `G-QZRFH6TJG6`) — מה כבר בקוד:**
- אותו תג בשני הדפים, עם `cookie_domain: 'meravtech.com'` — עוגיית `_ga` על דומיין השורש, כך שמבקר שעובר
  בין האתר העסקי לאתר בת ים נספר פעם אחת ולא נוצר referral עצמי.
- `admin/index.html` (הדשבורד) מסנן את **כל** דוחות ה-GA ל-`hostName = batyamtoday.meravtech.com` או
  `pagePath` שמתחיל ב-`/batyam/` — אחרת אחרי המעבר "/" של meravtech.com ו-"/" של בת ים היו מתערבבים.

**מה לעשות בממשק GA (analytics.google.com → Admin):**
1. **Data Streams → הזרם של meravtech.com** — לא צריך זרם חדש: זרם אחד מכסה את דומיין השורש וכל
   הסאב-דומיינים. רק לוודא ב-"Configure tag settings → Domains" ש-`meravtech.com` מופיע (ואפשר להוסיף גם
   `batyamtoday.meravtech.com` — לא מזיק).
2. **Reports → Library / Explorations / Comparisons שמורים** — כל סינון שהיה על `Page path contains /batyam/`
   להחליף ל-`Hostname = batyamtoday.meravtech.com` (או OR עם הישן להיסטוריה). בדוחות הסטנדרטיים: להוסיף
   Comparison לפי Hostname כדי לראות את אתר בת ים לבד.
3. **Key events (המרות)** שמוגדרות על אירועי `gtrack` (click_bot, click_register, share_event…) — לא תלויות
   בדומיין, ממשיכות לעבוד.
4. **Search Console:** להוסיף נכס חדש `https://batyamtoday.meravtech.com/` (URL-prefix). תג ה-verification
   שכבר ב-`index.html` שייך לחשבון של מירב, אז האימות אמור לעבור מיד. אחר כך: Settings → Change of address
   בנכס `meravtech.com` **לא** מתאים (זה מעביר דומיין שלם) — פשוט להסתמך על ה-301, ולשלוח את הכתובת החדשה
   ל-Index → URL inspection → Request indexing.
5. **קישור GA ↔ Search Console** (Admin → Product links → Search Console) — לקשר את הנכס החדש.

**חלופה (לא מומלצת עכשיו):** נכס GA4 נפרד לבת ים. נותן הפרדה מלאה אבל מאבד את ההיסטוריה של 614 המבקרים
ומחייב להחליף את ה-Measurement ID בקוד ובדשבורד. אם בעתיד רוצים — לשנות `G-QZRFH6TJG6` ב-`preview.html`,
`privacy.html`, וב-`dashboard.html` לבטל את הסינון לפי hostName.

**כלי אנליטיקה נוספים:**
- דשבורד הבוט (`admin/index.html` + `dashboard_data.js` מ-Railway) — לא תלוי בדומיין, רק ה-OAuth origin.
- קישורי מעקב לבוט (`t.me/BatYamTodayBot?start=track_...`) — לא תלויים בדומיין.
- `batyam_monitor.py` (legacy, מקומי) — `SITE_URL` עודכן.

### 4ב. שאריות בשורש meravtech.com (נמצאו 24.9)
- `batyam_webhook_queue.jsonl` — שריד מהבוט הישן, נגיש פומבית (58 בייט). למחוק.
- `sitemap.xml` של האתר העסקי כלל `/batyam/` ו-`/batyam/privacy.html` — גרסה נקייה ב-`deploy/meravtech-root/sitemap.xml`.
- לאתר החדש נוספו `sitemap.xml` + `robots.txt` (חוסם `/admin/`) ב-`deploy/upload/`.

### 5. מקומות חיצוניים שמכילים את הכתובת הישנה (ידני)
- ביו/קישורים בקבוצות וואטסאפ ופייסבוק, `track_link_generator.html` (בודק — אין שם דומיין), הודעת ה-pin בקבוצות.
- הודעות שכבר נשלחו ימשיכו לעבוד דרך ה-301.
