# -*- coding: utf-8 -*-
"""Readiness report: what's missing for isotanks CURRENTLY ON-SITE (by status)."""
import os, io
from collections import Counter
os.environ.pop("DATABASE_URL", None)
from src.app import create_app
from src.app.db import DepotIsotankVisit

# on-site / in-yard statuses (NOT left, not on-the-way, not cancelled)
ON_SITE = ["באחסון", "בטיפול שטיפה", "בתיקון", "מוכן לשחרור", "הכנה לשחרור"]

app = create_app()
log = io.StringIO()
with app.app_context():
    rows = DepotIsotankVisit.query.filter(DepotIsotankVisit.status.in_(ON_SITE)).all()
    N = len(rows)
    def has(v): return v not in (None, "", "—")

    with_customer = sum(1 for v in rows if has(v.company))
    no_storage_date = sum(1 for v in rows if not v.storage_in_date)
    with_material = [v for v in rows if has(v.last_material)]
    no_material = N - len(with_material)
    no_un = sum(1 for v in with_material if not has(v.un_number))
    no_class = sum(1 for v in with_material if not has(v.hazard_class))

    by_status = Counter(v.status for v in rows)
    by_company = Counter(v.company for v in rows if has(v.company))

    log.write(f"מכלים שנמצאים כעת באתר (לפי סטטוס): {N}\n\n")
    log.write("פילוח לפי סטטוס:\n")
    for s, c in by_status.most_common():
        log.write(f"  {c:>4}  {s}\n")
    log.write(f"\nמשויכים ללקוח: {with_customer} מתוך {N}\n\n")
    log.write("חוסרים להשלמה:\n")
    log.write(f"  חסר תאריך כניסה לאחסון: {no_storage_date}\n")
    log.write(f"  חסר חומר אחרון: {no_material}\n")
    log.write(f"  חסר מספר אום (מהקטלוג): {no_un}\n")
    log.write(f"  חסר Class סכנה (מהקטלוג): {no_class}\n\n")
    log.write("לקוחות עם מכלים באתר כעת (מספר מכלים):\n")
    for name, c in by_company.most_common():
        log.write(f"  {c:>3}  {name}\n")

open(r"C:\eco_oil_platform_git\_gaps.md", "w", encoding="utf-8").write(log.getvalue())
print("done")
