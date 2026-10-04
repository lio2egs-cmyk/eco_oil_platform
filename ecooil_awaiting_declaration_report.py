# -*- coding: utf-8 -*-
r"""
Eco-Oil bridge — דוח "שורות חסומות שכבר יש להן הצהרה" (לימור 28/09/2026).

מה קרה: הפורטל חוסם אישור פריקה כל עוד בריכוז כתוב "אין הצהרת יצרן"
(או "לא לפרסם - אין הצהרה" בעמודת הפורטל). כשההצהרה מוסדרת אף אחד לא
מזכיר לעדכן את ההערה — ושי מוורידיס ראה חסימה על שורה שכבר הייתה בסדר.

מה הסקריפט עושה, בסבב השעתי הקיים (קריאה בלבד, לא נוגע בריכוז ולא משחרר):
  1. השורות החסומות בגלל "אין הצהרה" מתמונת-המצב המקומית (אחרי שלב הקורא).
  2. הצלבה מול גיליון "ח.פ.-היתר-תוקף" במסד: אותו לקוח, אותו זרם, תוקף ≥ היום.
  3. התאמה חדשה → מייל אחד ל-office עם טבלה ומה לעשות. כל שורה מדווחת
     פעם אחת (זיכרון ב-_awaiting_declaration_reported.json); הצהרה שחודשה
     (תאריך תוקף אחר) מדווחת שוב.

Usage:
  python ecooil_awaiting_declaration_report.py            # production
  python ecooil_awaiting_declaration_report.py --dry-run  # הדפסה + קובץ תצוגה, בלי מייל ובלי זיכרון
"""
import argparse
import html
import io
import json
import os
import smtplib
import sys
from datetime import date, datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(r"C:\eco_oil_platform_git\.env")

# שני הסקריפטים המיובאים עוטפים את stdout ב-UTF-8 בעצמם. עטיפה ישנה שמאבדת
# את ההפניה האחרונה סוגרת את הזרם שמתחתיה — לכן שומרים הפניה לכל עטיפה.
_keep_stdout = [sys.stdout]
from ecooil_masad_feed import _norm  # noqa: E402  (שם מנורמל: בלי גרשיים/נקודות/בע"מ)
_keep_stdout.append(sys.stdout)
from ecooil_validity_push import MASAD_PATH, read_rows  # noqa: E402
_keep_stdout.append(sys.stdout)

STATE_PATH = r"C:\eco_oil_portal\_awaiting_declaration_reported.json"
PREVIEW_PATH = r"C:\eco_oil_portal\preview\awaiting_declaration_report_preview.html"
MAIL_TO = ["office@eco-oil.co.il"]

# הזרמים שיש להם עמודת תוקף במסד; זרמים אחרים (צמחי, סניטרי...) אין מול מה להצליב
CHECKABLE_STREAMS = {"מינרלי", "אמולסיה", "בסיס", "חומצה", "מי שטיפה", "מזוט"}


def _parse_ddmmyyyy(s):
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        return None


def _name_match(a, b):
    """שוויון אחרי נרמול, או הכלה של שם משמעותי (≥ 8 תווים) — לדוח בלבד."""
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 8 and shorter in longer


def find_released(events, masad_rows, today):
    """[(event, valid_until:date, masad_name)] — שורות חסומות שכבר יש להן הצהרה בתוקף."""
    idx = [(_norm(r["name"]), r) for r in masad_rows]
    out = []
    for ev in events:
        stream = (ev.stream_norm or "").strip()
        if stream not in CHECKABLE_STREAMS:
            continue
        cust = _norm(ev.customer)
        # ללקוח שיש לו שורה משלו במסד (שם זהה) מצליבים רק מולה. הכלת-שם היא
        # גיבוי ללקוח בלי שורה זהה — אחרת "נמל מספנות ישראל" מקבל את התוקף של
        # "מספנות ישראל", חברה אחרת עם ח.פ. אחר (לימור 04/10/2026).
        exact = [(nname, r) for nname, r in idx if cust and nname == cust]
        best = None
        for nname, r in (exact or idx):
            if not _name_match(cust, nname):
                continue
            vu = _parse_ddmmyyyy(r["streams"].get(stream) or "")
            if vu and vu >= today and (best is None or vu > best[0]):
                best = (vu, r["name"])
        if best:
            out.append((ev, best[0], best[1]))
    return out


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def _td(s, extra=""):
    return f'<td style="border:1px solid #999;padding:6px 10px;vertical-align:top;{extra}">{html.escape(str(s))}</td>'


def build_html(rows, today):
    """rows = [(event, valid_until, masad_name, has_pdf)]"""
    n = len(rows)
    trs = []
    for ev, vu, mname, has_pdf in rows:
        year = ev.event_date.year if hasattr(ev.event_date, "year") else str(ev.event_date)[:4]
        where = f'ריכוז {year}, גיליון {ev.source_sheet or ""}, שורה {ev.source_row or ""}'
        if has_pdf:
            todo = ('לעדכן את ההערה בשורה (למשל "אישור שוחרר '
                    f'{today:%d.%m.%y} - לאחר הסדרת הצהרת יצרן"), ולרוקן את '
                    '"הערות למערכת פורטל" אם מלאה.')
        else:
            todo = "להפיק את האישור ולתייק, ואז לעדכן את ההערה בשורה."
        ev_date = ev.event_date.strftime("%d/%m/%Y") if hasattr(ev.event_date, "strftime") else str(ev.event_date)
        trs.append("<tr>" + _td(ev_date) + _td(ev.customer or "") + _td(ev.stream_norm or "")
                   + _td(vu.strftime("%d/%m/%Y")) + _td(where)
                   + _td("יש" if has_pdf else "אין") + _td(todo, "max-width:360px;") + "</tr>")
    head = "".join(
        f'<td style="border:1px solid #999;padding:6px 10px;background:#eef3f2;"><b>{h}</b></td>'
        for h in ("תאריך פריקה", "לקוח", "זרם", "ההצהרה בתוקף עד", "איפה בריכוז",
                  "קובץ אישור", "מה לעשות"))
    return f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p><b>מה קרה:</b> {'שורה אחת חסומה' if n == 1 else f'{n} שורות חסומות'} בפורטל בגלל
