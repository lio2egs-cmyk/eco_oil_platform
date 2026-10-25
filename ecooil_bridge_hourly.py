# -*- coding: utf-8 -*-
"""
Eco-Oil bridge — the HOURLY production cycle, run by Windows Task Scheduler
on Limor's office PC (daily 07:00-18:00, every hour):

    1. ecooil_bridge_sync.py       — ריכוז workbooks → local snapshot DB (read-only)
    2. ecooil_pdf_matcher.py       — link rows to filed certificate PDFs
    3. ecooil_manifest_matcher.py  — link rows to signed טופס מלווה scans
    4. ecooil_bridge_push.py       — upload new PDFs+manifests to B2 + push snapshot

A lock file prevents overlapping runs; each run appends to a daily log under
C:\\eco_oil_portal\\bridge_logs\\.

התראה במייל (לימור 25/10/2026, אחרי יומיים של כשל שקט כשהשרת נפל):
כשל בודד שמתאושש בסבב הבא קורה בערך פעם בשבוע — לא מתריעים עליו.
מהכשל השני ברצף יוצא מייל ל-office@ (מגיע גם לנייד של לימור), תזכורת
פעם ביום כל עוד זה נמשך, ומייל "חזר לעבוד" בסבב התקין הראשון.
"""
import json
import os
import smtplib
import subprocess
import sys
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

REPO = r"C:\eco_oil_platform_git"
PY = os.path.join(REPO, r"venv\Scripts\python.exe")
ENV_FILE = os.path.join(REPO, ".env")
LOG_DIR = r"C:\eco_oil_portal\bridge_logs"
LOCK = os.path.join(LOG_DIR, "_run.lock")
LOCK_STALE_MINUTES = 50
ALERT_STATE = os.path.join(LOG_DIR, "_alert_state.json")
ALERT_TO = "office@eco-oil.co.il"
ALERT_AFTER_FAILURES = 2
ALERT_REPEAT_HOURS = 24

STEPS = [
    ("reader", "ecooil_bridge_sync.py", []),
    ("matcher", "ecooil_pdf_matcher.py", []),
    ("manifest-matcher", "ecooil_manifest_matcher.py", []),
    ("push", "ecooil_bridge_push.py", []),
    # הזנת הצהרות מאושרות למסד (לימור 10/08) — מדלג בשקט כשהמסד פתוח
    ("masad-feed", "ecooil_masad_feed.py", []),
    # תמונת גיליון ח.פ.-היתר-תוקף → טבלת לקוחות החומ"ס בפורטל (לימור 03/09);
    # קריאה בלבד — עובד גם כשהמסד פתוח
    ("validity-push", "ecooil_validity_push.py", []),
    # דוח "שורות חסומות שכבר יש להן הצהרה" למשרד (לימור 28/09) — קריאה בלבד
    # מתמונת-המצב ומהמסד; כל שורה מדווחת פעם אחת; לא נוגע בריכוז.
    ("awaiting-report", "ecooil_awaiting_declaration_report.py", []),
    # תיוק הסכמות + סריקות חתומות לתיקיות הלקוחות (לימור 12/08)
    ("filing", "ecooil_filing_feed.py", []),
    # תעודות שטיפה של הדיפו → B2 → פורטל (לימור 23/08) — אחרון בכוונה:
    # תקלה בו לא עוצרת אף שלב של האויל.
    ("depot-certs", "depot_certs_push.py", []),
    # תמונת "הנכסים שלי" לפורטל הדיפו (שלב 3, אישור יואב 02/09) — קריאה
    # בלבד מעותק-צל; אחרון כדי שתקלה בו לא תעצור אף שלב אחר.
    ("depot-assets", "depot_assets_push.py", []),
    # הדוח היומי לאקסל בפורטל (בקשת לקוחות הפריוריטי, לימור 08/09) —
    # קריאה בלבד מתיקיות הלקוחות; מניפסט מדלג על מה שכבר עלה.
    ("depot-daily", "depot_daily_reports_push.py", []),
    # תזכורות חתימה ללקוח (7 / 14 ימים) + התראה למשרד אחרי 21 (לימור 23/09);
    # הענן מחליט מי בתור וחותם כל שלב — הרצה שעתית לא שולחת פעמיים.
    # אחרון בכוונה: תקלה בו לא עוצרת אף שלב אחר.
    ("sign-reminders", "ecooil_signature_reminders.py", []),
    # בקרת ערוץ התנועות לטנקו (מייל כל שעתיים + API, לימור 22/10/2026) —
    # מחשב אחר מזה שדוחף (הגשר אצל יעל); קריאה בלבד, תמיד יוצא 0.
    ("movements-check", "depot_movements_check.py", []),
]


def _load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _send_alert(subject, body):
    env = _load_env()
    host, user, pw = env.get("MAIL_HOST"), env.get("MAIL_USERNAME"), env.get("MAIL_PASSWORD")
    from_addr = env.get("MAIL_FROM_ADDRESS") or user
    if not (host and user and pw and from_addr):
        raise RuntimeError("mail channel not configured in .env (MAIL_*)")
    msg = MIMEText(body, "plain", "utf-8")
    from_name = env.get("MAIL_FROM_NAME", "")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr)) if from_name else from_addr
    msg["To"] = ALERT_TO
    msg["Subject"] = Header(subject, "utf-8")
    with smtplib.SMTP(host, int(env.get("MAIL_PORT", "587")), timeout=30) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(user, pw)
        s.sendmail(from_addr, [ALERT_TO], msg.as_string())


