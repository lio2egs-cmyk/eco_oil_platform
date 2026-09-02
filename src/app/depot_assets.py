# -*- coding: utf-8 -*-
"""פורטל הדיפו — שלב 3 במפת הדרכים: "הנכסים שלי אצלכם" + בקשת/ביטול שחרור
(אישור יואב 02/09/2026, בעקבות שאלת אלירן-טנקו "איך אני מבטל נכס?").

העיקרון הקבוע: הלקוח אף פעם לא כותב לקובץ החי — הוא מגיש בקשה. הבקשה
נרשמת בענן, המשרד מקבל מייל, והגשר של יעל מושך אותה בסבב (אותו צינור כמו
הטופס המקדים: pending → fetched → posted), מעדכן את הסטטוס בקובץ ומאשר.

כלל לימור (02/09): ביטול שחרור אפשרי רק כל עוד העובד לא סימן בטאבלט
"מוכן לשחרור". המסך אוכף לפי תמונת-המצב השעתית, והגשר בודק שוב מול הקובץ
ברגע הביצוע (bounce ל-rejected אם בינתיים סומן מוכן) — כך גם פער של שעה
בין המסך למציאות לא יוצר תקלה.

תמונת-המצב נדחפת מהסבב השעתי במחשב של לימור (depot_assets_push.py, קריאה
בלבד מעותק). השיוך ללקוח = "גורם מחוייב אחסנה" מול שם+כתיבים (עוגן
הכתיבים, כמו התעודות) — ערך לא מזוהה לא מוצג לאף לקוח.
"""
from datetime import date, datetime

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from .auth import depot_admin_required
from .db import db, Client, DepotAssetSnapshot, DepotReleaseRequest, User
from .depot_certs import _folder_client_map, _norm
from .depot_portal import _depot_client_for_request
from .ecooil_bridge import ecooil_bridge_required
from .field import bridge_required

depot_assets = Blueprint("depot_assets", __name__)

# הסטטוסים בקובץ ← מה שהלקוח רואה
STATUS_HEB = {
    "בדרך להיכנס": "בדרך אלינו",
    "באחסון": "באחסנה",
    "בטיפול שטיפה": "בטיפול — שטיפה",
    "בתיקון": "בטיפול — תיקון",
    "הכנה לשחרור": "בהכנה לשחרור",
    "מוכן לשחרור": "מוכן לאיסוף",
}
READY_STATUS = "מוכן לשחרור"

REQ_STATUS_HEB = {
    ("release", "pending"): "בקשת השחרור התקבלה — בקליטה במשרד",
    ("release", "fetched"): "בקשת השחרור בקליטה במשרד",
    ("release", "posted"): "הבקשה נקלטה — הנכס בהכנה לשחרור",
    ("release", "rejected"): "הבקשה לא בוצעה — פנו למשרד",
    ("release", "error"): "הבקשה בבירור מול המשרד",
    ("cancel", "pending"): "בקשת הביטול התקבלה — בקליטה במשרד",
    ("cancel", "fetched"): "בקשת הביטול בקליטה במשרד",
    ("cancel", "posted"): "השחרור בוטל — הנכס נשאר באחסנה",
    ("cancel", "rejected"): "הביטול לא בוצע — הנכס כבר הוכן. פנו למשרד",
    ("cancel", "error"): "הבקשה בבירור מול המשרד",
}
OPEN_STATES = ("pending", "fetched")


def _client_payer_keys(client):
    keys = {_norm(client.name)} | {_norm(n) for n in client.billed_names()}
    keys.discard("")
    return keys


def _client_for_view():
    """הלקוח המחובר, או מבט-מנהלת ?client_id= (הלקח מ-17/08)."""
    client = _depot_client_for_request()
    preview = None
    if client is None:
        claims = get_jwt()
        cid = request.args.get("client_id", type=int)
        if claims.get("role") in ("admin", "depot_admin") and cid:
            c = db.session.get(Client, cid)
            if c is not None and c.division == "eco_depot":
                client, preview = c, {"client_id": c.id, "client_name": c.name}
    return client, preview


