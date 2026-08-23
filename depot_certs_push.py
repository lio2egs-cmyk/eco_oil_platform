# -*- coding: utf-8 -*-
"""גשר תעודות השטיפה של הדיפו — שלב 2 במפת הדרכים (לימור 23/08/2026).

רץ כצעד בסבב השעתי במחשב של לימור (ecooil_bridge_hourly.py, הכרעתה 23/08).
שלושה תפקידים:
  1. סריקה — קריאה בלבד — של O:\\SHTIFOT\\תעודות שטיפה: כל קובץ PDF בתיקיות
     הלקוחות משנת 2026 ואילך (הכרעתה 23/08; המבנה: לקוח\\שנה\\חודש\\מכל\\קובץ,
     עם וריאציות — הזיהוי גמיש לפי מקטע-שנה בנתיב).
  2. העלאה ל-B2 (אותו דלי כמו אישורי האויל, קידומת depotcerts/; מניפסט מקומי
     מדלג על מה שכבר עלה, מעלה מחדש בשינוי גודל, לעולם לא מוחק בענן).
  3. דחיפת הרישום לענן — רק קבצים שאושרו ב-B2, כדי שהפורטל לעולם לא יציע
     הורדה שאין מאחוריה קובץ (אותו עיקרון כמו pdf_key באויל).

בנוסף: פעם ביום (מהסבב הראשון אחרי 16:00) מפעיל את הסיכום היומי בענן —
מייל אחד לכל לקוח שהצטברו לו תעודות חדשות (הכרעתה 23/08).

שימוש:
  python depot_certs_push.py                    # ריצה מלאה
  python depot_certs_push.py --dry-run          # בלי העלאות, בלי דחיפה
  python depot_certs_push.py --seed             # הטענה ראשונית: מחתים notified
  python depot_certs_push.py --digest-now       # מפעיל את הסיכום מיד
  python depot_certs_push.py --api-base http://127.0.0.1:5000
"""
import argparse
import json
import os
import re
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(r"C:\eco_oil_platform_git\.env")
os.environ.pop("DATABASE_URL", None)

import requests

SRC = r"O:\SHTIFOT\תעודות שטיפה"
KEY_PREFIX = "depotcerts/"
MIN_YEAR = 2026
# תיקיות ברמה העליונה שאינן תיקיית-לקוח
EXCLUDE_TOP = {"_כל התעודות שהופקו", "אקסלים 2025", "ספקים לא פעילים"}
MANIFEST_PATH = r"C:\for_eco-depot\_depot_certs_b2_manifest.json"
DIGEST_STATE_PATH = r"C:\for_eco-depot\_depot_certs_digest_last.txt"
DIGEST_AFTER_HOUR = 16
DEFAULT_API_BASE = "https://depot.eco-oil.co.il"

TANK_RE = re.compile(r"[A-Z]{4}\s?\d{6,7}")
# רואדטנקרים: המזהה בתעודה הוא לוחית הרישוי (למשל 774-30-402)
PLATE_RE = re.compile(r"\d{2,3}-\d{2,3}-\d{2,3}")
YEAR_RE = re.compile(r"^20\d\d$")
MONTH_RE = re.compile(r"^\d{1,2}$")


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


def find_tank(parts, fname):
    """המזהה — איזוטנק (ISO) או לוחית רואדטנקר — מהתיקייה או משם הקובץ."""
    cands = list(parts[::-1]) + [os.path.splitext(fname)[0]]
    for cand in cands:
        m = TANK_RE.search(str(cand).upper())
        if m:
            return m.group(0).replace(" ", "")
    for cand in cands:
        m = PLATE_RE.search(str(cand))
        if m:
            return m.group(0)
    return ""


