# -*- coding: utf-8 -*-
"""
Eco-Depot bridge — LOCAL/dev sync.
Reads EcoDepot.xlsx (read-only) and loads the per-visit data into the portal DB,
mapped BY HEADER NAME (column letters drift). Dev version writes straight to the
local SQLite DB; the production version will run on an office PC and push to the
cloud portal API on a schedule.
"""
import os, io
from datetime import datetime, date

# Safety: never let this dev sync touch the production Postgres.
os.environ.pop("DATABASE_URL", None)

import openpyxl
from src.app import create_app
from src.app.db import (
    db, DepotIsotankVisit, DepotRoadtankerVisit, DepotStorageCharge, DepotRepair,
)

CANDIDATES = [
    r"O:\SHTIFOT\מערכת ניהול אקו דיפו\EcoDepot.xlsx",   # live master (real source)
    r"C:\for_eco-depot\EcoDepot_DRAFT.xlsx",            # local snapshot fallback (dev, off-network)
]
SRC = next((p for p in CANDIDATES if os.path.exists(p)), None)

# ---- type coercion ----
def to_date(v):
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    return None
def to_float(v):
    try: return float(v)
    except (TypeError, ValueError): return None
def to_int(v):
    try: return int(float(v))
    except (TypeError, ValueError): return None
def to_str(v):
    if v is None: return None
    s = str(v).strip()
    return s or None
def coerce(kind, v):
    return {"date": to_date, "int": to_int, "float": to_float}.get(kind, to_str)(v)

# ---- per-sheet specs: field -> (header, kind) ----
ISO = {
    "visit_no": ("מס' ביקור", "str"), "isotank_number": ("מספר איזוטנק", "str"),
    "company": ("גורם מחוייב אחסנה", "str"), "billed_to": ("גורם מחוייב אחסנה", "str"),
    "last_material": ("חומר אחרון", "str"), "un_number": ("מספר אומ", "str"),
    "hazard_class": ("Class סכנה", "str"), "status": ("סטטוס", "str"),
    "arrival_date": ("תאריך הגעה", "date"), "storage_in_date": ("תאריך כניסה לאחסון", "date"),
    "storage_out_date": ("תאריך יציאה מאחסון", "date"), "exit_site_date": ("תאריך יציאה מהאתר", "date"),
    "storage_days": ("סהכ ימי אחסנה", "int"), "daily_rate": ("תעריף יומי", "float"),
    "storage_total": ("סהכ אחסון", "float"), "wash_date": ("תאריך שטיפה", "date"),
    "wash_total": ("סהכ שטיפה", "float"), "entry_hour": ("שעת כניסה לאחסון", "str"),
    "exit_hour": ("שעת יציאה מאחסון", "str"),
}
RT = {
    "visit_no": ("מס' ביקור", "str"), "tanker_number": ("מספר מכלית", "str"),
    "company": ("חברה / סוכן", "str"), "billed_to": ("גורם מחוייב", "str"),
    "entry_date": ("תאריך כניסה", "date"), "entry_hour": ("שעת כניסה", "str"),
    "exit_date": ("תאריך יציאה", "date"), "exit_hour": ("שעת יציאה", "str"),
    "last_material": ("חומר אחרון", "str"), "group": ("קבוצת רואדטנקר", "str"),
    "un_number": ("מספר אומ", "str"), "hazard_class": ("Class", "str"),
    "compartments_used": ("מספר תאים בשימוש", "int"), "cert_status": ("סטטוס תעודה", "str"),
    "repairs_note": ("תיקונים", "str"), "wash_total": ("סהכ שטיפה", "float"),
    "final_total": ("סהכ סופי", "float"),
}
STORAGE = {
    "visit_no": ("מס' ביקור", "str"), "isotank_number": ("מספר איזוטנק", "str"),
    "company": ("חברה", "str"), "billed_to": ("גורם מחוייב", "str"),
    "billing_month": ("חודש החיוב", "date"), "storage_days": ("ימי אחסנה", "int"),
    "daily_rate": ("תעריף יומי", "float"), "total": ("סהכ", "float"),
    "billing_status": ("סטטוס חיוב", "str"),
}
REPAIRS = {
    "repair_id": ("Repair_ID", "str"), "visit_no": ("מס' ביקור", "str"),
    "isotank_number": ("מס' איזוטנק", "str"), "repair_date": ("תאריך תיקון", "date"),
    "repair_name": ("שם תיקון", "str"), "qty": ("כמות", "float"),
    "unit_price": ("מחיר ליחידה", "float"), "line_total": ("סכום שורה", "float"),
    "billed_to": ("מי מחויב", "str"),
}