def _asset_dict(a, open_req):
    can_release = a.status == "באחסון" and open_req is None
    can_cancel = a.status == "הכנה לשחרור" and open_req is None
    note = None
    if a.status == READY_STATUS:
        note = "הנכס כבר הוכן לאיסוף — לשינויים פנו למשרד"
    d = {
        "visit_id": a.visit_id,
        "tank": a.tank,
        "material": a.material or "",
        "status": STATUS_HEB.get(a.status, a.status),
        "arrival_date": a.arrival_date.strftime("%d/%m/%Y") if a.arrival_date else None,
        "est_exit_date": a.est_exit_date.strftime("%d/%m/%Y") if a.est_exit_date else None,
        "can_release": can_release,
        "can_cancel": can_cancel,
        "note": note,
    }
    if open_req is not None:
        d["request"] = {
            "action": open_req.action,
            "status": REQ_STATUS_HEB.get((open_req.action, open_req.status),
                                         open_req.status),
            "created_at": open_req.created_at.isoformat(),
        }
    return d


# ------------------------------------------------------------ customer side
@depot_assets.route("/depot/portal/my-assets", methods=["GET"])
@jwt_required()
def my_assets():
    client, preview = _client_for_view()
    if client is None:
        return jsonify(error="depot customers only"), 403

    keys = _client_payer_keys(client)
    rows = (DepotAssetSnapshot.query
            .order_by(DepotAssetSnapshot.arrival_date.desc().nullslast(),
                      DepotAssetSnapshot.id.desc()).all())
    mine = [a for a in rows if _norm(a.storage_payer) in keys]

    # בקשות פתוחות + אחרונות של הלקוח
    reqs = (DepotReleaseRequest.query.filter_by(client_id=client.id)
            .order_by(DepotReleaseRequest.created_at.desc()).limit(50).all())
    open_by_visit = {}
    for r in reqs:
        if r.status in OPEN_STATES and r.visit_id not in open_by_visit:
            open_by_visit[r.visit_id] = r

    pushed = max((a.pushed_at for a in rows), default=None)
    out = {
        "assets": [_asset_dict(a, open_by_visit.get(a.visit_id)) for a in mine],
        "snapshot_at": pushed.isoformat() if pushed else None,
        "requests": [{
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "tank": r.tank,
            "action_heb": "בקשת שחרור" if r.action == "release" else "ביטול שחרור",
            "requested_date": r.requested_date.strftime("%d/%m/%Y") if r.requested_date else None,
            "carrier": r.carrier or "",
            "status": REQ_STATUS_HEB.get((r.action, r.status), r.status),
        } for r in reqs],
    }
    if preview:
        out["preview"] = preview
    return jsonify(out)


