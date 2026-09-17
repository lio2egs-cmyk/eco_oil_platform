# -*- coding: utf-8 -*-
"""
Eco-Oil MANIFEST matcher — links unload events to their signed טופס מלווה scan.

Sister of ecooil_pdf_matcher.py (same trees, same normalization/scoring), with
two deliberate differences:
1. Indexes ONLY מלווה files (the cert matcher skips them).
2. A manifest IS single-use (Limor's rule 14/09/2026: a טופס מלווה is issued
   per pickup at one site — never shared across rows). When a site has several
   pickups on one day Limor numbers BOTH the certificate and its manifest with
   the same suffix (_2, _3); the row's certificate suffix therefore selects the
   manifest. No suffix = pickup #1. Only when exactly one candidate is left is
   it taken by elimination; otherwise the row stays without a manifest and is
   listed in the log instead of guessing.
   Refinement (Limor 14/09, the ISCAR 27/08 + Zohar-Dalia cases): ONE pickup can
   produce SEVERAL rows when inspection finds extra material (sludge/sand) and
   Yoav's rule adds a separate row — those rows share the pickup's single
   manifest. Hence "single-use" is per STREAM: a manifest may serve rows of
   different (raw) streams on that day/owner, never two rows of the same stream
   (those are two pickups and carry numbered files).

Manifests exist for hazardous streams; צמחי/סניטרי rows are not expected to
have one — the summary reports per-stream so those gaps read correctly.
Read-only on Z:; writes only manifest_path in the local dev DB.
"""
import os, io, re
from collections import defaultdict

os.environ.pop("DATABASE_URL", None)

from src.app import create_app
from src.app.db import db, EcoOilUnloadEvent

YEARS = (2024, 2025, 2026)
TREES = [r"Z:\Eco_General\מובילים", r"Z:\Eco_General\לקוחות"]
OUT_LOG = r"C:\eco_oil_platform_git\_ecooil_manifest_result.md"

# ---------- normalization (identical to the cert matcher) ----------
STOP = {"בעמ", "בע", "מ", "חברה", "לישראל", "ישראל", "והשקעות", "בעימ"}

