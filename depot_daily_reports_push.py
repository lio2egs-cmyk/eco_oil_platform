# -*- coding: utf-8 -*-
"""גשר הדוחות היומיים של הדיפו — בקשת לקוחות הפריוריטי (לימור 08/09/2026).

טנקו והי טנק טוענים את דוח הפעילות היומי (אקסל) ישירות לפריוריטי, ולכן
הפורטל מגיש בדיוק את הקבצים שהמחולל הקיים (gen_daily_pdf.py) מפיק ומתייק —
אחד-לאחד, בלי הפקה מחדש. הכפתור זמין לכל לקוחות הדיפו (הכרעתה 08/09).

רץ כצעד בסבב השעתי במחשב של לימור (ecooil_bridge_hourly.py). קריאה בלבד:
  1. סריקת לקוחות\\{לקוח}\\{שנה}\\{חודש}\\דוחות יומיים\\דוח_יומי_DD-MM-YYYY.xlsx
  2. העלאה ל-B2 (אותו דלי כמו התעודות, קידומת depotdaily/; מניפסט מקומי
     נפרד מדלג על מה שכבר עלה, מעלה מחדש בשינוי גודל, לעולם לא מוחק בענן)
  3. דחיפת הרישום לענן — רק קבצים שאושרו ב-B2

שימוש:
  python depot_daily_reports_push.py                 # ריצה מלאה
  python depot_daily_reports_push.py --dry-run       # בלי העלאות, בלי דחיפה
  python depot_daily_reports_push.py --api-base http://127.0.0.1:5000
"""
import argparse
import io
import json
import os
import re
import sys
from datetime import date, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(r"C:\eco_oil_platform_git\.env")
os.environ.pop("DATABASE_URL", None)

import requests

SRC = r"O:\SHTIFOT\מערכת ניהול אקו דיפו\לקוחות"
KEY_PREFIX = "depotdaily/"
MANIFEST_PATH = r"C:\for_eco-depot\_depot_daily_b2_manifest.json"
DEFAULT_API_BASE = "https://depot.eco-oil.co.il"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# דוח_יומי_07-09-2026.xlsx → 2026-09-07
NAME_RE = re.compile(r"^דוח_יומי_(\d{2})-(\d{2})-(\d{4})\.xlsx$")


def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(m):
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    os.replace(tmp, MANIFEST_PATH)


def b2_client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['B2_ENDPOINT']}",
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APP_KEY"],
        config=Config(signature_version="s3v4"),
    )


def scan():
    """כל קובצי דוח_יומי_*.xlsx בתת-תיקיות "דוחות יומיים" של תיקיות הלקוחות."""
    items = []
    if not os.path.isdir(SRC):
        return items
    for top in sorted(os.listdir(SRC)):
        top_path = os.path.join(SRC, top)
        if not os.path.isdir(top_path) or top.startswith("~"):
            continue
        for root, dirs, files in os.walk(top_path):
            if os.path.basename(root) != "דוחות יומיים":
                continue
            for fname in files:
                m = NAME_RE.match(fname)
                if not m:
                    continue
                p = os.path.join(root, fname)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    rd = date(yy, mm, dd)
                except ValueError:
                    continue
                rel = os.path.relpath(p, SRC).replace("\\", "/")
                items.append({
                    "path": p,
                    "b2_key": KEY_PREFIX + rel,
                    "folder": top,
                    "report_date": rd.isoformat(),
                    "file_name": fname,
                    "file_date": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                    "size": st.st_size,
                })
    return items


def upload(items, manifest, dry_run=False, limit=None):
    todo = [it for it in items if manifest.get(it["b2_key"]) != it["size"]]
    if limit:
        todo = todo[:limit]
    print(f"daily reports found: {len(items)} | to upload: {len(todo)}")
    if dry_run or not todo:
        return 0, 0
    s3 = b2_client()
    bucket = os.environ["B2_BUCKET_CERTS"]
    up, failed = 0, 0
    for i, it in enumerate(todo, 1):
        try:
            with open(it["path"], "rb") as f:
                s3.put_object(Bucket=bucket, Key=it["b2_key"], Body=f,
                              ContentType=XLSX_MIME)
            manifest[it["b2_key"]] = it["size"]
            up += 1
            if up % 25 == 0:
                save_manifest(manifest)
            if up % 100 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} uploaded…")
        except Exception as e:
            failed += 1
            print(f"  FAILED {it['b2_key']}: {type(e).__name__}: {e}")
            if failed >= 10:
                print("  too many failures — stopping upload phase")
                break
    save_manifest(manifest)
    print(f"upload done: {up} uploaded, {failed} failed")
    return up, failed


def push(items, manifest, api_base, token, dry_run=False):
    payload = [{k: it[k] for k in
                ("b2_key", "folder", "report_date", "file_name",
                 "file_date", "size")}
               for it in items if it["b2_key"] in manifest]
    print(f"records to push: {len(payload)} (confirmed in B2)")
    if dry_run:
        return
    headers = {"Authorization": f"Bearer {token}"}
    added = updated = 0
    for i in range(0, len(payload), 500):
        chunk = payload[i:i + 500]
        r = requests.post(f"{api_base}/depot/portal/bridge/daily-reports",
                          json={"items": chunk},
                          headers=headers, timeout=120)
        r.raise_for_status()
        d = r.json()
        added += d.get("added", 0)
        updated += d.get("updated", 0)
    print(f"push done: {added} added, {updated} updated")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    args = ap.parse_args()

    token = os.environ.get("ECOOIL_BRIDGE_TOKEN")
    if not token:
        print("missing ECOOIL_BRIDGE_TOKEN")
        return 1
    if not os.path.isdir(SRC):
        print(f"source folder unreachable: {SRC} — skipping this cycle")
        return 0

    items = scan()
    manifest = load_manifest()
    upload(items, manifest, dry_run=args.dry_run, limit=args.limit)
    push(items, manifest, args.api_base, token, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
