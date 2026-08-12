# -*- coding: utf-8 -*-
r"""
Eco-Oil bridge — FILING FEED stage (לימור 12/08/2026).

Pulls from the portal cloud everything awaiting filing and drops it into the
customer's own folder under Z:\Eco_General\לקוחות :
  * Agreement documents (מסמך הסכמה) — rendered to PDF locally via headless
    Edge from the same layout as the portal page, filed as
    "הסכמה_מס <number>_<זרם> <גודל>_אתר <אתר>_<M.YY>.pdf".
  * Signed declaration scans (after final approval) — filed as
    "יצרן_<זרם> <גודל>_אתר <אתר>_<M.YY>.<ext>".

Folder resolution (per Limor 12/08):
  * customer dir under the clients root, matched by producer name / portal
    account name / billing-alias spellings (normalized: quotes, בע"מ, dashes);
  * inside it, the docs subdir — any folder named with "מסמכים" or a
    יצרן+הסכמה combination ("הצהרת יצרן+הסכמה", "יצרן+הסכמה", "מסמכים ואישורים").
  * Nothing is guessed and no folder is ever created — a miss is reported
    back as a note; the cloud emails Limor once and the item retries next cycle.
  * The bridge only ADDS files — archiving old ones stays manual (her call).

Usage:
  python ecooil_filing_feed.py                  # production (Z:, real API)
  python ecooil_filing_feed.py --api-base http://127.0.0.1:5000 --clients-root C:\...test
  python ecooil_filing_feed.py --dry-run        # pull + plan, no write, no ack
"""
import argparse
import html as html_mod
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(r"C:\eco_oil_platform_git\.env")

import requests

CLIENTS_ROOT = r"Z:\Eco_General\לקוחות"
DEFAULT_API_BASE = "https://portal.eco-oil.co.il"
STATIC_DIR = r"C:\eco_oil_platform_git\src\app\static"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TMP_DIR = r"C:\eco_oil_portal\_filing_tmp"

FAMILY_TITLE = {
    "mineral": "מינרלי/ אמולסיה/ מזוט",
    "emulsion": "מינרלי/ אמולסיה/ מזוט",
    "gasoil": "מינרלי/ אמולסיה/ מזוט",
    "acid": "חומצות/ בסיסים/ מי שטיפה",
    "base": "חומצות/ בסיסים/ מי שטיפה",
    "washwater": "חומצות/ בסיסים/ מי שטיפה",
}

MIME_EXT = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png",
            "image/heic": ".heic", "image/webp": ".webp"}


# ------------------------------------------------------------- folder matching
def _norm(s):
    s = str(s or "")
    for ch in ('"', "'", "׳", "״", "-", "_", ".", ",", "+", "(", ")"):
        s = s.replace(ch, " ")
    s = " ".join(s.split())
    for suffix in ("בע מ", "בעמ"):
        s = s.replace(" " + suffix, " ")
    return " ".join(s.split())


def find_customer_dir(root, candidates):
    """התיקייה של הלקוח — התאמה מנורמלת, בלי ניחושים.
    מחזיר (path, None) או (None, note)."""
    try:
        dirs = [d for d in os.listdir(root)
                if os.path.isdir(os.path.join(root, d))]
    except OSError as exc:
        return None, f"תיקיית הלקוחות לא נגישה ({exc})"
    by_norm = {}
    for d in dirs:
        by_norm.setdefault(_norm(d), []).append(d)

    for cand in candidates:
        hits = by_norm.get(_norm(cand))
        if hits and len(hits) == 1:
            return os.path.join(root, hits[0]), None
        if hits:
            return None, f"נמצאו כמה תיקיות עם השם '{cand}' — אחדי או שני שם"

    # התאמה חלקית — רק אם היא חד-משמעית (תיקייה אחת בלבד מתאימה)
    partial = set()
    for cand in candidates:
        n = _norm(cand)
        if len(n) < 4:
            continue
        for dn, names in by_norm.items():
            if n in dn or dn in n:
                partial.update(names)
    if len(partial) == 1:
        return os.path.join(root, partial.pop()), None
    if len(partial) > 1:
        names = ", ".join(sorted(partial)[:4])
        return None, f"כמה תיקיות מתאימות חלקית ({names}) — לא ניחשתי"
    return None, ("לא נמצאה תיקיית לקוח מתאימה תחת " + root +
                  " — צרי תיקייה (או הוסיפי צורת כתיב בפורטל)")


