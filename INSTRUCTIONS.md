# הנחיות הפעלה — מערכת פרסומים, מחלקת יחסים בינלאומיים

---

## קבצים בפרויקט

| קובץ | תיאור |
|---|---|
| `faculty_config.json` | רשימת 25 חברי הסגל |
| `fetch_publications.py` | הסקריפט ששואב פרסומים מ-OpenAlex |
| `index.html` | דף התצוגה הציבורי |
| `admin.html` | ממשק ניהול הסגל |
| `.github/workflows/update.yml` | עדכון חודשי אוטומטי |

---

## שלב 1 — הכנת הסביבה (Mac)

```bash
# 1. וודא שהסביבה הוירטואלית פעילה (תמיד לפני הרצה)
source ~/ir-venv/bin/activate

# 2. וודא שהספרייה מותקנת
python3 -c "import requests; print('OK')"
```

---

## שלב 2 — בדיקת ריצה ראשונה

```bash
# נווט לתיקייה
cd ~/Downloads/ir-publications

# בדיקה על 2 חברי סגל בלבד
python3 fetch_publications.py --test
```

**פלט תקין:**
```
[01/02] Daniel Schwartz... ✓ found (works: 12, cited: 340)
[02/02] Yehonatan Abramson... ✓ found (works: 8, cited: 120)
✅ סיום! סה"כ פרסומים שנשמרו: 20
```

---

## שלב 3 — ריצה עם חיתוך (לבדיקת עדכונים)

```bash
# שאב רק עד סוף 2023
python3 fetch_publications.py --until-year 2023
```
שמור את ה-`publications.json` שנוצר.  
אחר כך הרץ שוב ללא חיתוך — תראה שפרסומי 2024–2025 מתווספים.

---

## שלב 4 — ריצה מלאה

```bash
python3 fetch_publications.py
```
לוקח כ-3–5 דקות. יוצר `publications.json`.

---

## שלב 5 — GitHub Pages (פרסום לאינטרנט)

1. פתח חשבון ב-[github.com](https://github.com)
2. צור repository חדש: `ir-publications` (Public)
3. העלה את כל הקבצים
4. Settings → Pages → Deploy from branch → main → Save
5. האתר יהיה זמין בכתובת:  
   `https://YOUR-USERNAME.github.io/ir-publications/`

---

## שלב 6 — הטמעה באתר המחלקה

```html
<iframe
  src="https://YOUR-USERNAME.github.io/ir-publications/"
  width="100%" height="900px" style="border:none;"
  title="Department Publications">
</iframe>
```

---

## ניהול שוטף

**להוספה/הסרה של חבר סגל:**
1. פתח `admin.html` בדפדפן
2. בצע שינויים
3. Export JSON → Download
4. העלה את `faculty_config.json` ל-GitHub
5. Actions → Run workflow

**עדכון ידני:**
- GitHub → Actions → Update Publications → Run workflow

**עדכון אוטומטי:**  
רץ לבד ב-1 לכל חודש ✅
