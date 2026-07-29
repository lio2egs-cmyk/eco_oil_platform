# -*- coding: utf-8 -*-
"""
Eco-Oil bridge — the HOURLY production cycle, run by Windows Task Scheduler
on Limor's office PC (daily 07:00-18:00, every hour):

    1. ecooil_bridge_sync.py       — ריכוז workbooks → local snapshot DB (read-only)
    2. ecooil_pdf_matcher.py       — link rows to filed certificate PDFs
    3. ecooil_manifest_matcher.py  — link rows to signed טופס מלווה scans
    4. ecooil_bridge_push.py       — upload new PDFs+manifests to B2 + push snapshot

A lock file prevents overlapping runs; each run appends to a daily log under
C:\\eco_oil_portal\\bridge_logs\\.
"""
import os
import subprocess
import sys
from datetime import datetime

REPO = r"C:\eco_oil_platform_git"
PY = os.path.join(REPO, r"venv\Scripts\python.exe")
LOG_DIR = r"C:\eco_oil_portal\bridge_logs"
LOCK = os.path.join(LOG_DIR, "_run.lock")
LOCK_STALE_MINUTES = 50

STEPS = [
    ("reader", "ecooil_bridge_sync.py", []),
    ("matcher", "ecooil_pdf_matcher.py", []),
    ("manifest-matcher", "ecooil_manifest_matcher.py", []),
    ("push", "ecooil_bridge_push.py", []),
]


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d") + ".log")

    if os.path.exists(LOCK):
        age_min = (datetime.now().timestamp() - os.path.getmtime(LOCK)) / 60
        if age_min < LOCK_STALE_MINUTES:
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"\n[{datetime.now():%H:%M}] skipped — previous run still going ({age_min:.0f} min)\n")
            return 0
        os.remove(LOCK)

    open(LOCK, "w").close()
    ok = True
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"\n===== run {datetime.now():%Y-%m-%d %H:%M} =====\n")
            for name, script, extra in STEPS:
                started = datetime.now()
                r = subprocess.run(
                    [PY, os.path.join(REPO, script)] + extra,
                    cwd=REPO, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=45 * 60,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                took = (datetime.now() - started).seconds
                tail = "\n".join((r.stdout or "").strip().splitlines()[-6:])
                log.write(f"[{name}] exit {r.returncode} ({took}s)\n{tail}\n")
                if r.returncode != 0:
                    err_tail = "\n".join((r.stderr or "").strip().splitlines()[-10:])
                    log.write(f"[{name}] STDERR:\n{err_tail}\n")
                    ok = False
                    break
            log.write(f"===== {'OK' if ok else 'FAILED'} {datetime.now():%H:%M} =====\n")
    finally:
        if os.path.exists(LOCK):
            os.remove(LOCK)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