@depot_assets.route("/depot/portal/release-requests", methods=["POST"])
@jwt_required()
def submit_release_request():
    """בקשת שחרור / ביטול שחרור. שליחה ללקוח דיפו בלבד (תצוגת-מנהלת חסומה
    בצד השרת, כמו בטופס המקדים)."""
    client = _depot_client_for_request()
    if client is None:
        return jsonify(error="depot customers only"), 403

    data = request.get_json(silent=True) or {}
    action = data.get("action")
    visit_id = (str(data.get("visit_id") or "")).strip()
    if action not in ("release", "cancel") or not visit_id:
        return jsonify(error="בקשה לא תקינה"), 400

    a = DepotAssetSnapshot.query.filter_by(visit_id=visit_id).first()
    if a is None or _norm(a.storage_payer) not in _client_payer_keys(client):
        return jsonify(error="הנכס לא נמצא ברשימה שלכם"), 404

    open_req = (DepotReleaseRequest.query
                .filter(DepotReleaseRequest.visit_id == visit_id,
                        DepotReleaseRequest.status.in_(OPEN_STATES)).first())
    if open_req is not None:
        return jsonify(error="כבר יש בקשה פתוחה לנכס הזה — היא בטיפול המשרד"), 409

    if action == "release":
        if a.status != "באחסון":
            return jsonify(error="בקשת שחרור אפשרית רק לנכס שנמצא באחסנה"), 409
        req_date = None
        if (data.get("requested_date") or "").strip():
            try:
                req_date = date.fromisoformat(str(data["requested_date"]).strip())
            except ValueError:
                return jsonify(error="תאריך איסוף לא תקין"), 400
        if req_date is None:
            return jsonify(error="חסר תאריך איסוף מבוקש"), 400
    else:
        if a.status == READY_STATUS:
            # כלל לימור 02/09: אחרי שהעובד סימן מוכן — רק דרך המשרד
            return jsonify(error="הנכס כבר הוכן לאיסוף — לביטול פנו למשרד"), 409
        if a.status != "הכנה לשחרור":
            return jsonify(error="אין לנכס הזה שחרור פתוח לביטול"), 409
        req_date = None

    row = DepotReleaseRequest(
        client_id=client.id,
        submitted_by_user_id=int(get_jwt_identity()),
        visit_id=visit_id,
        tank=a.tank,
        action=action,
        requested_date=req_date,
        carrier=(data.get("carrier") or "").strip()[:200] or None,
        notes=(data.get("notes") or "").strip()[:400] or None,
    )
    db.session.add(row)
    db.session.commit()

    try:
        _notify_office(row, client, a)
    except Exception as exc:
        current_app.logger.error("release-request office notification failed: %s", exc)

    return jsonify(id=row.id, tank=row.tank), 201


def _notify_office(row, client, asset):
    """מייל פנימי למשרד הדיפו — טבלה RTL עם מסגרות (כלל העיצוב)."""
    from .mailer import send_office_email

    def tr(k, v):
        return (f'<tr><td style="border:1px solid #999;padding:6px 10px;'
                f'background:#EDF3F2;font-weight:bold">{k}</td>'
                f'<td style="border:1px solid #999;padding:6px 10px">{v or "—"}</td></tr>')

    kind = "בקשת שחרור" if row.action == "release" else "ביטול שחרור"
    submitter = db.session.get(User, row.submitted_by_user_id or 0)
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif">
<p>התקבלה {kind} חדשה בפורטל הדיפו — הסטטוס יתעדכן אוטומטית ע"י הגשר.</p>
<table style="border-collapse:collapse">
{tr("לקוח", client.name)}
{tr("מספר מכל", row.tank)}
{tr("מס' ביקור", row.visit_id)}
{tr("מצב נוכחי בקובץ", asset.status)}
{tr("תאריך איסוף מבוקש", row.requested_date.strftime('%d/%m/%Y') if row.requested_date else None)}
{tr("מוביל אוסף", row.carrier)}
{tr("הערות הלקוח", row.notes)}
{tr("הוגש על ידי", submitter.email if submitter else None)}
</table>
<p style="margin-top:14px"><a href="https://depot.eco-oil.co.il/depot-admin"
style="background:#5B9E96;color:#fff;padding:9px 18px;border-radius:8px;
text-decoration:none;font-weight:bold">לצפייה — מסך ניהול הדיפו</a></p></div>"""
    send_office_email(subject=f"{kind} — {row.tank} ({client.name})",
                      html=html, to="shtifot@eco-oil.co.il")


