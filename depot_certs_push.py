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

20/10/2026 (מקרה CXTU1088766, הורייזן — תעודת שטיפה הופקה למכל 'אחסנה בלבד' והפורטל
שלח עליה מייל ללקוח): שני שערים חדשים —
  * תעודת שטיפה של איזוטנק (העץ החדש, שם קובץ {מכל}_{מס' ביקור}.pdf) שהשורה שלה
    בקובץ החי בלי תאריך שטיפה (L) לא מועלית, לא נדחפת ולא נכנסת לסיכום היומי —
    נרשמת ביומן כ"תעודה בלי שטיפה — לבדיקת המשרד". הקובץ החי נקרא קריאה-בלבד
    (openpyxl); אם אי אפשר לקרוא אותו באותו סבב, תעודות חדשות ממתינות לסבב הבא.
  * --cancel <b2_key>: ביטול תעודה שכבר בפורטל — מחיקת הרשומה בענן (נקודת הגשר
    certs-cancel, נרשמת ביומן הניהול), מחיקת הקובץ מ-B2, הסרה מהמניפסט ורישום
    ברשימת המבוטלים כך שהסורק לא יעלה אותו שוב. את ה-PDF בתיקיית הנכס על הכונן
    המרכזי המשרד מזיז בעצמו — הסקריפט לא נוגע בקבצי פרודקשן.

שימוש:
  python depot_certs_push.py                    # ריצה מלאה
  python depot_certs_push.py --dry-run          # בלי העלאות, בלי דחיפה
  python depot_certs_push.py --seed             # הטענה ראשונית: מחתים notified
  python depot_certs_push.py --digest-now       # מפעיל את הסיכום מיד
  python depot_certs_push.py --api-base http://127.0.0.1:5000
  python depot_certs_push.py --cancel "depotcerts/לקוחות/.../X.pdf" [--reason "..."]
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
# העץ החדש (עידן הטאבלטים, מ-07/2026): הגשר מתייק תעודות ותמונות תחת
# לקוחות\{לקוח}\{שנה}\{חודש}\שטיפה\{טנק}. הבאג שתוקן 06/09/2026: הסורק
# ראה רק את העץ הישן — תעודות מיולי ואילך לא הגיעו לפורטל כלל.
SRC_NEW = r"O:\SHTIFOT\מערכת ניהול אקו דיפו\לקוחות"
# מהעץ החדש נקלטים רק 07/2026 ואילך — יוני ואחורה מגיעים מהעץ הישן,
# כך אין תעודה שנרשמת פעמיים משני העצים.
NEW_TREE_FROM = (2026, 7)
KEY_PREFIX = "depotcerts/"
KEY_PREFIX_NEW = KEY_PREFIX + "לקוחות/"
MIN_YEAR = 2026
# תיקיות ברמה העליונה שאינן תיקיית-לקוח
EXCLUDE_TOP = {"_כל התעודות שהופקו", "אקסלים 2025", "ספקים לא פעילים"}
MANIFEST_PATH = r"C:\for_eco-depot\_depot_certs_b2_manifest.json"
# תעודות שבוטלו (--cancel): הסורק מדלג עליהן לעולמים, גם אם ה-PDF עדיין בתיקייה
CANCELLED_PATH = r"C:\for_eco-depot\_depot_certs_cancelled.json"
# הקובץ החי — קריאה בלבד (openpyxl), רק גיליון האיזוטנקים, רק עמודות A-L
LIVE_PATH = r"O:\SHTIFOT\מערכת ניהול אקו דיפו\EcoDepot.xlsx"
ISO_SHEET = "רישום תנועות איזוטנקים"
# מס' ביקור בשם הקובץ ({מכל}_{מס' ביקור}.pdf — שם ייחודי פר-ביקור מ-05/08/2026);
# שני הכתיבים שבקובץ: ISO-2026-07-026 וההיסטורי ISO-TEMP-0164
VID_RE = re.compile(r"ISO-[A-Z0-9]+(?:-\d+)+", re.I)
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


def load_cancelled():
    if os.path.exists(CANCELLED_PATH):
        with open(CANCELLED_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cancelled(c):
    os.makedirs(os.path.dirname(CANCELLED_PATH), exist_ok=True)
    tmp = CANCELLED_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CANCELLED_PATH)


def _norm_tank(t):
    return str(t or "").strip().upper().replace(" ", "").replace("-", "")


def load_wash_dates(path=LIVE_PATH):
    """קריאה בלבד של גיליון האיזוטנקים: (מס' ביקור, מכל) → [(שורה, יש תאריך שטיפה?)].
    מס' ביקור אינו ייחודי (הגעה קבוצתית חולקת מספר) — לכן המפתח כולל את המכל.
    None = הקובץ לא נקרא הפעם (לא נגיש / באמצע שמירה) — תעודות חדשות ממתינות לסבב הבא."""
    try:
        import warnings
        import openpyxl
        warnings.filterwarnings("ignore")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[ISO_SHEET]
        out = {}
        for i, row in enumerate(ws.iter_rows(min_row=2, max_col=12, values_only=True), 2):
            vid, tank, wd = row[0], row[1], row[11]
            if not vid or not tank:
                continue
            washed = wd is not None and str(wd).strip() != ""
            out.setdefault((str(vid).strip().upper(), _norm_tank(tank)), []).append((i, washed))
        wb.close()
        return out
    except Exception as e:
        print(f"live workbook not readable ({type(e).__name__}: {e}) — "
              f"new iso certs are held until the next cycle")
        return None


def wash_verdict(it, wash_map):
    """'washed' / 'no-wash' (+שורות) / 'unknown' (אין איך לאמת) / 'n/a' (לא תעודת איזוטנק מהעץ החדש)."""
    if not it["b2_key"].startswith(KEY_PREFIX_NEW):
        return "n/a", []
    m = VID_RE.search(it["file_name"])
    if not m or not TANK_RE.search(it["tank"] or ""):
        return "n/a", []          # רואדטנקר / שם ישן בלי מס' ביקור — אין מה לאמת
    if wash_map is None:
        return "unknown", []
    rows = wash_map.get((m.group(0).upper(), _norm_tank(it["tank"])))
    if not rows:
        return "unknown", []      # הביקור לא נמצא בקובץ — לא חוסמים על סמך כלום
    if any(w for _, w in rows):
        return "washed", [r for r, _ in rows]
    return "no-wash", [r for r, _ in rows]


def wash_filter(items, wash_map, manifest):
    """מסנן תעודות שטיפה של איזוטנק שהשורה שלהן בקובץ החי בלי תאריך שטיפה.
    מחזיר (items_ok, held). כל תעודה מוחזקת נרשמת ביומן; מה שכבר בפורטל נרשם
    עם פקודת הביטול — ההחלטה של המשרד, לא של הסקריפט."""
    ok, held = [], []
    stat = {"washed": 0, "no-wash": 0, "unknown": 0, "n/a": 0}
    for it in items:
        verdict, rows = wash_verdict(it, wash_map)
        stat[verdict] += 1
        in_portal = it["b2_key"] in manifest
        if verdict == "no-wash":
            held.append(it)
            rel = it["b2_key"][len(KEY_PREFIX):]
            where = "שורה " + "/".join(str(r) for r in rows)
            if in_portal:
                print(f"  ⛔ תעודה בלי שטיפה — לבדיקת המשרד (כבר בפורטל): {rel} ({where}) — "
                      f"לביטול: depot_certs_push.py --cancel \"{it['b2_key']}\"")
            else:
                print(f"  ⛔ תעודה בלי שטיפה — לבדיקת המשרד: {rel} ({where}) — לא מועלית ולא נדחפת לפורטל")
        elif verdict == "unknown" and wash_map is None and not in_portal:
            held.append(it)       # הקובץ החי לא נקרא הפעם — תעודה חדשה ממתינה לסבב הבא
            print(f"  ⏸ ממתינה לאימות שטיפה (הקובץ החי לא נקרא): {it['b2_key'][len(KEY_PREFIX):]}")
        else:
            ok.append(it)
    print(f"wash check (live file {'read' if wash_map is not None else 'NOT read'}): "
          f"washed {stat['washed']} | no wash date {stat['no-wash']} | unverifiable {stat['unknown']} | "
          f"not applicable {stat['n/a']} | held {len(held)}")
    return ok, held


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


def scan_new():
    """העץ החדש: PDF-ים בתוך תת-תיקיית "שטיפה" בלבד (דוחות ברמת החודש,
    "דוחות יומיים", MSDS ותיקונים — בחוץ), מ-NEW_TREE_FROM ואילך."""
    items = []
    if not os.path.isdir(SRC_NEW):
        return items
    for top in sorted(os.listdir(SRC_NEW)):
        top_path = os.path.join(SRC_NEW, top)
        if not os.path.isdir(top_path) or top.startswith("~"):
            continue
        for root, dirs, files in os.walk(top_path):
            rel_parts = os.path.relpath(root, top_path).split(os.sep)
            if "שטיפה" not in rel_parts:
                continue
            year = month = None
            for i, seg in enumerate(rel_parts):
                if YEAR_RE.match(seg):
                    year = int(seg)
                    if i + 1 < len(rel_parts) and MONTH_RE.match(rel_parts[i + 1]):
                        mo = int(rel_parts[i + 1])
                        if 1 <= mo <= 12:
                            month = mo
                    break
            if year is None or month is None or (year, month) < NEW_TREE_FROM:
                continue
            for fname in files:
                if not fname.lower().endswith(".pdf"):
                    continue
                p = os.path.join(root, fname)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                rel = os.path.relpath(p, SRC_NEW).replace("\\", "/")
                items.append({
                    "path": p,
                    "b2_key": KEY_PREFIX_NEW + rel,
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


def cancel(b2_key, api_base, token, manifest, reason="", dry_run=False, s3=None):
    """ביטול תעודה שכבר הגיעה לפורטל (20/10/2026). הסדר: קודם הענן (אם הוא לא
    זמין — עוצרים לפני שנוגעים ב-B2, כך שהרצה חוזרת נקייה), אחר כך B2, המניפסט
    ורשימת המבוטלים. ה-PDF על הכונן המרכזי נשאר — המשרד מזיז אותו בעצמו."""
    key = (b2_key or "").strip()
    if not key.startswith(KEY_PREFIX):
        print(f"cancel: not a cert key (must start with {KEY_PREFIX}): {key}")
        return 1
    print(f"cancel: {key}" + (f" | reason: {reason}" if reason else "") + (" | DRY-RUN" if dry_run else ""))
    if dry_run:
        print("  would delete the portal record, the B2 object and the manifest entry; "
              "would add the key to the cancelled list")
        return 0
    r = requests.post(f"{api_base}/depot/portal/bridge/certs-cancel",
                      json={"b2_key": key, "reason": reason},
                      headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if r.status_code == 404:
        print("  portal: record not found (already removed) — continuing")
    else:
        r.raise_for_status()
        d = r.json()
        c = d.get("cert") or {}
        print(f"  portal: record deleted (id {c.get('id')}, folder {c.get('folder')}, "
              f"tank {c.get('tank')}, file {c.get('file_name')}) — logged in the admin log")
    s3 = s3 or b2_client()
    bucket = os.environ["B2_BUCKET_CERTS"]
    try:
        s3.delete_object(Bucket=bucket, Key=key)
        print("  B2: object deleted")
    except Exception as e:
        print(f"  B2: delete failed: {type(e).__name__}: {e}")
        return 1
    if manifest.pop(key, None) is not None:
        save_manifest(manifest)
        print("  manifest: entry removed")
    else:
        print("  manifest: entry was not there")
    cancelled = load_cancelled()
    cancelled[key] = {"at": datetime.now().isoformat(timespec="seconds"), "reason": reason}
    save_cancelled(cancelled)
    print("  cancelled list: added — the scanner will skip this file from now on")
    print("  reminder: the PDF in the asset folder on the central drive is NOT touched — "
          "the office moves it (backup first)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true",
                    help="הטענה ראשונית: תעודות חדשות מוחתמות כ'כבר-נכללו-בסיכום'")
    ap.add_argument("--digest-now", action="store_true")
    ap.add_argument("--no-digest", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--cancel", metavar="B2_KEY",
                    help="ביטול תעודה: מחיקה מהפורטל + מ-B2 + מהמניפסט, ורישום ברשימת המבוטלים")
    ap.add_argument("--reason", default="", help="סיבת הביטול (נרשמת ביומן הניהול בפורטל)")
    args = ap.parse_args()

    token = os.environ.get("ECOOIL_BRIDGE_TOKEN")
    if not token:
        print("missing ECOOIL_BRIDGE_TOKEN")
        return 1
    if args.cancel:
        return cancel(args.cancel, args.api_base, token, load_manifest(),
                      reason=args.reason, dry_run=args.dry_run)
    if not os.path.isdir(SRC):
        print(f"source folder unreachable: {SRC} — skipping this cycle")
        return 0

    items = scan() + scan_new()
    manifest = load_manifest()
    cancelled = load_cancelled()
    if cancelled:
        before = len(items)
        items = [it for it in items if it["b2_key"] not in cancelled]
        if before != len(items):
            print(f"cancelled certs skipped: {before - len(items)}")
    # 20/10/2026: תעודת שטיפה רק לשורה שנשטפה — הקובץ החי נקרא קריאה-בלבד
    items, _held = wash_filter(items, load_wash_dates(), manifest)
    upload(items, manifest, dry_run=args.dry_run, limit=args.limit)
    push(items, manifest, args.api_base, token,
         seed=args.seed, dry_run=args.dry_run)
    if not args.no_digest:
        maybe_digest(args.api_base, token, force=args.digest_now,
                     dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
