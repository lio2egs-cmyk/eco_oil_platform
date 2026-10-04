# -*- coding: utf-8 -*-
"""
Eco-Oil — the weekly ריכוז for Ravit (finance), automated (Limor, 24/09/2026).

What Limor did by hand every Thursday: copy the rows that were added or fixed
since the last send (she kept them red) into a new weekly sheet of the month's
file in ...\לרוית, paint them black, mail the file to Ravit with Yoav in cc.

What this script does instead, every Thursday from Task Scheduler on Limor's PC:

    1. reads the live ריכוז workbook read-only (safe while it is open in Excel),
       for the previous and the current month;
    2. keeps its own ledger of what was already sent (per certificate code +
       a fingerprint of the row's values) under C:\\eco_oil_portal\\ravit_weekly —
       this replaces the red/black colouring; the live workbook is never written;
    3. new complete rows → a new weekly sheet in the month's file for Ravit
       (same columns, formats and formulas as her sheets); rows that were sent
       before and changed since are added to the same sheet first, with an
       short automatic note in Limor's wording ("תוקן משקל", "התקבל טופס
       מלווה, הופק אישור") — exactly like her "+תוספות" sheets;
    4. rebuilds the 'ריכוז מלא' sheet (whole month so far) on every run;
    5. backs the month file up to C: before writing, then mails the file to
       Ravit (cc Yoav + office) from the portal mailbox.

Rows without a certificate code (date typed, rest still empty) are not sent.
A week with nothing new sends a short notice to the office only.

Usage:
    ecooil_ravit_weekly.py                 normal Thursday run
    ecooil_ravit_weekly.py --dry-run       write to the preview folder, no mail, no ledger change
    ecooil_ravit_weekly.py --date 2026-10-01   pretend today is that date
    ecooil_ravit_weekly.py --no-mail       write the file, skip the mail (mail stays pending)
"""
import argparse
import copy
import glob
import json
import os
import shutil
import smtplib
import sys
import traceback
from datetime import date, datetime, time, timedelta
from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import openpyxl
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------- settings ---
ENV_FILE = r"C:\eco_oil_platform_git\.env"
SRC_BASE = r"Z:\Eco_General\ריכוז חודשי"
WORK_DIR = r"C:\eco_oil_portal\ravit_weekly"
LEDGER = os.path.join(WORK_DIR, "ledger.json")
LOG_FILE = os.path.join(WORK_DIR, "log.txt")
BACKUP_DIR = os.path.join(WORK_DIR, "backups")
PREVIEW_DIR = os.path.join(WORK_DIR, "preview")
KEEP_BACKUPS = 12

MAIL_TO = ["ksafim@eco-oil.co.il"]
MAIL_CC = ["yoav@eco-oil.co.il", "office@eco-oil.co.il"]
OFFICE = "office@eco-oil.co.il"

