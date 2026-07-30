# -*- coding: utf-8 -*-
"""
Declaration-expiry reminders — the OFFICE side (runs on Limor's PC, scheduled
monthly on the 15th). Reads the masad validity sheet ח.פ.-היתר-תוקף
(read-only, safe while open in Excel):

  col A "סוג לקוח"  — Limor's routing (30/07/2026): "ישיר" = direct customer;
                       a company name = the responsible transporter; rows with
                       an empty customer name are formatting/template rows.
  col B "לקוח"       — customer (+ optional site suffix)
  6 stream date cols — declaration expiry per stream (first-of-month dates)

Computes: (a) everyone expiring NEXT month (a month-and-a-half of notice),
(b) everyone already expired and not renewed, (c) data-quirk notes — and POSTs
to the cloud endpoint /admin/declaration-reminders, which enriches with
portal-account status and emails ONE consolidated pilot email to the office.
No customer receives anything at this stage.

Usage:
  venv\\Scripts\\python.exe ecooil_declaration_reminders.py            # window = next month
  ... --window 09/2026                                                # explicit window
  ... --dry-run                                                       # compute + log, no POST
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime

MASAD = r"Z:\Eco_General\מסד מלא_הצהרות_היתרים_מובילים.xlsx"
SHEET = "ח.פ.-היתר-תוקף"
API_BASE = os.environ.get("ECOOIL_API_BASE", "https://portal.eco-oil.co.il")
LOG_DIR = r"C:\eco_oil_portal\reminder_logs"

STREAM_COLS = {"מינרלי": 5, "אמולסיה": 7, "בסיס": 9, "חומצה": 11, "מי שטיפה": 13, "מזוט": 15}

# routing values that mean "no reminder for this row"
SKIP_ROUTING = {"לקוח לא קיים יותר"}


def _norm(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _mm_yyyy(d):
    return f"{d.month:02d}/{d.year}"


def _bridge_token():
    # same source as the bridge push: the repo .env
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("ECOOIL_BRIDGE_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise SystemExit("ECOOIL_BRIDGE_TOKEN not found in .env")


def collect(window_month, window_year, today):
    import warnings
    warnings.filterwarnings("ignore")
    import openpyxl

    wb = openpyxl.load_workbook(MASAD, read_only=True, data_only=True)
    ws = wb[SHEET]

    direct, via_map, expired, notes = [], {}, [], []
    seen_pairs = set()  # (customer, routing) — the masad has duplicate rows (multi-permit)

    for row in ws.iter_rows(min_row=2, values_only=True):
        customer = _norm(row[1])
        routing = _norm(row[0])
        if not customer:
            continue  # template/formatting row (Limor 30/07: no meaning)
        if routing in SKIP_ROUTING:
            continue
        expiring_here, expired_here = [], []
        for stream, col in STREAM_COLS.items():
            d = _to_date(row[col]) if col < len(row) else None
            if d is None:
                continue
            if d.year == window_year and d.month == window_month:
                expiring_here.append({"stream": stream, "month": _mm_yyyy(d)})
            elif d < today:
                expired_here.append({"stream": stream, "month": _mm_yyyy(d)})
        if not expiring_here and not expired_here:
            continue
        key = (customer, routing)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        if not routing:
            notes.append(f"{customer} — יש תאריכי תוקף אך עמודת 'סוג לקוח' ריקה (למי לנתב?)")
        elif routing != "ישיר" and ("+" in routing or routing == "עקיף"):
            notes.append(f"{customer} — שיוך לא חד-משמעי בעמודת 'סוג לקוח': \"{routing}\"")

        if expiring_here:
            if routing == "ישיר":
                direct.append({"customer": customer, "expiring": expiring_here})
            elif routing and "+" not in routing and routing != "עקיף":
                via_map.setdefault(routing, []).append(
                    {"customer": customer, "expiring": expiring_here})
        if expired_here:
            expired.append({"customer": customer,
                            "routing": routing or "?",
                            "streams": expired_here})
    wb.close()

    via = [{"transporter": t, "customers": lst} for t, lst in sorted(via_map.items())]

    # The masad carries a long tail of ancient expiries (2019+, mostly inactive
    # customers) — the email shows only the last 3 months as the actionable
    # chase list, and states the older count explicitly (no silent cap).
    cutoff_m = today.month - 3
    cutoff = date(today.year - 1, cutoff_m + 12, 1) if cutoff_m <= 0 else date(today.year, cutoff_m, 1)
    recent = []
    older = 0
    for x in expired:
        yy, mm = max(tuple(map(int, s["month"].split("/")[::-1])) for s in x["streams"])
        if date(yy, mm, 1) >= cutoff:
            recent.append(x)
        else:
            older += 1
    recent.sort(key=lambda x: max(tuple(map(int, s["month"].split("/")[::-1])) for s in x["streams"]),
                reverse=True)
    return direct, via, recent, older, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", help="MM/YYYY; default = next month")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = date.today()
    if args.window:
        m, y = args.window.split("/")
        wm, wy = int(m), int(y)
    else:
        wm, wy = (1, today.year + 1) if today.month == 12 else (today.month + 1, today.year)
    window = f"{wm:02d}/{wy}"

    direct, via, expired, expired_older, notes = collect(wm, wy, today)
    payload = {"window": window, "direct": direct, "via": via,
               "expired": expired, "expired_older": expired_older, "notes": notes}

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{today.isoformat()}_{wm:02d}-{wy}.json")
    with io.open(log_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    summary = (f"window {window}: direct={len(direct)} via-transporters={len(via)} "
               f"expired={len(expired)} notes={len(notes)}")
    if args.dry_run:
        print("[dry-run] " + summary + f" -> {log_path}")
        return

    req = urllib.request.Request(
        API_BASE + "/admin/declaration-reminders",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + _bridge_token()})
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode("utf-8"))
    print(summary + f" | sent={resp.get('sent')}")
    if not resp.get("sent"):
        sys.exit(1)


if __name__ == "__main__":
    main()
