# -*- coding: utf-8 -*-
"""
Eco-Oil MANIFEST matcher — links unload events to their signed טופס מלווה scan.

Sister of ecooil_pdf_matcher.py (same trees, same normalization/scoring), with
two deliberate differences:
1. Indexes ONLY מלווה files (the cert matcher skips them).
2. A manifest is NOT single-use: one truck's signed manifest may cover several
   unload rows of the same day/stream/owner (multiple pickups on one route),
   so records are never marked "used".

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
               "אתר", "לייצוא", "ללא", "אישור", "MOE"}

YEAR_NAMES = {str(y) for y in YEARS}
SKIP_PARTS = {"אישורים", "ישן"}

index = defaultdict(list)
n_files = n_unparsed = 0

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
    return {"d": d, "mo": mo, "y": y, "streams": streams, "name": name}

def scan_owner(base, owner):
    global n_files, n_unparsed
    for dirpath, dirnames, filenames in os.walk(base):
        rel = os.path.relpath(dirpath, base)
        parts = [] if rel == "." else rel.split(os.sep)
        year_on_path = next((int(p) for p in parts if p in YEAR_NAMES), None)
        subs = [p for p in parts
                if p not in YEAR_NAMES and p not in SKIP_PARTS
                and "מלווה" not in p
                and not re.fullmatch(r"\d{1,2}([\./]\d{2,4})?", p)]
        owner_full = " ".join([owner] + subs)
        for f in filenames:
            if not f.lower().endswith(".pdf") or "מלווה" not in f:
                continue
            p = parse_manifest_name(f, year_on_path)
            if p is None:
                n_unparsed += 1
                continue
            rec = {"path": os.path.join(dirpath, f), "owner": owner_full,
                   "name": p["name"], "streams": p["streams"]}
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
    per_stream = defaultdict(lambda: [0, 0])
    for ev in events:
        d = ev.event_date
        bs = base_stream(ev.stream)
        per_stream[ev.stream_norm or bs or "?"][0] += 1
        cands = index.get((d.year, d.month, d.day), [])
        best, best_score = None, 0.0
        for rec in cands:                      # NOTE: no 'used' flag — reuse allowed
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
            if score > best_score:
                best, best_score = rec, score
        if best:
            ev.manifest_path = best["path"]
            matched += 1
            per_stream[ev.stream_norm or bs or "?"][1] += 1
        else:
            ev.manifest_path = None
    db.session.commit()

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