def _explain(step, err_tail):
    """מה זה אומר, בשפה של לימור."""
    low = err_tail.lower()
    if ("network path was not found" in low or "winerror 53" in low
            or "'z:\\" in low or "'o:\\" in low or "unreachable" in low):
        return ("כנראה שהכונן המרכזי לא זמין מהמחשב של לימור (השרת כבוי או מנותק).\n"
                "מה לבדוק: שהשרת דלוק, ושהכוננים Z: ו-O: נפתחים במחשב.")
    if "connection" in low or "timeout" in low or "timed out" in low or "max retries" in low:
        return ("כנראה תקלת תקשורת מול הענן (הפורטל / האחסון).\n"
                "מה לבדוק: שיש אינטרנט במשרד ושהפורטל נפתח בדפדפן.")
    return f"השלב '{step}' נכשל מסיבה שלא זוהתה אוטומטית — לפתוח שיחה עם Claude ולהדביק את המייל."


def _alert(ok, failed_step, err_tail, log_path):
    """מייל בכשל השני ברצף, תזכורת יומית, ומייל חזרה. כשל במייל לעולם לא
    מפיל את הסבב — הוא נרשם ביומן וינוסה שוב בסבב הבא."""
    try:
        with open(ALERT_STATE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    now = datetime.now()
    subject = body = None
    if ok:
        if st.get("alerted"):
            since = st.get("failing_since", "")
            subject = "הגשר השעתי חזר לעבוד"
            body = (f"הגשר השעתי במחשב של לימור עבר בהצלחה ב-{now:%d/%m/%Y %H:%M}.\n"
                    f"הוא היה בתקלה מאז {since} ({st.get('failures', 0)} סבבים נכשלו).\n"
                    "מה שהצטבר בזמן התקלה נקלט בסבב הזה — אין צורך בפעולה.")
        else:
            st = {}
    else:
        st["failures"] = st.get("failures", 0) + 1
        st.setdefault("failing_since", f"{now:%d/%m/%Y %H:%M}")
        st["step"] = failed_step
        last = st.get("last_mail")
        due = (st["failures"] >= ALERT_AFTER_FAILURES and
               (not last or (now - datetime.fromisoformat(last)).total_seconds() >= ALERT_REPEAT_HOURS * 3600))
        if due:
            again = " (תזכורת — עדיין לא עובד)" if st.get("alerted") else ""
            subject = f"תקלה: הגשר השעתי לא עובד{again}"
            body = (f"הגשר השעתי במחשב של לימור נכשל {st['failures']} פעמים ברצף, מאז {st['failing_since']}.\n"
                    "כל עוד זה נמשך: תעודות חדשות, דוחות יומיים ותמונת הנכסים לא מגיעים לפורטלים.\n\n"
                    f"{_explain(failed_step, err_tail)}\n\n"
                    f"השלב שנכשל: {failed_step}\n"
                    f"היומן: {log_path}\n\n"
                    f"פרטי השגיאה:\n{err_tail[-1500:]}\n\n"
                    f"(התראה אוטומטית. חוזרת פעם ב-{ALERT_REPEAT_HOURS} שעות כל עוד התקלה נמשכת, "
                    "ומייל נוסף יגיע כשהגשר יחזור לעבוד.)")
    sent_note = ""
    if subject:
        try:
            _send_alert(subject, body)
            sent_note = f"alert mail sent: {subject}"
            if ok:
                st = {}
            else:
                st["alerted"] = True
                st["last_mail"] = now.isoformat(timespec="seconds")
        except Exception as e:
            # המצב נשמר כמו שהוא, כך שהמייל (התראה או חזרה) ינוסה שוב בסבב הבא
            sent_note = f"alert mail FAILED: {type(e).__name__}: {e}"
    with open(ALERT_STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    return sent_note


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d") + ".log")

    if os.path.exists(LOCK):
        age_min = (datetime.now().timestamp() - os.path.getmtime(LOCK)) / 60
        if age_min < LOCK_STALE_MINUTES:
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"\n[{datetime.now():%H:%M}] skipped — previous run still going ({age_min:.0f} min)\n")
            return 0
        os.remove(LOCK)

    open(LOCK, "w").close()
    ok = True
    failed_step, err_tail = "", ""
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"\n===== run {datetime.now():%Y-%m-%d %H:%M} =====\n")
            for name, script, extra in STEPS:
                started = datetime.now()
                r = subprocess.run(
                    [PY, os.path.join(REPO, script)] + extra,
                    cwd=REPO, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=45 * 60,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                took = (datetime.now() - started).seconds
                tail = "\n".join((r.stdout or "").strip().splitlines()[-6:])
                log.write(f"[{name}] exit {r.returncode} ({took}s)\n{tail}\n")
                if r.returncode != 0:
                    err_tail = "\n".join((r.stderr or "").strip().splitlines()[-10:])
                    log.write(f"[{name}] STDERR:\n{err_tail}\n")
                    ok, failed_step = False, name
                    break
            note = _alert(ok, failed_step, err_tail, log_path)
            if note:
                log.write(note + "\n")
            log.write(f"===== {'OK' if ok else 'FAILED'} {datetime.now():%H:%M} =====\n")
    except Exception as e:
        # כשל של הסבב עצמו (לא של שלב) — גם הוא נספר ומתריע
        ok = False
        note = _alert(False, "bridge-runner", f"{type(e).__name__}: {e}", log_path)
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"===== FAILED (runner) {type(e).__name__}: {e} | {note} =====\n")
    finally:
        if os.path.exists(LOCK):
            os.remove(LOCK)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
