# רשימת העברה למחשב העבודה — שלב העלאת האתר לרשת

> **תאריך:** 2026-05-07
> **מטרה:** להעביר את כל מה שצריך מהמחשב הנייד הפרטי של לימור אל המחשב המרכזי באקו אויל (כונן O), כדי להמשיך את העבודה שם על העלאת האתר לרשת.

---

## 🎯 מה אנחנו מעבירים בשלב הזה

**רק** מה שדרוש להעלאת האתר. את שאר הפרויקט (מערכת הניהול, סקריפטים פייתון, קבצי דאטה) **אל תעבירי עכשיו** — נטפל בהם כשנגיע לשלב של מערכת הניהול.

---

## ✅ רשימת קבצים להעתקה ל-USB

### 1. תיקיית האתר במלואה
**מקור:** `C:\Users\lio2e\Documents\AI_DEV\eco_oil_platform\website\`
**יעד ב-USB:** `D:\website_deployment\website\`

זאת התיקייה החשובה ביותר — היא מכילה את כל הקבצים של האתר (8 דפים, CSS, JS, תמונות, תעודות).

### 2. קובץ הוראות הסקיל לפריסה
**מקור:** `C:\Users\lio2e\Documents\AI_DEV\eco_oil_platform\DEPLOYMENT_SKILL.md`
**יעד ב-USB:** `D:\website_deployment\DEPLOYMENT_SKILL.md`

הקובץ המקיף עם כל ההוראות איך להעלות אתר לרשת — מ-א' עד ת'.

### 3. הפרומפט ל-Claude במחשב העבודה
**מקור:** `C:\Users\lio2e\Documents\AI_DEV\eco_oil_platform\WORK_CLAUDE_PROMPT.md`
**יעד ב-USB:** `D:\website_deployment\WORK_CLAUDE_PROMPT.md`

ההודעה הפותחת שתדביקי ל-Claude במחשב העבודה כדי לעדכן אותה.

### 4. קובץ הכללים הראשי של הפרויקט (CLAUDE.md)
**מקור:** `C:\Users\lio2e\Documents\AI_DEV\eco_oil_platform\website\CLAUDE.md`
**יעד ב-USB:** `D:\website_deployment\CLAUDE.md`

זה הקובץ שבפעם שעברה החלטנו לדלג עליו — עכשיו הזמן לקחת אותו. מכיל את כל ההיסטוריה של החלטות העיצוב והכללים של הפרויקט.

### 5. קובץ ה-README של הפרויקט (אם קיים ועדכני)
**מקור:** `C:\Users\lio2e\Documents\AI_DEV\eco_oil_platform\README.md`
**יעד ב-USB:** `D:\website_deployment\README.md`

---

## 📦 גודל כולל משוער

- תיקיית האתר: בערך 700 מגה (עם כל התמונות)
- שאר הקבצים: זניח (פחות ממגה כל אחד)
- **סך הכל: ~700 מגה**

USB בגודל 4 ג'יגה ומעלה יספיק בקלות.

---

## 🔄 איך מעבירים למחשב העבודה

1. חברי USB למחשב הנייד הפרטי שלך.
2. אני אעתיק את כל הקבצים האלה אוטומטית ל-USB (תאשרי לי).
3. תוציאי את ה-USB בצורה בטוחה (Eject).
4. תיקחי אותו למשרד.
5. תחברי למחשב העבודה.
6. תפעילי את Claude Code שם.
7. תדביקי לה את התוכן של `WORK_CLAUDE_PROMPT.md` (או תגידי לה לקרוא אותו ישירות מה-USB).
8. היא תנחה אותך מאיפה להעתיק לאן.

---

## 📍 מיקום היעד במחשב העבודה

הכל ילך אל **`O:\eco_oil_platform\`** — אותה תיקייה שכבר יצרנו בשבוע שעבר עבור התעודות.

המבנה הסופי שם יהיה:

```
O:\eco_oil_platform\
├── website\                       ← חדש: כל קבצי האתר
│   ├── index.html
│   ├── about.html
│   ├── services-offered.html
│   ├── industrial-consulting.html
│   ├── eco-depot.html
│   ├── partners.html
│   ├── export-of-waste.html
│   ├── types-of-waste-water.html
│   ├── cleaning_certificate.html
│   ├── release_certificate.html
│   ├── style.css
│   ├── subpage.css
│   ├── about.css
│   ├── eco-depot.css
│   ├── export.css
│   ├── services.css
│   ├── script.js
│   ├── CLAUDE.md
│   └── images\
│       └── ... (כל התמונות, כולל cert\ שכבר שם)
├── DEPLOYMENT_SKILL.md            ← חדש: סקיל הפריסה
├── WORK_CLAUDE_PROMPT.md          ← חדש: לעיון בלבד
├── WORK_RULES.md                  ← קיים מהפעם הקודמת
├── _build_cleaning_cert.py        ← קיים
├── _build_release_cert.py         ← קיים
├── _add_un_lookup.py              ← קיים
├── טנקו_NEW_DESIGN.xlsx           ← קיים
└── ... (שאר קבצי התעודות הקיימים)
```

---

## ⚠️ דברים שלא להעביר עכשיו (מערכת הניהול — לעתיד)

הקבצים הבאים הם של מערכת הניהול ולא נדרשים בשלב הנוכחי:
- `dashboard.py`, `run.py`, `crew_analysis.py`, `prepare_data.py`, `check_db.py`, `seed_demo_data.py`, `vision_agent.py`, `email_agent_*.py`, `fix_font.py`
- `src/`, `data/`, `output/`, `artifacts/`, `tests/`
- `venv/` (סביבה וירטואלית — נבנית מחדש)
- `requirements.txt` (ייתכן שכן צריך, אבל לא דחוף)
- כל קבצי ה-`.docx` (מסמכי Word פנימיים)
- `_eftco_*.json`, `_materials.json`, `_pricelist_*.json`, `_tanko_*.json` (קבצי דאטה ישנים)

---

## 🔚 בסוף ההעברה

אחרי שכל הקבצים במחשב העבודה — Claude שם תדריך אותך **דרך הסקיל `DEPLOYMENT_SKILL.md`** איך להעלות את האתר לרשת. הסקיל כתוב מאפס בהנחה שאת לא יודעת כלום על הנושא — לא תהיה חסרה לך אף הוראה.

*עדכון אחרון: 2026-05-07*