def find_docs_subdir(customer_dir):
    """תת-תיקיית התיוק: "מסמכים" / "מסמכים ואישורים" / "הצהרת יצרן+הסכמה" / "יצרן+הסכמה"."""
    try:
        subs = [d for d in os.listdir(customer_dir)
                if os.path.isdir(os.path.join(customer_dir, d))]
    except OSError as exc:
        return None, f"תיקיית הלקוח לא נגישה ({exc})"
    hits = [d for d in subs
            if "מסמכים" in d or ("יצרן" in d and "הסכמה" in d)]
    if len(hits) == 1:
        return os.path.join(customer_dir, hits[0]), None
    if len(hits) > 1:
        exact = [d for d in hits if _norm(d) == "מסמכים"]
        if len(exact) == 1:
            return os.path.join(customer_dir, exact[0]), None
        return None, f"כמה תת-תיקיות מתאימות ({', '.join(hits[:4])}) — לא ניחשתי"
    return None, (f"בתיקיית הלקוח ({os.path.basename(customer_dir)}) אין תת-תיקיית "
                  "מסמכים / הצהרת יצרן+הסכמה — צרי אותה")


# ------------------------------------------------------------- file naming
def _clean(s, maxlen=45):
    s = re.sub(r'[\\/:*?"<>|\r\n]+', " ", str(s or ""))
    s = " ".join(s.split())
    return s[:maxlen].strip()


def _myy(iso):
    if not iso:
        return datetime.now().strftime("%-m.%y") if os.name != "nt" else datetime.now().strftime("%m.%y").lstrip("0")
    dt = datetime.fromisoformat(iso)
    return f"{dt.month}.{dt:%y}"


def build_filename(prefix, row, date_iso, ext):
    parts = [prefix]
    stream_size = " ".join(x for x in (_clean(row.get("material_name"), 30),
                                       _clean(row.get("producer_size"), 10)) if x)
    if stream_size:
        parts.append(stream_size)
    fac = _clean(row.get("production_facility"), 40)
    if fac:
        parts.append("אתר " + fac)
    parts.append(_myy(date_iso))
    return "_".join(parts) + ext


def unique_path(folder, filename):
    base, ext = os.path.splitext(filename)
    path = os.path.join(folder, filename)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