"אין הצהרת יצרן", אבל במסד כבר יש ללקוח הצהרה בתוקף לזרם הזה.</p>
<p><b>מה לעשות:</b> לעדכן את ההערה בריכוז לפי העמודה האחרונה בטבלה.</p>
<table dir="rtl" style="border-collapse:collapse;"><tr>{head}</tr>{"".join(trs)}</table>
<p style="color:#555;">קבצי הריכוז: Z:\\Eco_General\\ריכוז חודשי\\&lt;שנה&gt;\\</p>
</div>"""


def send_html(subject, body_html):
    host = os.environ.get("MAIL_HOST")
    user = os.environ.get("MAIL_USERNAME")
    pw = os.environ.get("MAIL_PASSWORD")
    from_addr = os.environ.get("MAIL_FROM_ADDRESS") or user
    from_name = os.environ.get("MAIL_FROM_NAME", "")
    if not (host and user and pw and from_addr):
        raise RuntimeError("mail channel not configured in .env (MAIL_*)")
    msg = MIMEText(body_html, "html", "utf-8")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr)) if from_name else from_addr
    msg["To"] = ", ".join(MAIL_TO)
    msg["Subject"] = Header(subject, "utf-8")
    with smtplib.SMTP(host, int(os.environ.get("MAIL_PORT", "587")), timeout=30) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(user, pw)
        s.sendmail(from_addr, MAIL_TO, msg.as_string())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--masad-path", default=MASAD_PATH)
    args = ap.parse_args()
    today = date.today()

    from src.app import create_app
    from src.app.db import EcoOilUnloadEvent
    app = create_app()
    with app.app_context():
        events = (EcoOilUnloadEvent.query
                  .filter(EcoOilUnloadEvent.doc_status == "awaiting_declaration")
                  .order_by(EcoOilUnloadEvent.event_date.asc()).all())
        # מנתקים מהסשן: כל השדות כבר נטענו
        for ev in events:
            _ = (ev.id, ev.event_date, ev.customer, ev.stream_norm, ev.pdf_path,
                 ev.source_sheet, ev.source_row)
    print(f"awaiting_declaration rows: {len(events)}")
    if not events:
        save_state({}) if not args.dry_run else None
        return 0

    if not os.path.exists(args.masad_path):
        print(f"ERROR: masad not found at {args.masad_path}")
        return 1
    masad_rows = read_rows(args.masad_path)
    released = find_released(events, masad_rows, today)
    print(f"with a valid declaration in the masad: {len(released)}")

    state = load_state()
    awaiting_ids = {str(ev.id) for ev in events}
    # שורה שכבר לא חסומה יוצאת מהזיכרון — אם תיחסם שוב, תדווח שוב
    state = {k: v for k, v in state.items() if k in awaiting_ids}

    new_rows = []
    for ev, vu, mname in released:
        key = str(ev.id)
        prev = state.get(key)
        if prev and prev.get("valid_until") == vu.isoformat():
            continue
        has_pdf = bool(ev.pdf_path) and os.path.exists(ev.pdf_path)
        new_rows.append((ev, vu, mname, has_pdf))
    for ev, vu, mname, has_pdf in new_rows:
        print(f"  {ev.event_date} | {ev.customer} | {ev.stream_norm} | valid to {vu:%d/%m/%Y}"
              f" | {ev.source_sheet} r{ev.source_row} | pdf={'yes' if has_pdf else 'no'}")
    print(f"new to report: {len(new_rows)}")

    if not new_rows:
        if not args.dry_run:
            save_state(state)
        return 0

    body = build_html(new_rows, today)
    n = len(new_rows)
    subject = ("שורה חסומה בפורטל שכבר יש לה הצהרה" if n == 1
               else f"{n} שורות חסומות בפורטל שכבר יש להן הצהרה")
    if args.dry_run:
        os.makedirs(os.path.dirname(PREVIEW_PATH), exist_ok=True)
        with open(PREVIEW_PATH, "w", encoding="utf-8") as f:
            f.write(f"<!doctype html><meta charset='utf-8'><title>{html.escape(subject)}</title>{body}")
        print(f"dry-run: preview written to {PREVIEW_PATH} (no mail, no state)")
        return 0

    send_html(subject, body)
    print(f"mail sent → {', '.join(MAIL_TO)}: {subject}")
    for ev, vu, mname, has_pdf in new_rows:
        state[str(ev.id)] = {"valid_until": vu.isoformat(), "reported_at": datetime.now().isoformat(),
                             "customer": ev.customer, "stream": ev.stream_norm}
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