def norm(s):
    if not s:
        return ""
    s = str(s)
    s = s.replace('"', "").replace("'", "").replace("_", " ").replace("-", " ")
    s = re.sub(r"בע\s*מ", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokens(s):
    return {t for t in norm(s).split() if t not in STOP}

def name_score(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    if inter:
        return len(inter) / min(len(ta), len(tb))
    na, nb = norm(a).replace(" ", ""), norm(b).replace(" ", "")
    if na and nb and (na in nb or nb in na):
        return 0.6
    return 0.0

from ecooil_pdf_matcher_aliases import LEGACY_BILLED_ALIASES  # shared aliases module

def billed_variants(billed):
    if not billed:
        return []
    return [billed] + LEGACY_BILLED_ALIASES.get(billed, [])

BASE_STREAMS = ["מי שטיפה", "מינרלי", "אמולסיה", "מזוט", "חומצה", "בסיס",
                "צמחי", "סניטרי", "רכז שפכים"]
FIX = {"מנרלי": "מינרלי", "מנירלי": "מינרלי", "רכז": "רכז שפכים"}
HAZ_STREAMS = {"מינרלי", "אמולסיה", "מזוט", "חומצה", "בסיס", "מי שטיפה"}

def base_stream(s):
    if not s:
        return None
    n = norm(s)
    n = FIX.get(n, n)
    for b in BASE_STREAMS:
        if n.startswith(norm(b)) or norm(b) in n:
            return b
    return n or None

# Loose filename parsing — manifests come in many hand-typed shapes
# (מלווה_זרם_ד.ח_לקוח / מלווה+נספח ג_... / לקוח מלווה ד.ח.שנה / date-first...).
# We extract: a date anywhere, every base-stream word anywhere, and the residual
# tokens as the customer/site name for scoring.
DATE_ANY = re.compile(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?")
NOISE_WORDS = {"מלווה", "טופס", "נספח", "ג", "משקל", "שקילה", "מעורב", "קוביות",
               "חביות", "פילטרים", "בוצה", "תשטיפי", "תשטיפיי", "תוסף", "בטון",
               "אתר", "לייצוא", "ללא", "אישור", "MOE", "תעודת", "משלוח"}

YEAR_NAMES = {str(y) for y in YEARS}
SKIP_PARTS = {"אישורים", "ישן"}

index = defaultdict(list)
n_files = n_unparsed = 0

# מספור-היום של לימור: _2/_3 בסוף שם הקובץ (לפני .pdf) = פינוי חוזר באותו יום.
# ספרה אחת בלבד — כדי לא לבלבל עם מספרים אחרים בשם ("בריכה צפונית_160").
SUFFIX_RE = re.compile(r"_(\d)\.pdf$", re.I)

def day_suffix(f):
    m = SUFFIX_RE.search(f)
    return int(m.group(1)) if m else 1

def parse_manifest_name(f, year_on_path):
    base = f[:-4]  # strip .pdf
    m = DATE_ANY.search(base)
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        return None
    y = None
    if m.group(3):
        yy = int(m.group(3))
        y = yy + 2000 if yy < 100 else yy
    if y is None:
        y = year_on_path
    if y is None or y not in YEARS:
        return None
    streams = {b for b in BASE_STREAMS if norm(b) in norm(base)}
    residue = base[:m.start()] + " " + base[m.end():]
    words = [w for w in re.split(r"[_\s+\-,.']+", residue)
             if w and not w.isdigit() and w not in NOISE_WORDS]
    for b in streams:
        for t in norm(b).split():
            words = [w for w in words if norm(w) != t]
    name = " ".join(words).strip() or None
    # Multi-site manifest (Limor 17/09/2026, Or Barkan "שוהם+חלמיש"): when the
    # residual name joins several SITE names with '+', Limor wrote one manifest
    # for one pickup that served several sites of the same customer — it may
    # serve one row per site (same stream). Stream combos ("אמולסיה+בוצה")
    # never reach here: stream words are removed from the residue first.
    site_parts = []
    if "+" in residue:
        for part in residue.split("+"):
            ws = [w for w in re.split(r"[_\s\-,.']+", part)
                  if w and not w.isdigit() and w not in NOISE_WORDS]
            for b in streams:
                for t in norm(b).split():
                    ws = [w for w in ws if norm(w) != t]
            if ws:
                site_parts.append(" ".join(ws))
    if len(site_parts) < 2:
        site_parts = []
    return {"d": d, "mo": mo, "y": y, "streams": streams, "name": name,
            "site_parts": site_parts}

def scan_owner(base, owner):
    global n_files, n_unparsed
    for dirpath, dirnames, filenames in os.walk(base):
        rel = os.path.relpath(dirpath, base)
        parts = [] if rel == "." else rel.split(os.sep)
        # חוק לימור 06/08/2026: תיקיית "איציק" חסומה לעולמים — לא נסרקת.
        if any(p.strip() == "איציק" for p in parts):
            continue
        year_on_path = next((int(p) for p in parts if p in YEAR_NAMES), None)
        subs = [p for p in parts
                if p not in YEAR_NAMES and p not in SKIP_PARTS
                and "מלווה" not in p
                and not re.fullmatch(r"\d{1,2}([\./]\d{2,4})?", p)]
        owner_full = " ".join([owner] + subs)
        # Rule (Limor 29/07): ANYTHING inside a customer's טופס-מלווה folder
        # counts as a manifest (e.g. תעודות משלוח in the one-off Gadot case),
        # regardless of the filename.
        in_manifest_folder = any("מלווה" in p for p in parts)
        for f in filenames:
            if not f.lower().endswith(".pdf"):
                continue
            if "מלווה" not in f and not in_manifest_folder:
                continue
            p = parse_manifest_name(f, year_on_path)
            if p is None:
                n_unparsed += 1
                continue
            rec = {"path": os.path.join(dirpath, f), "owner": owner_full,
                   "name": p["name"], "streams": p["streams"],
                   "site_parts": p["site_parts"], "served_sites": set(),
                   "suffix": day_suffix(f), "used_by": set()}
            index[(p["y"], p["mo"], p["d"])].append(rec)
            n_files += 1

for tree in TREES:
    for owner in os.listdir(tree):
        p = os.path.join(tree, owner)
        if os.path.isdir(p):
            scan_owner(p, owner)

app = create_app()
log = io.StringIO()
with app.app_context():
    events = (EcoOilUnloadEvent.query
              .filter(EcoOilUnloadEvent.event_date.isnot(None))
              .order_by(EcoOilUnloadEvent.event_date, EcoOilUnloadEvent.serial)
              .all())
    log.write(f"events: {len(events)} | indexed manifests: {n_files} | unparsed filenames: {n_unparsed}\n")

    def owner_score(rec, ev):
        s = 0.0
        for b in billed_variants(ev.billed_to):
            s = max(s, name_score(rec["owner"], b) * 1.2)
        if ev.customer:
            s = max(s, name_score(rec["owner"], ev.customer))
        if ev.transporter:
            s = max(s, name_score(rec["owner"], ev.transporter) * 0.9)
        return s

    matched = 0
    by_suffix = 0
    by_elimination = 0
    shared_same_pickup = 0   # one manifest → several rows of different streams (same pickup)
    shared_multi_site = 0    # one "site+site" manifest → one row per named site (17/09/2026)
    ambiguous = []   # (ev, [candidate paths]) — several manifests, none with the row's suffix
    per_stream = defaultdict(lambda: [0, 0])
    for ev in events:
        d = ev.event_date
        bs = base_stream(ev.stream)
        per_stream[ev.stream_norm or bs or "?"][0] += 1
        cands = index.get((d.year, d.month, d.day), [])
        ev_suffix = day_suffix(os.path.basename(ev.pdf_path)) if ev.pdf_path else 1
        skey = norm(ev.stream) or "?"          # raw stream: אמולסיה ≠ אמולסיה בוצה
        passing = []                           # (score, rec, site) — all gates passed, free for this stream
        for rec in cands:
            # Multi-site file (Limor 17/09/2026): one row per named site, per
            # stream. Anything else: single-use per stream (Limor 14/09/2026).
            site = None
            for part in rec["site_parts"]:
                if name_score(part, ev.customer or "") >= 0.5:
                    site = part
                    break
            if site is None:
                if skey in rec["used_by"]:
                    continue
            elif (skey, site) in rec["served_sites"]:
                continue
            # stream gate: a manifest naming streams matches only rows of those
            # streams; a stream-less filename may serve any stream that day
            if rec["streams"] and bs not in rec["streams"]:
                continue
            osc = owner_score(rec, ev)
            if osc < 0.5:
                continue
            if rec["name"]:
                nsc = max([name_score(rec["name"], ev.customer or "")] +
                          [name_score(rec["name"], b)
                           for b in billed_variants(ev.billed_to)])
                if nsc < 0.4 and osc < 1.0:
                    continue
            else:
                if osc < 0.7:
                    continue
                nsc = 0.0
            score = osc + nsc
            passing.append((score, rec, site))
        best = best_site = None
        if passing:
            same = [t for t in passing if t[1]["suffix"] == ev_suffix]
            if same:
                _, best, best_site = max(same, key=lambda t: t[0])
                by_suffix += 1
            elif len(passing) == 1:
                _, best, best_site = passing[0]
                by_elimination += 1
            else:
                ambiguous.append((ev, [r["path"] for _, r, _ in passing]))
        if best:
            if best_site is not None:
                if best["served_sites"]:
                    shared_multi_site += 1
                best["served_sites"].add((skey, best_site))
            else:
                if best["used_by"]:
                    shared_same_pickup += 1
                best["used_by"].add(skey)
            ev.manifest_path = best["path"]
            matched += 1
            per_stream[ev.stream_norm or bs or "?"][1] += 1
        else:
            ev.manifest_path = None
    db.session.commit()
    log.write(f"by suffix: {by_suffix} | by elimination (single candidate): {by_elimination} | shared by rows of different streams (same pickup): {shared_same_pickup} | shared by sites named in the file: {shared_multi_site} | ambiguous (left empty): {len(ambiguous)}\n")
    for ev, paths in ambiguous[:40]:
        log.write(f"  AMBIGUOUS {ev.event_date} {ev.billed_to} {ev.stream} code={ev.code}: {[os.path.basename(x) for x in paths]}\n")

    total = len(events)
    log.write(f"matched: {matched} ({matched*100//total}% of all rows)\n")
    haz_t = sum(v[0] for k, v in per_stream.items() if k in HAZ_STREAMS)
    haz_m = sum(v[1] for k, v in per_stream.items() if k in HAZ_STREAMS)
    if haz_t:
        log.write(f"hazardous streams only: {haz_m}/{haz_t} ({haz_m*100//haz_t}%)\n")
    log.write("per stream:\n")
    for k in sorted(per_stream, key=lambda k: -per_stream[k][0]):
        t, m = per_stream[k]
        log.write(f"  {k}: {m}/{t} ({m*100//t if t else 0}%)\n")

open(OUT_LOG, "w", encoding="utf-8").write(log.getvalue())
print(log.getvalue())