# ------------------------------------------------------------- PDF rendering
def agreement_html(row):
    """אותה נראות כמו agreement_doc.html בפורטל — גרסה עצמאית לקובץ מקומי."""
    def esc(v):
        v = "" if v is None else str(v)
        return html_mod.escape(v) if v else "—"

    st = STATIC_DIR.replace("\\", "/")
    day = ""
    if row.get("issued_at"):
        day = datetime.fromisoformat(row["issued_at"]).strftime("%d/%m/%Y")
    fam = FAMILY_TITLE.get(row.get("material_classification"),
                           "חומצות/ בסיסים/ מי שטיפה")
    cells = [row.get(k) for k in (
        "producer_name", "material_name", "waste_stream_number",
        "production_facility", "y_code", "annex8", "h_code", "un_group",
        "catalog", "treatment_type", "r_code", "d_code", "quantity",
        "packaging", "characteristic", "pollutant_type", "concentration_range")]
    tds = "".join(f"<td>{esc(c)}</td>" for c in cells)
    ths = ("<th>יצרן הפסולת</th><th>שם זרם הפסולת</th><th>מספר הפסולת</th>"
           "<th>מתקן הייצור ממנו נוצרה הפסולת</th>"
           "<th>קוד Y (נספחים I ו-II לאמנת באזל) – קוד ותיאור הקוד</th>"
           "<th>סוג הפסולת (נספח VIII לאמנת באזל) – סיווג ותיאור הסיווג</th>"
           "<th>קוד סיכון (H) לאמנת באזל</th><th>קבוצת סיכון ע\"פ האו\"ם</th>"
           "<th>סיווג ע\"פ קטלוג הפסולות האירופאי (סיווג ופירוט)</th><th>מתקן / סוג טיפול</th>"
           "<th>קוד פעולות השבה (R) לאמנת באזל</th><th>קוד טיפול בפסולת (D) לאמנת באזל</th>"
           "<th>כמות שנתית (טון)</th><th>סוג האריזה</th><th>מאפיין עיקרי של הפסולות</th>"
           "<th>סוג מזהם</th><th>טווח הריכוזים בפסולת (מינימום - מקסימום)</th>")
    return f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<style>
  @page {{ size: A4 landscape; margin: 7mm; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:Arial,'Segoe UI',sans-serif;color:#111}}
  .sheet{{width:100%;min-height:735px;padding:4px 6px 80px;display:flex;flex-direction:column;position:relative}}
  .hdr{{display:flex;align-items:center;justify-content:space-between;border-bottom:1.5px solid #2F5F59;padding-bottom:6px}}
  .hdr img.logo{{height:86px}} .hdr img.min{{height:80px}}
  .hdr .ttl{{text-align:center;flex:1}}
  .hdr .ttl h1{{font-size:18px;color:#1c3f3a}}
  .hdr .ttl .num{{font-size:12px;color:#1c3f3a;font-weight:600;margin-top:2px}}
  .hdr .ttl .dt{{font-size:11px;color:#555;margin-top:2px}}
  .hdr .ttl .fam{{font-size:10.5px;color:#555;margin-top:1px}}
  .addr{{font-size:11px;margin:9px 2px 6px;padding:7px 10px;background:#f3f6f5;border-radius:5px;line-height:1.7}}
  .addr b{{color:#1c3f3a}}
  .clause{{font-size:10px;margin:6px 2px;line-height:1.5}}
  table{{width:100%;border-collapse:collapse;margin:13px 0;table-layout:fixed}}
  th,td{{border:0.7px solid #555;padding:2px 2px;font-size:6.7px;line-height:1.1;text-align:center;vertical-align:middle;word-wrap:break-word}}
  th{{background:#e8efed;color:#16352f;font-weight:600}}
  tbody td{{height:30px;font-size:7px}}
  .sigwrap{{display:flex;justify-content:space-between;align-items:flex-end;margin-top:auto;padding:14px 6px 0}}
  .sigright{{font-size:10.5px;line-height:1.6}}
  .sigright .cap{{color:#444;font-size:9.5px}}
  .sigimgs{{display:flex;align-items:flex-end;gap:26px;padding-left:30px}}
  .sigimgs .box{{text-align:center}}
  .sigimgs img.sig{{height:58px}} .sigimgs img.stamp{{height:52px}}
  .sigimgs .lbl{{font-size:9px;color:#444;border-top:1px solid #000;margin-top:3px;padding-top:2px}}
  .ftr{{position:absolute;left:0;right:0;bottom:0;text-align:center}}.ftr img{{width:773px;height:60px}}
</style></head><body>
<div class="sheet">
  <div class="hdr">
    <img class="logo" src="file:///{st}/decl_logo.png">
    <div class="ttl">
      <h1>מסמך הסכמה לקליטת הפסולת</h1>
      <div class="num">מסמך מס' {esc(row.get('number'))}</div>
      <div class="dt">תאריך: {day}</div>
      <div class="fam">{esc(fam)}</div>
    </div>
    <img class="min" src="file:///{st}/decl_ministry.png">
  </div>
  <div class="addr">
    <div><b>לכבוד:</b> {esc(row.get('producer_name'))}</div>
    <div><b>בעל היתר הרעלים של יצרן הפסולת המסוכנת:</b> {esc(row.get('ceo_name'))}</div>
    <div><b>מספר ח.פ. של יצרן הפסולת / ת.ז.:</b> {esc(row.get('business_id'))}
     &nbsp;&nbsp;<b>מספר היתר הרעלים:</b> {esc(row.get('permit_number'))}</div>
    <div><b>כתובת העסק / מפעל:</b> {esc(row.get('address'))}</div>
  </div>
  <div class="clause">הריני לאשר כי הפסולת המסוכנת המתוארת בבקשתך, כמפורט להלן, ניתנת לטיפול במתקן אקו אויל חץ וירומטל בע"מ, בהתאם לתנאים שנקבעו למתקן:</div>
  <table><thead><tr>{ths}</tr></thead><tbody><tr>{tds}</tr></tbody></table>
  <div class="clause">הפסולת המסוכנת תתקבל לטיפול רק בליווי אישור מנהל וטופס מלווה לפסולת מסוכנת.</div>
  <div class="clause">במידה ויחול שינוי במאפייני הפסולת המסוכנת, לרבות בהרכב הפסולת המסוכנת, על יצרן הפסולת המסוכנת לשנות את טופס הצהרת יצרן בהתאם לשינוי.</div>
  <div class="clause">במידה ויחול שינוי ביכולת הטיפול בפסולת המסוכנת, המסמך ישונה בהתאם לרבות סוג הטיפול ומתקן הטיפול.</div>
  <div class="sigwrap">
    <div class="sigright">בכבוד רב,<br><b>יואב טואג — מנכ"ל</b><br>
      <span class="cap">מתקן הקליטה: אקו אויל חץ וירומטל בע"מ · ח.פ. 513216556</span></div>
    <div class="sigimgs">
      <div class="box"><img class="sig" src="file:///{st}/decl_sig_yoav.png"><div class="lbl">חתימת מנכ"ל</div></div>
      <div class="box"><img class="stamp" src="file:///{st}/decl_stamp.png"><div class="lbl">חותמת החברה</div></div>
    </div>
  </div>
  <div class="ftr"><img src="file:///{st}/decl_footer.png"></div>
</div></body></html>"""


def render_pdf(html_text, out_pdf):
    """HTML → PDF דרך Edge חסר-ראש (הדפדפן שכבר מותקן על המחשב)."""
    os.makedirs(TMP_DIR, exist_ok=True)
    html_path = os.path.join(TMP_DIR, "agreement_tmp.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    profile = os.path.join(TMP_DIR, "edge_profile")
    r = subprocess.run(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         f"--user-data-dir={profile}", "--no-pdf-header-footer",
         f"--print-to-pdf={out_pdf}", "file:///" + html_path.replace("\\", "/")],
        capture_output=True, timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if not os.path.exists(out_pdf) or os.path.getsize(out_pdf) < 5000:
        raise RuntimeError(f"Edge PDF failed (rc={r.returncode}, "
                           f"stderr={r.stderr.decode(errors='replace')[-200:]})")


# ------------------------------------------------------------- main work
def resolve_target(root, row):
    cdir, note = find_customer_dir(root, row.get("folder_candidates") or [])
    if note:
        return None, note
    sub, note = find_docs_subdir(cdir)
    if note:
        return None, note
    return sub, None


def file_into(folder, src_path, filename):
    """העתקה בטוחה: קודם לקובץ זמני בתיקיית היעד, ואז שינוי שם."""
    target = unique_path(folder, filename)
    tmp = target + ".part"
    shutil.copy2(src_path, tmp)
    if os.path.getsize(tmp) != os.path.getsize(src_path):
        os.remove(tmp)
        raise RuntimeError("copy size mismatch")
    os.replace(tmp, target)
    return target


def run(api_base, clients_root, dry_run=False):
    token = os.environ.get("ECOOIL_BRIDGE_TOKEN")
    if not token:
        print("ERROR: ECOOIL_BRIDGE_TOKEN missing from .env")
        return 1
    headers = {"Authorization": "Bearer " + token}

    r = requests.get(api_base + "/bridge/ecooil/filing-feed", headers=headers, timeout=60)
    if r.status_code != 200:
        print(f"ERROR: filing-feed pull failed {r.status_code}: {r.text[:200]}")
        return 1
    data = r.json()
    agreements = data.get("agreements") or []
    scans = data.get("scans") or []
    if not agreements and not scans:
        print("filing: nothing pending")
        return 0
    print(f"filing: {len(agreements)} agreement(s), {len(scans)} scan(s) pending")

    ag_results, scan_results = [], []

    for row in agreements:
        num = row.get("number")
        try:
            folder, note = resolve_target(clients_root, row)
            if note:
                print(f"  agreement #{num}: MISS — {note}")
                ag_results.append({"id": row["agreement_id"], "done": False, "note": note})
                continue
            filename = build_filename(f"הסכמה_מס {num}", row, row.get("issued_at"), ".pdf")
            if dry_run:
                print(f"  agreement #{num}: would file '{filename}' → {folder}")
                continue
            os.makedirs(TMP_DIR, exist_ok=True)
            tmp_pdf = os.path.join(TMP_DIR, f"agreement_{num}.pdf")
            render_pdf(agreement_html(row), tmp_pdf)
            target = file_into(folder, tmp_pdf, filename)
            os.remove(tmp_pdf)
            print(f"  agreement #{num}: filed → {target}")
            ag_results.append({"id": row["agreement_id"], "done": True, "note": None})
        except Exception as exc:  # noqa: BLE001
            print(f"  agreement #{num}: ERROR — {exc}")
            ag_results.append({"id": row["agreement_id"], "done": False,
                               "note": f"שגיאת תיוק: {exc}"})

    for row in scans:
        did = row.get("declaration_id")
        try:
            folder, note = resolve_target(clients_root, row)
            if note:
                print(f"  scan decl#{did}: MISS — {note}")
                scan_results.append({"id": did, "done": False, "note": note})
                continue
            ext = MIME_EXT.get((row.get("scan_mime") or "").lower())
            if not ext:
                ext = os.path.splitext(row.get("scan_filename") or "")[1] or ".pdf"
            filename = build_filename("יצרן", row, row.get("approved_at"), ext)
            if dry_run:
                print(f"  scan decl#{did}: would file '{filename}' → {folder}")
                continue
            rs = requests.get(f"{api_base}/bridge/ecooil/filing-feed/scan/{did}",
                              headers=headers, timeout=120)
            if rs.status_code != 200:
                raise RuntimeError(f"scan download failed {rs.status_code}")
            os.makedirs(TMP_DIR, exist_ok=True)
            tmp_f = os.path.join(TMP_DIR, f"scan_{did}{ext}")
            with open(tmp_f, "wb") as f:
                f.write(rs.content)
            target = file_into(folder, tmp_f, filename)
            os.remove(tmp_f)
            print(f"  scan decl#{did}: filed → {target}")
            scan_results.append({"id": did, "done": True, "note": None})
        except Exception as exc:  # noqa: BLE001
            print(f"  scan decl#{did}: ERROR — {exc}")
            scan_results.append({"id": did, "done": False, "note": f"שגיאת תיוק: {exc}"})

    if dry_run:
        print("dry-run: no ack")
        return 0
    if ag_results or scan_results:
        ra = requests.post(api_base + "/bridge/ecooil/filing-feed/ack", headers=headers,
                           json={"agreements": ag_results, "scans": scan_results}, timeout=60)
        print(f"ack: {ra.status_code} {ra.text[:160]}")
        if ra.status_code != 200:
            return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--clients-root", default=CLIENTS_ROOT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return run(args.api_base, args.clients_root, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
