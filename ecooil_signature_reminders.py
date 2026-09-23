# -*- coding: utf-8 -*-
"""
Signature reminders for producer declarations (Limor, 23/09/2026) — the
office-side trigger. Runs as a step of the hourly bridge; the cloud decides
who is due (7 days → reminder 1, +7 → reminder 2, +7 → one alert to the
office) and stamps each step, so hourly runs never send twice.

Usage:
  venv\\Scripts\\python.exe ecooil_signature_reminders.py            # send
  ... --dry-run                                                       # report only
"""
import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = os.environ.get("ECOOIL_API_BASE", "https://portal.eco-oil.co.il")


def _bridge_token():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("ECOOIL_BRIDGE_TOKEN="):
                return line.strip().split("=", 1)[1].strip().strip('"')
    raise SystemExit("ECOOIL_BRIDGE_TOKEN not found in .env")


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    req = urllib.request.Request(
        API_BASE + "/admin/declaration-signature-reminders",
        data=json.dumps({"dry_run": args.dry_run}).encode("utf-8"),
        headers={"Authorization": "Bearer " + _bridge_token(),
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"status: {e.code} {e.read()[:200]!r}")
        return 1
    actions = res.get("actions", [])
    if not actions:
        print("signature reminders: nothing due")
    for a in actions:
        print(f"  #{a['id']} {a.get('client')} / {a.get('producer')} — {a['step']} "
              f"({a['days']}d) → {a.get('to')}: {a.get('result', 'office alert')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