def scan():
    """כל קבצי ה-PDF משנת MIN_YEAR ואילך, לפי מקטע-שנה בנתיב."""
    items = []
    for top in sorted(os.listdir(SRC)):
        top_path = os.path.join(SRC, top)
        if not os.path.isdir(top_path):
            continue
        if top in EXCLUDE_TOP or top.startswith("~"):
            continue
        for root, dirs, files in os.walk(top_path):
            rel_parts = os.path.relpath(root, top_path).split(os.sep)
            year = month = None
            for i, seg in enumerate(rel_parts):
                if YEAR_RE.match(seg):
                    year = int(seg)
                    if i + 1 < len(rel_parts) and MONTH_RE.match(rel_parts[i + 1]):
                        mo = int(rel_parts[i + 1])
                        if 1 <= mo <= 12:
                            month = mo
                    break
            if year is None or year < MIN_YEAR:
                continue
            for fname in files:
                if not fname.lower().endswith(".pdf"):
                    continue
                p = os.path.join(root, fname)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                rel = os.path.relpath(p, SRC).replace("\\", "/")
                items.append({
                    "path": p,
                    "b2_key": KEY_PREFIX + rel,
                    "folder": top,
                    "tank": find_tank(rel_parts, fname),
                    "year": year,
                    "month": month,
                    "file_name": fname,
                    "file_date": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                    "size": st.st_size,
                })
    return items


def upload(items, manifest, dry_run=False, limit=None):
    todo = [it for it in items if manifest.get(it["b2_key"]) != it["size"]]
    if limit:
        todo = todo[:limit]
    print(f"PDFs found: {len(items)} | to upload: {len(todo)}")
    if dry_run or not todo:
        return 0, 0
    s3 = b2_client()
    bucket = os.environ["B2_BUCKET_CERTS"]
    up, failed = 0, 0
    for i, it in enumerate(todo, 1):
        try:
            with open(it["path"], "rb") as f:
                s3.put_object(Bucket=bucket, Key=it["b2_key"], Body=f,
                              ContentType="application/pdf")
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


def push(items, manifest, api_base, token, seed=False, dry_run=False):
    payload = [{k: it[k] for k in
                ("b2_key", "folder", "tank", "year", "month",
                 "file_name", "file_date", "size")}
               for it in items if it["b2_key"] in manifest]
    print(f"records to push: {len(payload)} (confirmed in B2)")
    if dry_run:
        return
    headers = {"Authorization": f"Bearer {token}"}
    added = updated = 0
    for i in range(0, len(payload), 500):
        chunk = payload[i:i + 500]
        r = requests.post(f"{api_base}/depot/portal/bridge/certs",
                          json={"items": chunk, "seed_notified": seed},
                          headers=headers, timeout=120)
        r.raise_for_status()
        d = r.json()
        added += d.get("added", 0)
        updated += d.get("updated", 0)
    print(f"push done: {added} added, {updated} updated")


def maybe_digest(api_base, token, force=False, dry_run=False):
    """הסיכום היומי — פעם ביום, מהסבב הראשון אחרי DIGEST_AFTER_HOUR."""
    today = datetime.now().strftime("%Y-%m-%d")
    if not force:
        if datetime.now().hour < DIGEST_AFTER_HOUR:
            return
        if os.path.exists(DIGEST_STATE_PATH):
            with open(DIGEST_STATE_PATH, encoding="utf-8") as f:
                if f.read().strip() == today:
                    return
    r = requests.post(f"{api_base}/depot/portal/bridge/certs-digest",
                      json={"dry_run": dry_run},
                      headers={"Authorization": f"Bearer {token}"}, timeout=120)
    r.raise_for_status()
    d = r.json()
    print(f"digest: {json.dumps(d, ensure_ascii=False)}")
    if not dry_run:
        os.makedirs(os.path.dirname(DIGEST_STATE_PATH), exist_ok=True)
        with open(DIGEST_STATE_PATH, "w", encoding="utf-8") as f:
            f.write(today)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true",
                    help="הטענה ראשונית: תעודות חדשות מוחתמות כ'כבר-נכללו-בסיכום'")
    ap.add_argument("--digest-now", action="store_true")
    ap.add_argument("--no-digest", action="store_true")
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
    push(items, manifest, args.api_base, token,
         seed=args.seed, dry_run=args.dry_run)
    if not args.no_digest:
        maybe_digest(args.api_base, token, force=args.digest_now,
                     dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