# ------------------------------------------------------------- bridge side
@depot_assets.route("/depot/portal/bridge/assets", methods=["POST"])
@ecooil_bridge_required
def bridge_replace_assets():
    """הסבב השעתי במחשב של לימור דוחף תמונת-מצב מלאה — החלפה מלאה בכל
    דחיפה (כמה מאות שורות; מה שלא בתמונה כבר לא באתר)."""
    body = request.get_json(silent=True) or {}
    items = body.get("items")
    if not isinstance(items, list):
        return jsonify(error="items list required"), 400
    now = datetime.utcnow()
    DepotAssetSnapshot.query.delete()
    added = 0
    seen = set()
    for it in items:
        vid = (str(it.get("visit_id") or "")).strip()
        tank = (str(it.get("tank") or "")).strip()
        status = (str(it.get("status") or "")).strip()
        if not vid or not tank or not status or vid in seen:
            continue
        seen.add(vid)

        def _d(key):
            v = (it.get(key) or "")
            try:
                return date.fromisoformat(str(v)[:10]) if v else None
            except ValueError:
                return None

        db.session.add(DepotAssetSnapshot(
            visit_id=vid[:40], tank=tank[:40],
            storage_payer=(str(it.get("storage_payer") or "")).strip()[:200] or None,
            status=status[:40],
            material=(str(it.get("material") or "")).strip()[:200] or None,
            arrival_date=_d("arrival_date"),
            est_exit_date=_d("est_exit_date"),
            pushed_at=now,
        ))
        added += 1
    db.session.commit()
    return jsonify(ok=True, count=added)


@depot_assets.route("/depot/portal/bridge/release-requests", methods=["GET"])
@bridge_required
def bridge_pending_requests():
    """הגשר של יעל מושך בקשות פתוחות (כמו הטופס המקדים: גם fetched מוגש
    שוב — בקשה שנמשכה אבל לא אושרה חוזרת בסבב הבא)."""
    rows = (DepotReleaseRequest.query
            .filter(DepotReleaseRequest.status.in_(OPEN_STATES))
            .order_by(DepotReleaseRequest.id).limit(50).all())
    for r in rows:
        r.status = "fetched"
    db.session.commit()
    return jsonify(requests=[{
        "id": r.id,
        "client_id": r.client_id,
        "client_name": r.client.name if r.client else "?",
        "created_at": r.created_at.isoformat(),
        "visit_id": r.visit_id,
        "tank": r.tank,
        "action": r.action,
        "requested_date": r.requested_date.isoformat() if r.requested_date else None,
        "carrier": r.carrier,
        "notes": r.notes,
    } for r in rows])


@depot_assets.route("/depot/portal/bridge/release-requests/ack", methods=["POST"])
@bridge_required
def bridge_ack_request():
    """הגשר מאשר: posted (הסטטוס עודכן בקובץ) / rejected (בדיקת-האמת מצאה
    שכבר סומן מוכן וכד') / error. ה-note מוצג במסך הניהול."""
    data = request.get_json(silent=True) or {}
    r = db.session.get(DepotReleaseRequest, int(data.get("id") or 0))
    if r is None:
        return jsonify(error="not found"), 404
    status = data.get("status")
    if status not in ("posted", "rejected", "error"):
        return jsonify(error="status must be posted/rejected/error"), 400
    r.status = status
    r.bridge_note = (data.get("note") or "")[:400] or None
    if status == "posted":
        r.posted_at = datetime.utcnow()
    db.session.commit()
    return jsonify(ok=True, id=r.id, status=r.status)


# ------------------------------------------------------------- admin side
@depot_assets.route("/depot/admin/release-requests", methods=["GET"])
@depot_admin_required
def admin_release_requests():
    heb = {"pending": "ממתינה לקליטה", "fetched": "בקליטה",
           "posted": "בוצעה — עודכן בקובץ", "rejected": "נדחתה (ראו הערה)",
           "error": "תקלה — ראו הערה"}
    rows = (DepotReleaseRequest.query
            .order_by(DepotReleaseRequest.created_at.desc()).limit(100).all())
    return jsonify(requests=[{
        "id": r.id,
        "created_at": r.created_at.isoformat(),
        "client_name": r.client.name if r.client else "?",
        "tank": r.tank,
        "visit_id": r.visit_id,
        "action_heb": "שחרור" if r.action == "release" else "ביטול שחרור",
        "requested_date": r.requested_date.strftime("%d/%m/%Y") if r.requested_date else "",
        "carrier": r.carrier or "",
        "notes": r.notes or "",
        "status": r.status,
        "status_heb": heb.get(r.status, r.status),
        "bridge_note": r.bridge_note or "",
    } for r in rows])
