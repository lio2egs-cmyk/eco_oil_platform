# -*- coding: utf-8 -*-
"""גשר "הנכסים שלי" של הדיפו — שלב 3 במפת הדרכים (אישור יואב 02/09/2026).

רץ כצעד בסבב השעתי במחשב של לימור (ecooil_bridge_hourly.py). קריאה בלבד:
מעתיק את הקובץ החי לעותק-צל זמני, קורא מגיליון "רישום תנועות איזוטנקים"
את השורות שנמצאות באתר (לפי הסטטוס), ודוחף תמונת-מצב מלאה לענן —
הפורטל מציג ללקוח את הנכסים שלו לפי "גורם מחוייב אחסנה" (עוגן הכתיבים).

שום כתיבה לקובץ החי — את בקשות השחרור מבצע הגשר של יעל (הכותב היחיד).

שימוש:
  python depot_assets_push.py                    # ריצה מלאה
  python depot_assets_push.py --dry-run          # קריאה בלבד, בלי דחיפה
  python depot_assets_push.py --api-base http://127.0.0.1:5000
"""
import argparse
import io
import os
import shutil
import sys
import tempfile
import time
from datetime import date, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(r"C:\eco_oil_platform_git\.env")
os.environ.pop("DATABASE_URL", None)

import requests

LIVE = r"O:\SHTIFOT\מערכת ניהול אקו דיפו\EcoDepot.xlsx"
SHEET = "רישום תנועות איזוטנקים"
DEFAULT_API_BASE = "https://depot.eco-oil.co.il"

# הסטטוסים שנחשבים "נמצא באתר" (עמודה I) — כמו ONSITE_STATUSES בגשר של יעל
ONSITE = {"בדרך להיכנס", "באחסון", "בטיפול שטיפה", "בתיקון",
          "הכנה לשחרור", "מוכן לשחרור"}

# אינדקסים (0-based) לפי כותרות הגיליון: A מס' ביקור, B מכל, D גורם מחוייב
# אחסנה, F חומר אחרון, I סטטוס, J תאריך הגעה, R תאריך כניסה לאחסון (חלק
# מהשורות ממולאות רק בה — לימור 04/09: 90 שורות הוצגו "—" בפורטל בגללה),
# AK תאריך משוער ליציאה
COL = dict(visit=0, tank=1, payer=3, material=5, status=8, arrival=9,
           storage_entry=17, est_exit=36)


def _iso_date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return None


def read_snapshot():
    """קריאת השורות באתר מעותק-צל של הקובץ החי (הקובץ המקורי לא נפתח)."""
    import openpyxl
    tmp = os.path.join(tempfile.gettempdir(), "_depot_assets_shadow.xlsx")
    last_err = None
    for _ in range(5):
        try:
            shutil.copyfile(LIVE, tmp)
            last_err = None
            break
        except OSError as exc:
            last_err = exc
            time.sleep(3)
    if last_err is not None:
        raise last_err

    wb = openpyxl.load_workbook(tmp, data_only=True, read_only=True)
    try:
        ws = wb[SHEET]
        items = []
        for row in ws.iter_rows(min_row=2, max_col=40, values_only=True):
            status = (str(row[COL["status"]] or "")).strip()
            if status not in ONSITE:
                continue
            vid = (str(row[COL["visit"]] or "")).strip()
            tank = (str(row[COL["tank"]] or "")).strip()
            if not vid or not tank:
                continue
            items.append({
                "visit_id": vid,
                "tank": tank,
                "storage_payer": (str(row[COL["payer"]] or "")).strip(),
                "status": status,
                "material": (str(row[COL["material"]] or "")).strip(),
                "arrival_date": _iso_date(row[COL["arrival"]])
                                or _iso_date(row[COL["storage_entry"]]),
                "est_exit_date": _iso_date(row[COL["est_exit"]]),
            })
        return items
    finally:
        wb.close()
        try:
            os.remove(tmp)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    args = ap.parse_args()

    items = read_snapshot()
    by_status = {}
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1
    print(f"snapshot: {len(items)} onsite rows {by_status}")

    if args.dry_run:
        print("dry-run — not pushing")
        return 0

    token = os.environ.get("ECOOIL_BRIDGE_TOKEN")
    if not token:
        print("ERROR: ECOOIL_BRIDGE_TOKEN missing")
        return 1
    r = requests.post(
        args.api_base + "/depot/portal/bridge/assets",
        json={"items": items},
        headers={"Authorization": "Bearer " + token},
        timeout=120,
    )
    print("push:", r.status_code, r.text[:200])
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
