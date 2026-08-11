# -*- coding: utf-8 -*-
"""מסך ניהול הדיפו — ה-API (לימור 06/08/2026, אפשרות א):

מסך ניהול נפרד לגמרי מהמסך של אקו-אויל. עובדים בו: לימור, "משרד דיפו"
(שם תפקיד — לא שם אדם, כך שהמעקב שורד החלפת מאיישת) ויואב — כל אחד בכניסה
אישית בקסם-קישור (role=depot_admin), וגם סיסמת המאסטר של לימור עובדת.

כל פעולה נרשמת ב-AdminActionLog על שם מבצעה. המסך רואה ומנהל אך ורק
חברות ומשתמשים של חטיבת הדיפו (division=eco_depot) — עולם האויל לא נגיש.
"""
import secrets as _secrets

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity
from sqlalchemy.orm import defer
from werkzeug.security import generate_password_hash

from .auth import depot_admin_required
from .db import (db, AdminActionLog, Client, DepotPreArrival, LoginAuditLog,
                 MagicLinkToken, User)

depot_admin = Blueprint("depot_admin", __name__, url_prefix="/depot/admin")

MASTER_ACTOR = "מנהלת ראשית"


def _actor():
    """שם מבצע הפעולה ליומן: שם התצוגה של איש הצוות, או המאסטר."""
    claims = get_jwt()
    if claims.get("role") == "admin":
        return MASTER_ACTOR
    user = db.session.get(User, int(get_jwt_identity()))
    return user.username if user else "?"


def _log(action, details=""):
    db.session.add(AdminActionLog(actor=_actor(), division="eco_depot",
                                  action=action, details=details[:400]))


def _depot_client_or_404(client_id):
    client = db.session.get(Client, int(client_id))
    if client is None or client.division != "eco_depot":
        return None
    return client


@depot_admin.route("/overview", methods=["GET"])
@depot_admin_required
def overview():
    """הכל למסך במכה אחת: חברות הדיפו + המשתמשים שלהן, הצוות, ויומן אחרון."""
    clients = (Client.query.filter_by(division="eco_depot")
               .order_by(Client.name).all())
    users = (User.query.filter_by(role="eco_depot_client")
             .order_by(User.client_id, User.id).all())
    by_client = {}
    for u in users:
        by_client.setdefault(u.client_id, []).append({
            "id": u.id, "email": u.email,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        })
    staff = User.query.filter_by(role="depot_admin").order_by(User.id).all()
    actions = (AdminActionLog.query.filter_by(division="eco_depot")
               .order_by(AdminActionLog.at.desc()).limit(40).all())
    return jsonify({
        "is_master": get_jwt().get("role") == "admin",
        "me": _actor(),
        "clients": [{
            "id": c.id, "name": c.name,
            "billing_aliases": c.billing_aliases or "",
            "users": by_client.get(c.id, []),
        } for c in clients],
        "staff": [{
            "id": s.id, "display_name": s.username, "email": s.email,
            "last_login_at": s.last_login_at.isoformat() if s.last_login_at else None,
        } for s in staff],
        "actions": [{
            "at": a.at.isoformat(), "actor": a.actor,
            "action": a.action, "details": a.details,
        } for a in actions],
    })


# מצבי הטופס במילים של המשרד (הלקוח רואה נוסח אחר בעמוד הטופס שלו)
PREARRIVAL_STATUS_HEB = {
    "pending": "ממתין לקליטה במשרד",
    "fetched": "בקליטה במשרד",
    "posted": "נקלט — נפתחה שורת צפי בקובץ",
    "error": "תקלה בקליטה — ראו הערת גשר",
}