HEB_MONTHS = ["ינואר", "פברואר", "מארס", "אפריל", "מאי", "יוני",
              "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
FULL_SHEET = "ריכוז מלא"

# The 17 columns Ravit gets, in order (A..Q). R "הערות למערכת פורטל" stays home.
HEADERS = ["מס' תעודה", "קוד_רנדומלי", "תאריך", "מספר הרכב", "חברת ההובלה", "לקוח",
           "כתובת", "חיוב", "סיווג החומר", "משקל כניסה", "משקל יציאה", "משקל נטו",
           "משקל מוצהר", "סוג אריזה", "מס' אריזות", "שעת יציאה", "הערות"]
COL_WIDTHS = {"A": 9.0, "B": 12.8, "C": 10.1, "D": 9.0, "E": 26.0, "F": 41.6, "G": 14.5,
              "H": 41.0, "I": 9.0, "Q": 26.6}
NUM_FMT = {10: "#,##0", 11: "#,##0", 12: "#,##0.00", 13: "#,##0.00", 16: "h:mm"}
# fields compared for "did this row change since it was sent" (0-based indexes
# into A..Q). L and M are derived from J and K, so they are not compared.
COMPARE_IDX = [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 14, 15, 16]
FIELD_NAMES = {i: HEADERS[i] for i in COMPARE_IDX}


# ------------------------------------------------------------------ helpers --
def log(msg):
    os.makedirs(WORK_DIR, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        print(line)
    except Exception:
        pass


def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def norm(v):
    """Comparable, JSON-safe form of a cell value."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f == int(f) else repr(round(f, 4))
    if isinstance(v, datetime):
        if v.hour or v.minute:
            return v.strftime("%H:%M") if v.year == 1899 else v.strftime("%d/%m/%Y %H:%M")
        return v.strftime("%d/%m/%Y")
    if isinstance(v, time):
        return v.strftime("%H:%M")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    return str(v).strip()


def fingerprint(values):
    return {str(i): norm(values[i]) for i in COMPARE_IDX}


def month_key(y, m):
    return f"{y:04d}-{m:02d}"


def src_path(year):
    return os.path.join(SRC_BASE, str(year), f"ריכוז{year}_pivot.xlsx")


def src_sheet_name(year, month):
    return f"{HEB_MONTHS[month - 1]}_{year % 100:02d}"


def ravit_dir(year):
    return os.path.join(SRC_BASE, str(year), "לרוית")


def ravit_path(year, month):
    """The month file for Ravit; accepts the older 'חודש שנה.xlsx' spelling."""
    d = ravit_dir(year)
    for name in (f"{HEB_MONTHS[month - 1]}_{year}.xlsx", f"{HEB_MONTHS[month - 1]} {year}.xlsx"):
        if os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    return os.path.join(d, f"{HEB_MONTHS[month - 1]}_{year}.xlsx")


# ------------------------------------------------------------------ ledger ---
def load_ledger():
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            return json.load(f)
    return {"months": {}, "pending_mail": []}


def save_ledger(ledger):
    os.makedirs(WORK_DIR, exist_ok=True)
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LEDGER)


def seed_month_from_ravit_file(path):
    """First contact with a month that already has a file for Ravit: everything
    in that file counts as sent, with the values Ravit actually received (a row
    fixed since then will therefore show up as a correction on the first run)."""
    rows = {}
    if not os.path.exists(path):
        return rows
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = [ws for ws in wb.worksheets if ws.title != FULL_SHEET]
        if FULL_SHEET in wb.sheetnames:
            sheets.append(wb[FULL_SHEET])   # last = most recent picture, overrides
        for ws in sheets:
            seen = {}
            for r in ws.iter_rows(min_row=2, max_col=17, values_only=True):
                vals = list(r) + [None] * (17 - len(r))
                code = norm(vals[1])
                if not code:
                    continue
                n = seen.get(code, 0) + 1
                seen[code] = n
                key = code if n == 1 else f"{code}#{n}"
                rows[key] = {"fp": fingerprint(vals), "sent_on": "seed", "sheet": ws.title}
    finally:
        wb.close()
    return rows


# ------------------------------------------------------------------ source ---
def read_source_month(year, month):
    """All complete rows (with a certificate code) of one month sheet, in sheet
    order. Returns list of dicts {key, values(17)}, or None if sheet missing."""
    path = src_path(year)
    if not os.path.exists(path):
        log(f"MISSING source workbook: {path}")
        return None
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        name = src_sheet_name(year, month)
        if name not in wb.sheetnames:
            log(f"source sheet {name} not found in {os.path.basename(path)}")
            return None
        ws = wb[name]
        rows, seen = [], {}
        for r in ws.iter_rows(min_row=1, max_col=17, values_only=True):
            vals = list(r) + [None] * (17 - len(r))
            if vals[1] == HEADERS[1]:
                continue
            code = norm(vals[1])
            if not code:
                continue
            n = seen.get(code, 0) + 1
            seen[code] = n
            key = code if n == 1 else f"{code}#{n}"
            rows.append({"key": key, "values": vals})
        return rows
    finally:
        wb.close()


def parse_day(v):
    """Day-of-month of a ריכוז date cell (text dd/mm/yyyy or a real date)."""
    if isinstance(v, (datetime, date)):
        return v.day
    s = norm(v)
    try:
        return int(s.split("/")[0])
    except Exception:
        return None


# ------------------------------------------------------------------ writer ---
THIN = Side(style="thin")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def style_sheet(ws, n_rows):
    ws.sheet_view.rightToLeft = True
    ws.sheet_view.zoomScale = 90
    ws.row_dimensions[1].height = 37.5
    for col, w in COL_WIDTHS.items():
        ws.column_dimensions[col].width = w
    for c in range(1, 18):
        cell = ws.cell(1, c)
        cell.font = Font(name="Calibri", size=14, bold=True)
        cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
        cell.border = BORDER
    for r in range(2, n_rows + 2):
        for c in range(1, 18):
            cell = ws.cell(r, c)
            cell.font = Font(name="Calibri", size=11)
            cell.alignment = Alignment(horizontal="right")
            cell.border = BORDER
            if c in NUM_FMT:
                cell.number_format = NUM_FMT[c]


def fill_sheet(ws, rows):
    """rows = list of 17-value lists (A..Q). L and M are written as Ravit's
    formulas, everything else as plain values."""
    ws.append(HEADERS)
    for i, vals in enumerate(rows, start=2):
        for c, v in enumerate(vals, start=1):
            if c == 12:
                v = f"=SUM(J{i}-K{i})"
            elif c == 13:
                v = f'=TEXT(L{i}/1000,"0.000")'
            elif isinstance(v, datetime) and v.year == 1899:
                v = v.time()
            ws.cell(i, c, v)
    style_sheet(ws, len(rows))


def unique_title(wb, title):
    t, n = title, 2
    while t in wb.sheetnames:
        t = f"{title} ({n})"
        n += 1
    return t[:31]


def week_title(run_day, year, month, has_fixes):
    """'20-24.9' = Sunday..run day of the run week, clamped to the month."""
    sunday = run_day - timedelta(days=(run_day.weekday() + 1) % 7)
    first = date(year, month, 1)
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
    if sunday > last:
        # the run week has no day of this month: late additions to a month that
        # is already over get their own name (Limor 04/10/2026)
        return f"השלמות {HEB_MONTHS[month - 1]}"
    start = max(sunday, first)
    end = min(run_day, last)
    if end < start:
        end = start
    t = f"{start.day}.{month}" if start == end else f"{start.day}-{end.day}.{month}"
    return t + ("+תוספות" if has_fixes else "")


def backup(path):
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    dst = os.path.join(BACKUP_DIR, f"{base}_{datetime.now():%Y-%m-%d_%H%M%S}.xlsx")
    shutil.copy2(path, dst)
    old = sorted(glob.glob(os.path.join(BACKUP_DIR, f"{base}_*.xlsx")))
    for p in old[:-KEEP_BACKUPS]:
        try:
            os.remove(p)
        except OSError:
            pass
    return dst


def write_month_file(path, week_rows, week_name, full_rows, dry_run):
    """Add the weekly sheet (if any rows) and rebuild 'ריכוז מלא'. Returns the
    path actually written and the final sheet title (or None)."""
    if dry_run:
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        out = os.path.join(PREVIEW_DIR, os.path.basename(path))
        if os.path.exists(path):
            shutil.copy2(path, out)
        elif os.path.exists(out):
            os.remove(out)
    else:
        out = path
        os.makedirs(os.path.dirname(out), exist_ok=True)
        b = backup(out)
        if b:
            log(f"backup: {b}")

    if os.path.exists(out):
        wb = openpyxl.load_workbook(out)
    else:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

    title = None
    if week_rows:
        title = unique_title(wb, week_name)
        idx = wb.sheetnames.index(FULL_SHEET) if FULL_SHEET in wb.sheetnames else len(wb.sheetnames)
        ws = wb.create_sheet(title, idx)
        fill_sheet(ws, week_rows)

    if FULL_SHEET in wb.sheetnames:
        wb.remove(wb[FULL_SHEET])
    ws_full = wb.create_sheet(FULL_SHEET)
    fill_sheet(ws_full, full_rows)
    if week_rows:
        wb.active = wb.sheetnames.index(title)
    wb.save(out)

    # verify: reopen and count
    chk = openpyxl.load_workbook(out, read_only=True)
    try:
        n_full = sum(1 for _ in chk[FULL_SHEET].iter_rows(min_row=2, values_only=True))
        n_week = sum(1 for _ in chk[title].iter_rows(min_row=2, values_only=True)) if title else 0
    finally:
        chk.close()
    if n_full != len(full_rows) or n_week != len(week_rows):
        raise RuntimeError(f"verification failed after save: full {n_full}/{len(full_rows)}, week {n_week}/{len(week_rows)}")
    return out, title


# -------------------------------------------------------------------- mail ---
def send_mail(env, subject, body, to, cc=(), attachment=None):
    host, user, pw = env.get("MAIL_HOST"), env.get("MAIL_USERNAME"), env.get("MAIL_PASSWORD")
    from_addr = env.get("MAIL_FROM_ADDRESS") or user
    from_name = env.get("MAIL_FROM_NAME", "")
    if not (host and user and pw and from_addr):
        raise RuntimeError("mail channel not configured in .env (MAIL_*)")
    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr)) if from_name else from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if attachment:
        with open(attachment, "rb") as f:
            part = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment",
                        filename=("utf-8", "", os.path.basename(attachment)))
        msg.attach(part)
    with smtplib.SMTP(host, int(env.get("MAIL_PORT", "587")), timeout=30) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(user, pw)
        s.sendmail(from_addr, list(to) + list(cc), msg.as_string())


def send_pending(ledger, env):
    still = []
    for p in ledger.get("pending_mail", []):
        try:
            send_mail(env, p["subject"], p["body"], p["to"], p.get("cc", ()), p.get("attachment"))
            log(f"pending mail sent: {p['subject']}")
        except Exception as exc:
            log(f"pending mail still failing: {p['subject']} — {exc}")
            still.append(p)
    ledger["pending_mail"] = still



# ------------------------------------------------------- correction notes ---
# Short, human wording for Ravit (Limor 24/09: "התקבל טופס מלווה, הופק אישור"
# rather than field names and old values). One phrase per kind of change,
# joined with " + " like Limor's own "הוחלף הגורם המחוייב + תוקן משקל".
CHANGE_PHRASES = [
    ((9, 10), "תוקן משקל"),
    ((7,), "הוחלף הגורם המחוייב"),
    ((3, 4), "שונה המוביל"),
    ((5,), "שונה שם הלקוח"),
    ((6,), "שונתה הכתובת"),
    ((8,), "שונה סיווג החומר"),
    ((13, 14), "תוקנה האריזה"),
    ((2,), "תוקן התאריך"),
    ((15,), "תוקנה שעת היציאה"),
]
# a note that said "no certificate yet, X missing" and is now gone = X arrived
MISSING_DOC_PHRASES = [
    ("טופס מלווה", "התקבל טופס מלווה, הופק אישור"),
    ("הצהרת יצרן", "התקבלה הצהרת יצרן, הופק אישור"),
    ("הצהרה", "התקבלה הצהרה, הופק אישור"),
]


def change_note(prev_fp, fp):
    changed = {i for i in COMPARE_IDX if prev_fp.get(str(i), "") != fp[str(i)]}
    parts = []
    for idxs, phrase in CHANGE_PHRASES:
        if changed.intersection(idxs):
            parts.append(phrase)
    if 16 in changed:
        old_note, new_note = prev_fp.get("16", ""), fp["16"]
        if old_note and not new_note:
            for key, phrase in MISSING_DOC_PHRASES:
                if "ללא אישור" in old_note and key in old_note:
                    parts.append(phrase)
                    break
            else:
                parts.append("ההערה הקודמת בוטלה")
        elif not parts:
            parts.append("עודכנה ההערה")
    return " + ".join(parts) if parts else "עודכן"


def diff_fields(prev_fp, fp):
    """Fields that differ, ignoring the serial (col A = row position): a row
    pushed down by rows inserted above it is not a correction (Limor 04/10/2026)."""
    return {i for i in COMPARE_IDX if i != 0 and prev_fp.get(str(i), "") != fp[str(i)]}


def join_note(current, note):
    """Ravit's notes column: the row's own note first, then what changed."""
    cur = norm(current)
    return f"{cur} | {note}" if cur else note


# ------------------------------------------------------------------- month ---
def process_month(year, month, run_day, ledger, env, dry_run, no_mail):
    mk = month_key(year, month)
    src_rows = read_source_month(year, month)
    if src_rows is None:
        return
    rpath = ravit_path(year, month)
    if mk not in ledger["months"]:
        seeded = seed_month_from_ravit_file(rpath)
        ledger["months"][mk] = {"rows": seeded}
        log(f"{mk}: ledger seeded from {os.path.basename(rpath) if seeded else 'nothing'} ({len(seeded)} rows)")
    sent = ledger["months"][mk]["rows"]

    new_rows, fixed_rows, shifted = [], [], []
    for row in src_rows:
        fp = fingerprint(row["values"])
        prev = sent.get(row["key"])
        if prev is None:
            new_rows.append(row)
        elif prev["fp"] != fp:
            if not diff_fields(prev["fp"], fp):
                shifted.append((row["key"], fp))   # only the serial moved
                continue
            note = change_note(prev["fp"], fp)
            vals = list(row["values"])
            vals[16] = join_note(vals[16], note)
            fixed_rows.append({"key": row["key"], "values": vals, "fp": fp, "note": note})
    # A row whose date / vehicle / customer / stream / exit time was edited gets
    # a NEW certificate code (the code is computed from those fields), so it
    # looks like "one row gone + one new row". Pair them by content and report
    # a correction instead of a fresh row: first the same unload (same date,
    # vehicle and exit time — e.g. "ממתין לפירוט" that got its details), then
    # the gone row that differs in the fewest fields (at most 3). Not by serial:
    # rows inserted above move the serials, and an inserted row can land on a
    # gone row's number.
    src_keys = {r["key"] for r in src_rows}
    gone = {k: v for k, v in sent.items() if k not in src_keys}
    if gone:
        pairs = []
        for i, row in enumerate(new_rows):
            fp = fingerprint(row["values"])
            for k, v in gone.items():
                same_unload = all(v["fp"].get(c, "") == fp[c] and fp[c] for c in ("2", "3", "15"))
                n_diff = len(diff_fields(v["fp"], fp))
                if same_unload or n_diff <= 3:
                    pairs.append((not same_unload, n_diff, i, k))
        paired = {}
        for _, _, i, k in sorted(pairs):
            if i not in paired and k not in paired.values():
                paired[i] = k
        still_new = []
        for i, row in enumerate(new_rows):
            fp = fingerprint(row["values"])
            old_key = paired.get(i)
            if old_key is None:
                still_new.append(row)
                continue
            prev = gone.pop(old_key)
            note = change_note(prev["fp"], fp)
            vals = list(row["values"])
            vals[16] = join_note(vals[16], note)
            fixed_rows.append({"key": row["key"], "values": vals, "fp": fp, "note": note, "old_key": old_key})
        new_rows = still_new
    log(f"{mk}: source {len(src_rows)} complete rows; new {len(new_rows)}; corrected {len(fixed_rows)}"
        f"; serial moved only {len(shifted)}")
    if gone:
        # sent earlier, now missing from the live sheet and not re-paired — a
        # deleted row; Ravit still has it, so this deserves a human look
        log(f"{mk}: NOTE {len(gone)} rows sent earlier are no longer in the source: {list(gone)[:10]}")

    full_rows = [r["values"] for r in src_rows]
    week_rows = [r["values"] for r in fixed_rows] + [r["values"] for r in new_rows]
    if not week_rows:
        # nothing new and nothing fixed: the month file is left untouched
        # (rebuilding 'ריכוז מלא' alone would change a file nobody is told about)
        log(f"{mk}: nothing new — month file left as is")
        if shifted and not dry_run:
            for k, fp in shifted:
                sent[k]["fp"] = fp
            save_ledger(ledger)
        return {"month": mk, "new": 0, "fixed": 0, "title": None, "file": rpath} if os.path.exists(rpath) else None

    title = week_title(run_day, year, month, bool(fixed_rows))
    out, title = write_month_file(rpath, week_rows, title if week_rows else None, full_rows, dry_run)
    log(f"{mk}: wrote {out} sheet={title!r} (rows {len(week_rows)}), {FULL_SHEET}={len(full_rows)}")

    if dry_run:
        return {"month": mk, "new": len(new_rows), "fixed": len(fixed_rows), "title": title, "file": out,
                "fixed_notes": [(r["key"], r["note"]) for r in fixed_rows]}

    # the rows are in Ravit's file now — record that before anything else
    stamp = run_day.isoformat()
    for k, fp in shifted:     # new serial remembered quietly, nothing was sent
        sent[k]["fp"] = fp
    for r in new_rows:
        sent[r["key"]] = {"fp": fingerprint(r["values"]), "sent_on": stamp, "sheet": title}
    for r in fixed_rows:
        if r.get("old_key"):
            sent.pop(r["old_key"], None)
        sent[r["key"]] = {"fp": r["fp"], "sent_on": stamp, "sheet": title}
    for k in gone:            # logged above; nothing left to pair them with
        sent.pop(k, None)
    save_ledger(ledger)

    if week_rows:
        subject = f"ריכוז {title}"
        body = (f"מצורף קובץ {HEB_MONTHS[month - 1]} {year} עם גיליון חדש \"{title}\": "
                f"{len(new_rows)} תעודות חדשות" +
                (f", {len(fixed_rows)} תיקונים לתעודות שנשלחו קודם (מסומנים בעמודת הערות)" if fixed_rows else "") +
                f".\nגיליון \"{FULL_SHEET}\" מעודכן לכל החודש עד כה.\n\n(נשלח אוטומטית מהמערכת של אקו אויל)")
        mail = {"subject": subject, "body": body, "to": MAIL_TO, "cc": MAIL_CC, "attachment": out}
        if no_mail:
            ledger["pending_mail"].append(mail)
            save_ledger(ledger)
            log(f"{mk}: mail kept pending (--no-mail): {subject}")
        else:
            try:
                send_mail(env, **mail)
                log(f"{mk}: mail sent to {MAIL_TO} cc {MAIL_CC}: {subject}")
            except Exception as exc:
                ledger["pending_mail"].append(mail)
                save_ledger(ledger)
                log(f"{mk}: MAIL FAILED ({exc}) — kept pending, will retry next run")
    return {"month": mk, "new": len(new_rows), "fixed": len(fixed_rows), "title": title, "file": out}


# -------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-mail", action="store_true")
    ap.add_argument("--date", help="pretend the run date is YYYY-MM-DD")
    args = ap.parse_args()
    run_day = date.fromisoformat(args.date) if args.date else date.today()
    log(f"=== run {'DRY ' if args.dry_run else ''}for {run_day}")
    env = load_env()
    ledger = load_ledger()
    if not args.dry_run and ledger.get("pending_mail") and not args.no_mail:
        send_pending(ledger, env)
        save_ledger(ledger)

    prev_first = (run_day.replace(day=1) - timedelta(days=1))
    months = [(prev_first.year, prev_first.month), (run_day.year, run_day.month)]
    results = []
    for y, m in months:
        try:
            r = process_month(y, m, run_day, ledger, env, args.dry_run, args.no_mail)
            if r:
                results.append(r)
        except Exception:
            log(f"{month_key(y, m)}: ERROR\n{traceback.format_exc()}")
            if not args.dry_run:
                try:
                    send_mail(env, "ריכוז לרוית — תקלה בהרצה השבועית",
                              f"ההרצה של {run_day} נכשלה בחודש {month_key(y, m)}:\n\n{traceback.format_exc()}",
                              [OFFICE])
                except Exception as exc:
                    log(f"could not mail the error to office: {exc}")

    sent_any = any(r["new"] or r["fixed"] for r in results)
    if not args.dry_run and not args.no_mail and not sent_any:
        try:
            send_mail(env, "ריכוז לרוית — אין חדש השבוע",
                      f"ההרצה של {run_day} לא מצאה תעודות חדשות או תיקונים מאז השליחה הקודמת. לא נשלח דבר לרוית.",
                      [OFFICE])
            log("nothing new — notice sent to office")
        except Exception as exc:
            log(f"nothing new — notice mail failed: {exc}")
    if args.dry_run:
        summary = os.path.join(PREVIEW_DIR, "summary.json")
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        with open(summary, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    log("=== done")


if __name__ == "__main__":
    main()
