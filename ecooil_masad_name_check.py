# -*- coding: utf-8 -*-
r"""
Eco-Oil bridge — בדיקת שם↔ח.פ. בגיליון "ח.פ.-היתר-תוקף" (לימור 11/11/2026).

מה קרה: ב-05/10 הגשר עדכן נכון את השורה של פלסטומולד (תוקף אמולסיה עד
31/10/2028). בין 11/10 ל-13/10 תא השם באותה שורה נדרס ידנית ל"צמחי" —
והחברה "נעלמה" מהגיליון בלי שאף אחד שם לב. לא הייתה שום בדיקה שהשם
בשורה עדיין שייך לח.פ. שלה.

מה הסקריפט עושה, בסבב השעתי (קריאה בלבד, לא כותב למסד לעולם):
  1. קורא את שני הגיליונות: "ח.פ.-היתר-תוקף" (B שם, E ח.פ.) ו"הצהרות"
     (B שם היצרן, D ח.פ.).
  2. בדיקה מול ההצהרות: לכל שורה עם ח.פ. שמופיע בגיליון ההצהרות — האם
     לשם בשורה יש לפחות מילה מבדילה אחת משותפת עם אחד השמות שנרשמו
     בהצהרות לאותו ח.פ.? אם אין — חשד לדריסה.
  3. בדיקה מול הסבב הקודם: זוכרים לכל ח.פ. את השמות שראינו
     (_masad_name_seen.json). שם חדש לח.פ. שאין לו שום מילה משותפת עם
     השמות הקודמים — חשד לדריסה (תופס גם חברות שאין להן הצהרה בגיליון).
     ח.פ. שנעלם לגמרי מהגיליון, ואין שורה בשם דומה — חשד למחיקה/דריסה
     (תיקון ח.פ. או מחיקת כפילות נשארים בשקט).
  נבדק 11/11 על כל 35 הגיבויים מאז 20/08 ברצף: התראה אחת בלבד — פלסטומולד.
  4. חשד חדש → מייל אחד ל-office עם טבלה ומה לעשות. כל חשד מדווח פעם
     אחת (_masad_name_check_reported.json); חשד שתוקן יוצא מהזיכרון, ואם
     יחזור — ידווח שוב.

שמות שהם בכוונה שונים מההצהרה (למשל שם באנגלית מול עברית) נרשמים
ברשימת ההיתרים ב-_masad_name_check_ok.json — לימור מאשרת, לא אני.

Usage:
  python ecooil_masad_name_check.py                 # production
  python ecooil_masad_name_check.py --dry-run       # הדפסה + קובץ תצוגה, בלי מייל ובלי זיכרון
  python ecooil_masad_name_check.py --masad-path C:\...copy.xlsx --state-dir C:\...tmp
"""
import argparse
import difflib
import html
import io
import json
import os
import smtplib
import sys
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(r"C:\eco_oil_platform_git\.env")

_keep_stdout = [sys.stdout]
from ecooil_masad_feed import _digits, _norm, MASAD_PATH, LOG_SHEET, SUMMARY_SHEET  # noqa: E402
_keep_stdout.append(sys.stdout)

STATE_DIR = r"C:\eco_oil_portal"
SEEN_FILE = "_masad_name_seen.json"
REPORTED_FILE = "_masad_name_check_reported.json"
OK_FILE = "_masad_name_check_ok.json"
PREVIEW_PATH = r"C:\eco_oil_portal\preview\masad_name_check_preview.html"
MAIL_TO = ["office@eco-oil.co.il"]

# מילים שלא מבדילות בין חברות — לא נחשבות "מילה משותפת"
GENERIC = {
    "בע", "מ", "בעמ", "חברה", "חברת", "תעשיות", "תעשייה", "תעשיה", "ישראל",
    "אתר", "מפעל", "מפעלי", "שירותים", "שירותי", "ושירותים", "ייצור", "יצור",
    "הנדסה", "סחר", "אחזקות", "קבוצת", "קבוצה", "מרכז", "סניף", "ltd", "inc",
    "co", "company", "israel", "industries", "the", "שותפות", "מוגבלת",
    "אגודה", "שיתופית", "חקלאית", "של", "את", "גם",
}


def _tokens(name):
    toks = set()
    for t in _norm(name).lower().split():
        if t.startswith("ו") and len(t) > 3 and t[1:] in GENERIC:
            continue
        if t in GENERIC or len(t) < 2 or t.isdigit():
            continue
        toks.add(t)
    return toks


