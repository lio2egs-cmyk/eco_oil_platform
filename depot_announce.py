# -*- coding: utf-8 -*-
"""הודעה לכל משתמשי פורטל הדיפו דרך הפורטל (לימור 06/10/2026).

רץ במחשב של לימור (אותו טוקן כמו הגשר השעתי, ECOOIL_BRIDGE_TOKEN מ-.env).
הנוסח = קובץ טקסט UTF-8 שלימור אישרה; שורה ראשונה = נושא, השאר = גוף.

    py depot_announce.py --text "C:\\eco_oil_portal\\announce_2026-10-06.txt"            ← תצוגה: נמענים לפי חברה, בלי שליחה
    py depot_announce.py --text "..." --send                                            ← שליחה אמיתית (רק אחרי "שלחי")
    py depot_announce.py --text "..." --send --only a@x.co.il,b@y.co.il                 ← לנמענים מסוימים בלבד (בדיקה)
"""
import argparse
import io
import json
import os
import sys
import urllib.request

DEFAULT_API_BASE = "https://depot.eco-oil.co.il"


def _load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, ".env")
    if os.path.exists(p):
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True, help="קובץ UTF-8: שורה ראשונה נושא, אחריה הגוף")
    ap.add_argument("--send", action="store_true", help="שליחה אמיתית (ברירת המחדל: תצוגה בלבד)")
    ap.add_argument("--only", default="", help="כתובות מופרדות בפסיק — לשלוח רק להן")
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    args = ap.parse_args()
    _load_env()
    token = os.environ.get("ECOOIL_BRIDGE_TOKEN")
    if not token:
        print("ERROR: ECOOIL_BRIDGE_TOKEN missing")
        return 1
    lines = io.open(args.text, encoding="utf-8-sig").read().strip().splitlines()
    subject, body = lines[0].strip(), "\n".join(lines[1:]).strip()
    payload = {"subject": subject, "text": body, "dry_run": not args.send}
    if args.only.strip():
        payload["only_emails"] = [e.strip() for e in args.only.split(",")]
    req = urllib.request.Request(args.api_base + "/depot/portal/bridge/announce", method="POST",
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.loads(r.read().decode("utf-8"))
    out = os.path.join(os.path.dirname(os.path.abspath(args.text)),
                       os.path.splitext(os.path.basename(args.text))[0] + ("_sent" if args.send else "_preview") + ".json")
    io.open(out, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
    if res.get("dry_run"):
        print("DRY RUN — %d recipients; details: %s" % (res.get("count", 0), out))
    else:
        print("SENT %d, failed %d; details: %s" % (len(res.get("sent", [])), len(res.get("failed", [])), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
