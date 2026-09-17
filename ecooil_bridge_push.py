# -*- coding: utf-8 -*-
"""
Eco-Oil bridge — PUSH stage: office → cloud.

Runs AFTER ecooil_bridge_sync.py (Excel → local DB) and ecooil_pdf_matcher.py
(fills pdf_path). Two jobs:
  1. Upload matched certificate PDFs to the B2 bucket (skip what's already
     there via a local manifest; re-upload on size change; NEVER deletes from
     B2 — the cloud copy is also the backup, the Gadot-2025 lesson).
  2. Push the events to the portal's secure bridge API — like a backup
     (Limor 17/09/2026): every row carries a natural key (ecooil_natkey.py),
     the office remembers what it pushed last time (_ecooil_push_state.json),
     and normally sends ONLY the rows that were added / changed / removed
     since (/sync-delta). The cloud updates rows in place, so a row's id never
     changes between runs. A full snapshot (/sync) goes out on the first run,
     on --full, or whenever the cloud refuses the delta (409) — and even then
     the cloud reconciles in place rather than wiping.
     An event gets pdf_key only if its PDF is confirmed uploaded, so the
     portal never offers a download it cannot serve.

Usage:
  python ecooil_bridge_push.py                 # full run: files + data (delta)
  python ecooil_bridge_push.py --files-only [--limit N]
  python ecooil_bridge_push.py --data-only
  python ecooil_bridge_push.py --full          # force a full snapshot
  python ecooil_bridge_push.py --dry-run       # show the plan, send nothing
  python ecooil_bridge_push.py --api-base http://127.0.0.1:5000   # local test
"""
import argparse
import hashlib
import json
import os
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(r"C:\eco_oil_platform_git\.env")

# Safety: the local DB read must never touch production Postgres.
os.environ.pop("DATABASE_URL", None)

import requests

Z_BASE = r"Z:\Eco_General"
KEY_PREFIX = "certs/"
MANIFEST_PATH = r"C:\eco_oil_portal\_b2_uploaded_manifest.json"
# Memory of the previous push (natural key → row fingerprint), per target.
STATE_PATH = os.environ.get("ECOOIL_PUSH_STATE") or r"C:\eco_oil_portal\_ecooil_push_state.json"
DEFAULT_API_BASE = "https://portal.eco-oil.co.il"


def pdf_key_for(pdf_path):
    """Deterministic B2 key mirroring the office filing tree under Z:\\Eco_General."""
    p = os.path.normpath(pdf_path)
    base = os.path.normpath(Z_BASE)
    if p.lower().startswith(base.lower() + os.sep):
        rel = p[len(base) + 1:]
    else:
        rel = p.replace(":", "")
    return KEY_PREFIX + rel.replace("\\", "/")


def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(m):
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
        config=Config(signature_version="s3v4", retries={"max_attempts": 5}),
    )


def collect_events():
    """Read the full snapshot from the local DB into plain dicts (memory-safe:
    finish reading before any network work so a local-API test can't bite itself)."""
    from src.app import create_app
    from src.app.db import EcoOilUnloadEvent
    app = create_app()
    events = []
    with app.app_context():
        for r in EcoOilUnloadEvent.query.order_by(EcoOilUnloadEvent.id).all():
            events.append({
                "year": r.year, "month": r.month, "serial": r.serial,
                "code": r.code,
                "event_date": r.event_date.isoformat() if r.event_date else None,
                "vehicle": r.vehicle, "transporter": r.transporter,
                "customer": r.customer, "address": r.address,
                "billed_to": r.billed_to, "stream": r.stream,
                "stream_norm": r.stream_norm,
                "doc_status": r.doc_status,
                "weight_in": r.weight_in, "weight_out": r.weight_out,
                "weight_net": r.weight_net, "declared_tons": r.declared_tons,
                "package_type": r.package_type, "package_count": r.package_count,
                "exit_time": r.exit_time, "notes": r.notes,
                "pdf_path": r.pdf_path,
                "manifest_path": r.manifest_path,
                "source_sheet": r.source_sheet, "source_row": r.source_row,
            })
    return events


def upload_pdfs(events, manifest, limit=None, dry_run=False):
    """Upload every matched PDF that isn't in the cloud yet (or changed size)."""
    s3 = None if dry_run else b2_client()
    bucket = os.environ["B2_BUCKET_CERTS"]
    todo, missing_on_disk = [], 0
    seen = set()
    for ev in events:
        # certificates + signed טופס מלווה scans go through the same pipe
        for field in ("pdf_path", "manifest_path"):
            p = ev.get(field)
            if not p or p in seen:
                continue
            seen.add(p)
            if not os.path.exists(p):
                missing_on_disk += 1
                continue
            key = pdf_key_for(p)
            size = os.path.getsize(p)
            if manifest.get(key) == size:
                continue
            todo.append((p, key, size))

    if limit:
        todo = todo[:limit]
    print(f"PDFs to upload: {len(todo)} (missing on disk: {missing_on_disk})")

    uploaded, failed = 0, 0
    for i, (p, key, size) in enumerate(todo, 1):
        if dry_run:
            print(f"  DRY {key}")
            continue
        try:
            with open(p, "rb") as f:
                s3.put_object(Bucket=bucket, Key=key, Body=f,
                              ContentType="application/pdf")
            manifest[key] = size
            uploaded += 1
            if uploaded % 25 == 0:
                save_manifest(manifest)
            if uploaded % 200 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} uploaded…")
        except Exception as e:
            failed += 1
            print(f"  FAILED {key}: {type(e).__name__}: {e}")
            if failed >= 20:
                print("  too many failures — stopping upload phase")
                break
    if not dry_run:
        save_manifest(manifest)
    print(f"upload done: {uploaded} uploaded, {failed} failed")
    return uploaded, failed