@depot_admin.route("/prearrivals", methods=["GET"])
@depot_admin_required
def prearrivals():
    """הגשות המידע המקדים מהפורטל — תצוגה למשרד (קריאה בלבד).
    קובץ ה-MSDS עצמו לא נטען לרשימה (defer) — רק סימון צורף/לא."""
    rows = (DepotPreArrival.query
            .options(defer(DepotPreArrival.msds_data))
            .order_by(DepotPreArrival.created_at.desc())
            .limit(100).all())
    submitters = {u.id: u.email for u in User.query.filter(
        User.id.in_({r.submitted_by_user_id for r in rows if r.submitted_by_user_id})).all()} if rows else {}
    out = []
    for r in rows:
        services = " · ".join(filter(None, [
            "ייבוש" if r.svc_dry else None,
            "בדיקת ואקום" if r.svc_vacuum else None,
            f"סט תמונות ({r.svc_photos})" if r.svc_photos else None,
            f"תיקונים: {r.svc_repairs}" if r.svc_repairs else None]))
        out.append({
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "client_name": r.client.name if r.client else "?",
            "submitted_by": submitters.get(r.submitted_by_user_id, ""),
            "tank_number": r.tank_number,
            "material": r.material,
            "un_class": f"{r.un_number} / {r.hazard_class}",
            "carrier": r.carrier or (f"חדש: {r.carrier_new}" if r.carrier_new else ""),
            "purpose": r.purpose if r.purpose != "אחר" else (r.purpose_other or "אחר"),
            "expected_date": r.expected_date.strftime("%d/%m/%Y") if r.expected_date else "",
            "services": services,
            "has_msds": bool(r.msds_size),
            "status": r.status,
            "status_heb": PREARRIVAL_STATUS_HEB.get(r.status, r.status),
            "bridge_note": r.bridge_note or "",
            "posted_at": r.posted_at.isoformat() if r.posted_at else None,
        })
    counts = {s: 0 for s in PREARRIVAL_STATUS_HEB}
    for r in out:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return jsonify(prearrivals=out, counts=counts)


@depot_admin.route("/clients", methods=["POST"])
@depot_admin_required
def create_client():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    aliases = (data.get("billing_aliases") or "").strip() or None
    if not name:
        return jsonify(error="חסר שם חברה"), 400
    if Client.query.filter_by(name=name).first():
        return jsonify(error="חברה בשם הזה כבר קיימת"), 409
    client = Client(name=name, division="eco_depot", client_type="direct",
                    billing_aliases=aliases)
    db.session.add(client)
    _log("הקמת חברה", name)
    db.session.commit()
    return jsonify(id=client.id, name=client.name), 201


@depot_admin.route("/clients/<int:client_id>", methods=["PUT"])
@depot_admin_required
def update_client(client_id):
    client = _depot_client_or_404(client_id)
    if client is None:
        return jsonify(error="חברה לא נמצאה"), 404
    data = request.get_json(silent=True) or {}
    if "billing_aliases" in data:
        client.billing_aliases = (data.get("billing_aliases") or "").strip() or None
        _log("עדכון צורות כתיב", client.name)
    db.session.commit()
    return jsonify(id=client.id, name=client.name,
                   billing_aliases=client.billing_aliases or "")


@depot_admin.route("/users", methods=["POST"])
@depot_admin_required
def create_user():
    """חשבון לקוח דיפו (קסם-קישור, בלי סיסמה) — לחברה של הדיפו בלבד."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    client_id = data.get("client_id")
    if not email or "@" not in email:
        return jsonify(error="חסרה כתובת מייל תקינה"), 400
    client = _depot_client_or_404(client_id) if client_id else None
    if client is None:
        return jsonify(error="חברה לא נמצאה"), 404
    if User.query.filter_by(email=email).first() or User.query.filter_by(username=email).first():
        return jsonify(error="משתמש עם המייל הזה כבר קיים"), 409
    user = User(username=email, email=email,
                password_hash=generate_password_hash(_secrets.token_hex(32)),
                role="eco_depot_client", client_id=client.id)
    db.session.add(user)
    _log("הוספת משתמש לקוח", f"{email} ← {client.name}")
    db.session.commit()
    return jsonify(id=user.id, email=user.email, client_id=client.id), 201


@depot_admin.route("/users/<int:user_id>", methods=["DELETE"])
@depot_admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if user is None or user.role != "eco_depot_client":
        return jsonify(error="משתמש לא נמצא"), 404
    client = db.session.get(Client, user.client_id) if user.client_id else None
    MagicLinkToken.query.filter_by(user_id=user.id).delete()
    LoginAuditLog.query.filter_by(user_id=user.id).update({"user_id": None})
    email = user.email
    _log("הסרת משתמש לקוח", f"{email} ({client.name if client else '?'})")
    db.session.delete(user)
    db.session.commit()
    return jsonify(deleted=True, email=email)