def rt_extra(kwargs, cell):
    mats = [to_str(cell(f"חומר תא {i}")) for i in range(1, 7)]
    mats = [m for m in mats if m]
    kwargs["compartment_materials"] = " / ".join(dict.fromkeys(mats)) if mats else None

def iso_extra(kwargs, cell):
    # Customer = 'גורם מחוייב אחסנה' (D), fallback 'גורם מחוייב שטיפה' (E) — mirrors the cert logic.
    if not kwargs.get("company"):
        kwargs["company"] = to_str(cell("גורם מחוייב שטיפה"))

def load(wb, sheet, model, spec, required, extra=None):
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    header = next(it)
    idx = {h: i for i, h in enumerate(header) if h}
    missing = [hdr for (hdr, _) in spec.values() if hdr not in idx]
    model.query.delete()
    n = 0
    companies = {}
    for excel_row, row in enumerate(it, start=2):
        def cell(h):
            i = idx.get(h)
            return row[i] if (i is not None and i < len(row)) else None
        kwargs = {f: coerce(k, cell(h)) for f, (h, k) in spec.items()}
        if not kwargs.get(required):
            continue
        if hasattr(model, "source_row"):
            kwargs["source_row"] = excel_row
        if extra:
            extra(kwargs, cell)
        db.session.add(model(**kwargs))
        n += 1
        c = kwargs.get("company")
        if c:
            companies[c] = companies.get(c, 0) + 1
    return n, companies, missing

log = io.StringIO()
if not SRC:
    log.write("ERROR: EcoDepot file not found.\n")
else:
    app = create_app()
    with app.app_context():
        # snapshot tables are wiped+reloaded every run — drop them so schema changes (e.g. source_row) take effect
        for m in (DepotIsotankVisit, DepotRoadtankerVisit, DepotStorageCharge, DepotRepair):
            m.__table__.drop(db.engine, checkfirst=True)
        db.create_all()
        wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
        jobs = [
            ("איזוטנקים", "רישום תנועות איזוטנקים", DepotIsotankVisit, ISO, "isotank_number", iso_extra),
            ("רואדטנקים", "רישום תנועות רואדטנקרים", DepotRoadtankerVisit, RT, "tanker_number", rt_extra),
            ("חיובי אחסנה", "חיוב_אחסנה_חודשי", DepotStorageCharge, STORAGE, "isotank_number", None),
            ("תיקונים", "תיקונים", DepotRepair, REPAIRS, "repair_id", None),
        ]
        iso_companies = {}
        for label, sheet, model, spec, req, extra in jobs:
            n, companies, missing = load(wb, sheet, model, spec, req, extra)
            log.write(f"{label}: {n} rows" + (f"  | MISSING headers {missing}" if missing else "") + "\n")
            if model is DepotIsotankVisit:
                iso_companies = companies
        db.session.commit()
        wb.close()
        log.write("\ncompanies (from isotanks):\n")
        for name, cnt in sorted(iso_companies.items(), key=lambda x: -x[1]):
            log.write(f"  {cnt:>4}  {name}\n")

open(r"C:\eco_oil_platform_git\_bridge_result.md", "w", encoding="utf-8").write(log.getvalue())
print(log.getvalue())
