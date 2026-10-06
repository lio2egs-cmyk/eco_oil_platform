# -*- coding: utf-8 -*-
"""שרת פיתוח מקומי בלי מיילים ובלי נתוני אמת — לבדיקת מסכי פורטל הדיפו בדפדפן.

- SQLite זמני ב-data/dev_nomail.db (נמחק בכל הפעלה) — לא נוגע ב-data/app.db.
- כל ערוצי המייל מנוטרלים (שרת הפיתוח הרגיל שולח מיילים אמיתיים למשרד).
- נתוני דמו: לקוח דיפו "בדיקה - פורטל" עם 3 נכסים, הגשה מקדימה ובקשת שחרור.
- הטוקן של לקוח הדמו נכתב ל-data/dev_nomail_token.json — מדביקים ל-localStorage
  (eco_access_token + eco_user) ונכנסים ישירות למסכים, בלי קישור קסם.
- פורט 5001 (launch.json: "portal-nomail").
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DB = os.path.join(DATA, "dev_nomail.db")
os.makedirs(DATA, exist_ok=True)
if os.path.exists(DB):
    os.remove(DB)
os.environ["DATABASE_URL"] = "sqlite:///" + DB.replace("\\", "/")
for k in ("RESEND_API_KEY", "MAIL_HOST", "MAIL_PASSWORD", "MAIL_USERNAME"):
    os.environ[k] = ""
os.environ.setdefault("FIELD_BRIDGE_TOKEN", "dev-bridge-token")
os.environ.setdefault("ECOOIL_BRIDGE_TOKEN", "dev-ecooil-token")
os.environ.setdefault("JWT_SECRET_KEY", "dev-nomail-secret")
sys.path.insert(0, ROOT)

from flask_jwt_extended import create_access_token, create_refresh_token  # noqa: E402
from src.app import create_app  # noqa: E402
from src.app.db import (db, Client, User, DepotAssetSnapshot, DepotPreArrival,  # noqa: E402
                        DepotReleaseRequest, DepotFormOptions)

app = create_app()
with app.app_context():
    db.create_all()
    c = Client(name="בדיקה - פורטל", division="eco_depot")
    db.session.add(c)
    db.session.flush()
    u = User(username="demo_depot", role="eco_depot_client", client_id=c.id,
             email="demo@portal.test", contact_name="נציג הדמו")
    db.session.add(u)
    adm = User(username="demo_admin", role="admin", email="admin@portal.test")
    db.session.add(adm)
    db.session.flush()
    db.session.add(DepotFormOptions(data=json.dumps(
        {"materials": ["ACRONAL", "SN 150", "TOLUENE"], "carriers": ["אקו אויל", "תבור גליל בע\"מ", "הובלות הצפון"]})))
    now = datetime.utcnow()
    db.session.add(DepotAssetSnapshot(visit_id="ISO-2026-09-101", tank="TMBU2000440", storage_payer=c.name,
                                      status="באחסון", material="SN 150", arrival_date=date(2026, 9, 3),
                                      entry_time="09:40", pushed_at=now, profit_center="60657278"))
    db.session.add(DepotAssetSnapshot(visit_id="ISO-2026-09-117", tank="UTCU5041380", storage_payer=c.name,
                                      status="הכנה לשחרור", material="ACRONAL", arrival_date=date(2026, 9, 12),
                                      pushed_at=now))
    db.session.add(DepotAssetSnapshot(visit_id="ISO-2026-09-130", tank="KRIU2266457", storage_payer=c.name,
                                      status="באחסון", material="TOLUENE", arrival_date=date(2026, 9, 20),
                                      pushed_at=now))
    db.session.add(DepotReleaseRequest(client_id=c.id, submitted_by_user_id=u.id, visit_id="ISO-2026-09-117",
                                       tank="UTCU5041380", action="release", requested_date=date(2026, 10, 8),
                                       carrier="הובלות הצפון", status="posted", posted_at=now))
    db.session.add(DepotPreArrival(client_id=c.id, submitted_by_user_id=u.id, tank_number="HOYU9667783",
                                   material="ACRONAL", un_number="1993", hazard_class="3", carrier="אקו אויל",
                                   purpose="שטיפה + אחסנה", expected_date=date.today() + timedelta(days=3),
                                   status="posted", posted_at=now, created_at=now - timedelta(days=1)))
    db.session.add(DepotPreArrival(client_id=c.id, submitted_by_user_id=u.id, tank_number="TMBU2000440",
                                   material="SN 150", un_number="1993", hazard_class="3", carrier_new="מוביל חדש בע\"מ",
                                   purpose="אחסנה בלבד", internal_ref="60657278", status="pending",
                                   created_at=now - timedelta(hours=2)))
    db.session.commit()
    claims = {"role": u.role, "client_id": c.id}
    tok = {"access_token": create_access_token(identity=str(u.id), additional_claims=claims),
           "refresh_token": create_refresh_token(identity=str(u.id), additional_claims=claims),
           "user": {"id": u.id, "username": u.username, "role": u.role, "client_id": c.id,
                    "client_name": c.name, "email": u.email},
           "admin_access_token": create_access_token(identity=str(adm.id),
                                                     additional_claims={"role": "admin", "client_id": None}),
           "admin_user": {"id": adm.id, "username": adm.username, "role": "admin", "client_id": None}}
    with open(os.path.join(DATA, "dev_nomail_token.json"), "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False)

if __name__ == "__main__":
    app.run(debug=False, use_reloader=False, port=int(os.environ.get("PORT", 5001)))