def _tok_match(a, b):
    """שתי מילים "זהות": שוויון, אחת מכילה את השנייה (≥3 אותיות), או כתיב
    קרוב (מכשור/מיכשור)."""
    if a == b:
        return True
    if min(len(a), len(b)) >= 3 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def same_company(name, others):
    """True אם לשם יש מילה מבדילה משותפת עם אחד השמות האחרים. שם שאין בו
    מילה מבדילה בכלל (רק מילים כלליות) — לא שופטים, מחזירים True."""
    mine = _tokens(name)
    if not mine:
        return True
    for o in others:
        theirs = _tokens(o)
        if not theirs:
            continue
        if any(_tok_match(a, b) for a in mine for b in theirs):
            return True
    return False


def read_masad(path):
    """→ (summary_rows, ledger_names). summary_rows = [(row, name, hp)];
    ledger_names = {hp: set(names)}. קריאה בלבד."""
    from openpyxl import load_workbook
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        summary = []
        for i, r in enumerate(wb[SUMMARY_SHEET].iter_rows(min_row=2, max_col=5, values_only=True), 2):
            name = str(r[1] or "").strip()
            hp = _digits(r[4])
            if name or hp:
                summary.append((i, name, hp))
        ledger = {}
        for r in wb[LOG_SHEET].iter_rows(min_row=2, max_col=4, values_only=True):
            name = str(r[1] or "").strip()
            hp = _digits(r[3])
            if name and hp:
                ledger.setdefault(hp, set()).add(name)
    finally:
        wb.close()
    return summary, ledger


def find_suspects(summary, ledger, seen, ok_pairs):
    """→ רשימת חשדות [{row, name, hp, expected, why}]. ok_pairs = {(hp, name_norm)}."""
    out = []
    for row, name, hp in summary:
        if not hp or not name:
            continue
        if (hp, _norm(name)) in ok_pairs:
            continue
        led = ledger.get(hp)
        if led and not same_company(name, led):
            out.append({"row": row, "name": name, "hp": hp,
                        "expected": sorted(led), "why": "ledger"})
            continue
        prev = [n for n in seen.get(hp, []) if _norm(n) != _norm(name)]
        if prev and _norm(name) not in {_norm(n) for n in seen.get(hp, [])} \
                and not same_company(name, prev):
            out.append({"row": row, "name": name, "hp": hp,
                        "expected": sorted(prev), "why": "changed"})
    # ח.פ. שהיה בגיליון בסבב הקודם ונעלם לגמרי — נדרס גם הח.פ. או שהשורה נמחקה
    # אבל אם אותו שם עדיין בגיליון (עם ח.פ. אחר) — זה תיקון ח.פ., לא היעלמות
    # (בדיקה על כל הגיבויים: אסתילון 09/2026, פלגי מים 11/2026, ח.פ. של 8 ספרות)
    present = {hp for _r, _n, hp in summary if hp}
    # וגם שורה כפולה שנמחקה כשנשארה שורה בשם דומה (אסתילון, 08/09/2026).
    present_names = [n for _r, n, _hp in summary if n]
    for hp, names in seen.items():
        if hp in present or not names or (hp, "__missing__") in ok_pairs:
            continue
        if any(same_company(n, present_names) for n in names):
            continue
        out.append({"row": "—", "name": "(אין שורה)", "hp": hp,
                    "expected": sorted(names), "why": "missing"})
    return out


def update_seen(seen, summary, suspects):
    """שמות שנראו בסבב הזה נכנסים לזיכרון — חוץ מחשודים, כדי שדריסה לא
    "תתקבל" בשקט בסבב הבא."""
    bad = {(s["hp"], _norm(s["name"])) for s in suspects}
    for _row, name, hp in summary:
        if not hp or not name or (hp, _norm(name)) in bad:
            continue
        names = seen.setdefault(hp, [])
        if _norm(name) not in {_norm(n) for n in names}:
            names.append(name)
    return seen


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _td(s, extra=""):
    return f'<td style="border:1px solid #999;padding:6px 10px;vertical-align:top;{extra}">{html.escape(str(s))}</td>'


