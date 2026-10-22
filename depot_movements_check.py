# -*- coding: utf-8 -*-
"""בקרת ערוץ התנועות לטנקו (מייל כל שעתיים + API) — כלל 20/10: אין תקלה שקטה.

רץ כצעד אחרון בסבב השעתי במחשב של לימור (ecooil_bridge_hourly.py) — מחשב
אחר מזה שדוחף (הגשר אצל יעל), כך שגשר שנעצר מתגלה. קריאה בלבד: שואל את
הפורטל (bridge/movements/status) ומתריע — צליל + הודעה ליד השעון + מייל
ל-office@ (אותו מנגנון כמו בקרת הדוח היומי) — על:
  1. הגשר אצל יעל לא דחף תנועות מעל 20 דקות (בשעות העבודה)
  2. תנועות ממתינות למייל מעל שעתיים וחצי ללקוח שיש לו נמענים
  3. מייל שנכשל בשליחה
  4. מפתח API שהיה בשימוש ולא משך מעל 4 שעות (בשעות העבודה) — הלקוח שוב "עיוור"
  5. פניות API שנדחו ב-24 השעות האחרונות
כל בעיה מתריעה פעם אחת ביום (קובץ מצב), וכל ריצה נרשמת ביומן.
הערוץ "פעיל" רק כשיש נמען מסומן או מפתח פעיל — לפני ההפעלה אין התראות.

הרצה ידנית:  venv\\Scripts\\python.exe depot_movements_check.py [--dry-run]
"""
import io
import json
import os
import sys
import urllib.request
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(r"C:\eco_oil_platform_git\.env")

sys.path.insert(0, r"C:\for_eco-depot\scripts")
import daily_report_alert as A   # notify_desktop + send_mail — המנגנון הקבוע

API = "https://depot.eco-oil.co.il/depot/portal/bridge/movements/status"
LOG = r"C:\for_eco-depot\logs\movements_check.log"
STATE = r"C:\for_eco-depot\logs\movements_check_state.json"
WORK_HOURS = range(7, 19)       # 07:00-18:59, א'-ו'
PUSH_STALE_MIN = 20
MAIL_STALE_MIN = 150
API_STALE_MIN = 240


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (datetime.now().strftime("%d/%m/%Y %H:%M:%S"), msg))


def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def problems(st, now=None):
    now = now or datetime.now()
    work = now.weekday() != 5 and now.hour in WORK_HOURS
    has_recips = any(w.get("has_recipients") for w in st.get("waiting", []))
    # נמען מסומן נראה ב-waiting רק כשיש ממתינות — לכן גם שליחה כלשהי ביומן = פעיל
    active = has_recips or bool(st.get("last_mails")) or bool(st.get("api_keys"))
    out = []
    if not active:
        return out
    lp = st.get("last_push_min")
    if work and (lp is None or lp > PUSH_STALE_MIN):
        out.append(("push", "הגשר אצל יעל לא דחף תנועות לענן %s" %
                    ("מעולם" if lp is None else "כבר %d דקות" % lp),
                    "לבדוק שהמחשב של יעל דלוק ומחובר ושהדופק של הגשר מתעדכן "
                    "(bridge_heartbeat.txt). עד אז טנקו לא מקבלים עדכונים."))
    for w in st.get("waiting", []):
        if w.get("has_recipients") and w.get("oldest_min", 0) > MAIL_STALE_MIN:
            out.append(("mail|" + w["client"], "%d תנועות של %s ממתינות למייל כבר %d דקות" %
                        (w["count"], w["client"], w["oldest_min"]),
                        "המייל כל שעתיים לא יצא. לבדוק את יומן השליחות במסך הניהול / לעדכן את Claude."))
    for m in st.get("last_mails", [])[:4]:
        if m.get("result") != "נשלח":
            out.append(("mailfail|%s|%s" % (m["client"], m["slot"]),
                        "מייל התנועות ל-%s (%s) — %s" % (m["client"], m["at"], m["result"]),
                        "נכשל אצל: %s" % (m.get("failed_to") or "?")))
    for k in st.get("api_keys", []):
        lu = k.get("last_used_min")
        if work and lu is not None and lu > API_STALE_MIN:
            out.append(("api|" + k["prefix"], "המחשב של %s לא משך תנועות כבר %d שעות" %
                        (k["client"], lu // 60),
                        "כנראה תקלה אצלם — העובדים שוב 'עיוורים'. לעדכן את איש הקשר הטכני (ניר)."))
    if st.get("api_refused_24h"):
        out.append(("refused", "%d פניות API נדחו ב-24 השעות האחרונות" % st["api_refused_24h"],
                    "פרטים במסך הניהול ← החברה ← 🔑 חיבור API ← פניות אחרונות."))
    return out


def main():
    dry = "--dry-run" in sys.argv
    tok = os.environ.get("ECOOIL_BRIDGE_TOKEN")
    try:
        req = urllib.request.Request(API, headers={"Authorization": "Bearer " + (tok or "")})
        with urllib.request.urlopen(req, timeout=60) as r:
            st = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        # 404 = הקוד עוד לא נפרס לענן — לא תקלה
        if getattr(e, "code", None) == 404:
            log("status endpoint not deployed yet — skip")
            print("not deployed yet")
            return 0
        st = None
        found = [("status", "בקרת התנועות לא הצליחה לשאול את הפורטל", repr(e)[:200])]
    if st is not None:
        found = problems(st)
    today = datetime.now().strftime("%Y-%m-%d")
    state = _state()
    seen = state.get(today, [])
    fresh = [p for p in found if p[0] not in seen]
    log("check: push=%s waiting=%s keys=%d problems=%d new=%d" % (
        st.get("last_push_min") if st else "?", len(st.get("waiting", [])) if st else "?",
        len(st.get("api_keys", [])) if st else 0, len(found), len(fresh)))
    for key, title, todo in found:
        print(("NEW " if (key, title, todo) in fresh else "seen ") + title)
    if fresh and not dry:
        lines = ["• %s — %s" % (t, d) for _, t, d in fresh]
        text = "\n".join(lines)
        A.notify_desktop("תקלה בעדכון התנועות לטנקו", text[:240])
        A.send_mail("⚠ תקלה בעדכון התנועות ללקוחות — %d" % len(fresh),
                    text + "\n\n(נשלח אוטומטית מבקרת התנועות בסבב השעתי במחשב של לימור)")
        log("ALERT sent: " + " || ".join(t for _, t, _ in fresh))
        state = {today: seen + [p[0] for p in fresh]}
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:      # בקרה לעולם לא מפילה את הסבב השעתי
        log("check crashed: %r" % (e,))
        sys.exit(0)