def build_payload(events, manifest):
    """Rows as the cloud should hold them: pdf_key / manifest_key attached only
    when the file is confirmed in the cloud, plus the natural key of each row."""
    from src.app.ecooil_natkey import assign_nat_keys
    payload = []
    with_key = with_manifest = 0
    for ev in events:
        item = dict(ev)
        p = item.get("pdf_path")
        if p:
            key = pdf_key_for(p)
            if key in manifest:
                item["pdf_key"] = key
                with_key += 1
        mp = item.get("manifest_path")
        if mp:
            mkey = pdf_key_for(mp)
            if mkey in manifest:
                item["manifest_key"] = mkey
                with_manifest += 1
        payload.append(item)
    dups = assign_nat_keys(payload)
    return payload, with_key, with_manifest, dups


def item_digest(item):
    """Fingerprint of everything the cloud stores for a row — any difference
    (a note, a weight, a newly matched PDF, a publish flag) changes it."""
    body = {k: v for k, v in item.items() if k != "nat_key"}
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                   default=str).encode("utf-8")).hexdigest()


def load_state(api_base):
    """What we pushed last time to THIS target (a local test server must not
    inherit the production memory). None = no usable memory → full snapshot."""
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception as e:
        print(f"state file unreadable ({type(e).__name__}) — full snapshot")
        return None
    if st.get("api_base") != api_base or not isinstance(st.get("keys"), dict):
        return None
    return st


def save_state(api_base, keys):
    st = {"api_base": api_base, "saved_at": datetime.now().isoformat(timespec="seconds"),
          "total": len(keys), "keys": keys}
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def _post(api_base, token, path, body):
    return requests.post(f"{api_base}/bridge/ecooil/{path}", json=body,
                         headers={"Authorization": f"Bearer {token}"}, timeout=300)


def push_data(events, manifest, api_base, dry_run=False, full=False):
    """Send the rows to the cloud: normally only the differences since the
    previous push (like a backup), a full snapshot when there is no memory of
    a previous push, on --full, or when the cloud refuses the delta."""
    token = os.environ.get("ECOOIL_BRIDGE_TOKEN")
    if not token:
        print("ERROR: ECOOIL_BRIDGE_TOKEN missing from .env")
        return False
    payload, with_key, with_manifest, dups = build_payload(events, manifest)
    print(f"events: {len(payload)} ({with_key} with a cloud PDF, {with_manifest} with a cloud manifest"
          + (f", {dups} identical-identity rows got #n suffixes" if dups else "") + ")")
    current = {it["nat_key"]: item_digest(it) for it in payload}

    state = None if full else load_state(api_base)
    if state is None:
        print("push mode: FULL snapshot" + (" (--full)" if full else " (no memory of a previous push)"))
        plan = None
    else:
        prev = state["keys"]
        upsert = [it for it in payload if prev.get(it["nat_key"]) != current[it["nat_key"]]]
        added = sum(1 for it in upsert if it["nat_key"] not in prev)
        delete = [k for k in prev if k not in current]
        plan = {"upsert": upsert, "delete": delete, "expect_total": len(payload)}
        print(f"push mode: delta since {state.get('saved_at')} — "
              f"{added} added, {len(upsert) - added} changed, {len(delete)} removed")
    if dry_run:
        print("DRY RUN — not pushing")
        return True

    if plan is not None:
        resp = _post(api_base, token, "sync-delta", plan)
        print("push (delta):", resp.status_code, resp.text[:300])
        if resp.status_code == 409:
            print("cloud asked for a full snapshot — sending it")
            plan = None
        elif resp.status_code in (404, 405):
            # cloud not yet deployed with delta support — the old /sync still works
            print("cloud has no delta endpoint yet — sending a full snapshot")
            plan = None
        elif resp.status_code != 200:
            return False
    if plan is None:
        resp = _post(api_base, token, "sync", {"events": payload})
        print("push (full):", resp.status_code, resp.text[:300])
        if resp.status_code != 200:
            return False
    save_state(api_base, current)
    st = requests.get(f"{api_base}/bridge/ecooil/status",
                      headers={"Authorization": f"Bearer {token}"}, timeout=60)
    print("status:", st.status_code, st.text[:300])
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files-only", action="store_true")
    ap.add_argument("--data-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--full", action="store_true",
                    help="send the whole snapshot instead of the differences")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--api-base", default=os.environ.get("PORTAL_API_BASE", DEFAULT_API_BASE))
    args = ap.parse_args()

    events = collect_events()
    print(f"local snapshot: {len(events)} events")
    manifest = load_manifest()

    ok = True
    if not args.data_only:
        upload_pdfs(events, manifest, limit=args.limit, dry_run=args.dry_run)
        manifest = load_manifest() if not args.dry_run else manifest
    if not args.files_only:
        ok = push_data(events, manifest, args.api_base.rstrip("/"),
                       dry_run=args.dry_run, full=args.full)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