def build_html(suspects, masad_path):
    n = len(suspects)
    trs = []
    for s in suspects:
        src = ('בגיליון "הצהרות"' if s["why"] == "ledger" else "בבדיקה הקודמת")
        exp = " / ".join(s["expected"][:3])
        if s["why"] == "missing":
            todo = ("החברה הייתה בגיליון ועכשיו אין שום שורה עם הח.פ. שלה. "
                    "אם נמחקה או נדרסה בטעות: להחזיר מגיבוי. "
                    "אם המחיקה מכוונת: לכתוב ל-Claude לאשר.")
        else:
            todo = ("אם השם בשורה נדרס בטעות: להחזיר את השם הנכון. "
                    "אם זו באמת חברה אחרת: לתקן את הח.פ. בשורה. "
                    "אם השם נכון והשוני מכוון: לכתוב ל-Claude לאשר אותו.")
        trs.append("<tr>" + _td(s["row"]) + _td(s["name"]) + _td(s["hp"])
                   + _td(f"{exp} ({src})") + _td(todo, "max-width:340px;") + "</tr>")
    head = "".join(
        f'<td style="border:1px solid #999;padding:6px 10px;background:#eef3f2;"><b>{h}</b></td>'
        for h in ("שורה", "השם בשורה עכשיו", "ח.פ.", "השם שמתאים לח.פ. הזה", "מה לעשות"))
    return f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p><b>מה קרה:</b> {'בשורה אחת' if n == 1 else f'ב-{n} שורות'} בגיליון "{SUMMARY_SHEET}" השם
לא מתאים לח.פ. שבאותה שורה. ייתכן שהשם נדרס בטעות (כמו פלסטומולד, 10/2026).</p>
<p><b>מה לעשות:</b> לפתוח את המסד ולבדוק כל שורה לפי העמודה האחרונה.
הבדיקה לא שינתה כלום בקובץ.</p>
<table dir="rtl" style="border-collapse:collapse;"><tr>{head}</tr>{"".join(trs)}</table>
<p style="color:#555;">הקובץ: {html.escape(masad_path)}</p>
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
    ap.add_argument("--state-dir", default=STATE_DIR)
    args = ap.parse_args()

    if not os.path.exists(args.masad_path):
        print(f"ERROR: masad not found at {args.masad_path}")
        return 1
    seen_p = os.path.join(args.state_dir, SEEN_FILE)
    rep_p = os.path.join(args.state_dir, REPORTED_FILE)
    ok_p = os.path.join(args.state_dir, OK_FILE)

    summary, ledger = read_masad(args.masad_path)
    seen = _load(seen_p, {})
    ok_pairs = {(_digits(x.get("hp")), _norm(x.get("name"))) for x in _load(ok_p, [])}
    suspects = find_suspects(summary, ledger, seen, ok_pairs)
    print(f"summary rows: {len(summary)} | ledger ids: {len(ledger)} | suspects: {len(suspects)}")

    reported = _load(rep_p, {})
    cur_keys = {f'{s["hp"]}|{_norm(s["name"])}' for s in suspects}
    # חשד שתוקן יוצא מהזיכרון — אם יחזור, ידווח שוב
    reported = {k: v for k, v in reported.items() if k in cur_keys}
    new = [s for s in suspects if f'{s["hp"]}|{_norm(s["name"])}' not in reported]
    for s in new:
        print(f'  NEW row {s["row"]}: hp {s["hp"]} name {s["name"]!r} expected {s["expected"][:3]} ({s["why"]})')
    print(f"new to report: {len(new)}")

    if args.dry_run:
        if new:
            os.makedirs(os.path.dirname(PREVIEW_PATH), exist_ok=True)
            with open(PREVIEW_PATH, "w", encoding="utf-8") as f:
                f.write("<!doctype html><meta charset='utf-8'><title>בדיקת שמות במסד</title>"
                        + build_html(new, args.masad_path))
            print(f"dry-run: preview written to {PREVIEW_PATH} (no mail, no state)")
        return 0

    if new:
        n = len(new)
        subject = ("שם לא מתאים לח.פ. בגיליון התוקפים במסד" if n == 1
                   else f"{n} שמות לא מתאימים לח.פ. בגיליון התוקפים במסד")
        send_html(subject, build_html(new, args.masad_path))
        print(f"mail sent → {', '.join(MAIL_TO)}: {subject}")
        for s in new:
            reported[f'{s["hp"]}|{_norm(s["name"])}'] = {
                "row": s["row"], "name": s["name"], "reported_at": datetime.now().isoformat()}
    _save(rep_p, reported)
    _save(seen_p, update_seen(seen, summary, suspects))
    return 0


if __name__ == "__main__":
    sys.exit(main())
