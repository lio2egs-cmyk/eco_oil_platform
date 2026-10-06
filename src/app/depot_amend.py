# -*- coding: utf-8 -*-
"""פורטל הדיפו — תיקון / השלמת פרטים אחרי שליחה (לימור 06/10/2026).

הרקע: בחיוב ספטמבר של הי טנק נמצאו נכסים בלי מרכז רווח — חלקם הוגשו בפורטל
והנציג לא הקליד, וחלקם מימי ההקלדה במשרד. ובקשות שחרור שהמוביל נודע רק
למחרת. הכרעת לימור: אפשרות א' — הלקוח מתקן בעצמו בפורטל, רק מרכז רווח
ומוביל, והפורטל דורס מה שבקובץ.

המנגנון = צינור ביטול ההגעה: רשומת תיקון בענן (DepotAmendment) → הגשר של
יעל מושך בכל סבב → כותב לשורה הקיימת בקובץ החי (לפי המכל / (ביקור, מכל)) →
מאשר posted/rejected → הלקוח רואה בפורטל. המשרד מקבל מייל על כל תיקון.

שלושה מקומות ללקוח:
  · טופס מקדים — "ההגשות האחרונות": ✎ על כל הגשה חיה (מרכז רווח + מוביל מביא).
  · "הנכסים שלנו": ✎ על כל נכס באתר (מרכז רווח; ומוביל אוסף אם יש בקשת שחרור).
קיצור דרך: הגשה שהגשר עוד לא משך (pending) מתעדכנת במקום — השורה תיפתח
עם הערכים החדשים, בלי רשומה לגשר. כנ"ל בקשת שחרור שעוד לא נמשכה.
"""
import json
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from .auth import depot_admin_required
from .db import (db, DepotAmendment, DepotArrivalCancel, DepotAssetSnapshot,
                 DepotFormOptions, DepotPreArrival, DepotReleaseRequest, User)
from .depot_assets import OPEN_STATES as REQ_OPEN_STATES, _client_payer_keys, _norm
from .depot_portal import _depot_client_for_request
from .field import bridge_required

depot_amend = Blueprint("depot_amend", __name__)

AMEND_OPEN = ("pending", "fetched")
FIELD_HEB = {"internal_ref": "מרכז רווח", "carrier_in": "מוביל מביא", "carrier_out": "מוביל אוסף"}
# מה הלקוח רואה ליד הפריט (ניסוח קצר, שלושה מצבים כמו בבקשות השחרור)
STATUS_HEB = {
    "pending": "ממתין לעדכון במשרד",
    "fetched": "ממתין לעדכון במשרד",
    "posted": "עודכן",
    "rejected": "לא עודכן — פנו למשרד",
    "error": "בבירור מול המשרד",
}


def _carriers():
    row = DepotFormOptions.query.first()
    if row and row.data:
        try:
            return set(json.loads(row.data).get("carriers") or [])
        except ValueError:
            pass
    return set()


def _ref_clean(v):
    return (str(v or "")).strip()[:100]


def _mk(client, kind, tank, field, old, new, **kw):
    return DepotAmendment(
        client_id=client.id, submitted_by_user_id=int(get_jwt_identity()),
        kind=kind, tank=tank, field=field,
        old_value=(old or "")[:200] or None, new_value=(new or "")[:200] or None,
        **kw)


def _latest_by_target(client, kind):
    """התיקון האחרון לכל (עוגן, שדה) של הלקוח — לתצוגה ליד הפריט."""
    rows = (DepotAmendment.query.filter_by(client_id=client.id, kind=kind)
            .order_by(DepotAmendment.id).limit(300).all())
    out = {}
    for a in rows:
        key = (a.prearrival_id if kind == "prearrival" else (a.visit_id, a.tank), a.field)
        out[key] = a
    return out


def amend_view(a):
    """מה הלקוח רואה: הערך החדש + מצב. None אם אין תיקון."""
    if a is None:
        return None
    return {"value": a.new_value or "", "status": a.status,
            "status_heb": STATUS_HEB.get(a.status, a.status),
            "note": a.bridge_note if a.status in ("rejected", "error") else None}


# ------------------------------------------------------------ טופס מקדים
@depot_amend.route("/depot/portal/prearrivals/<int:row_id>/amend", methods=["POST"])
@jwt_required()
def amend_prearrival(row_id):
    """תיקון מרכז רווח / מוביל מביא בהגשה קיימת. רק ההגשה של הלקוח המחובר,
    רק כשההגעה לא בוטלה ואין ביטול פתוח. ההגשה עצמה מתעדכנת (כדי שהרשימה
    תציג את הערך החדש); אם הגשר כבר פתח שורה — רשומת תיקון לגשר."""
    client = _depot_client_for_request()
    if client is None:
        return jsonify(error="depot customers only"), 403
    pa = db.session.get(DepotPreArrival, row_id)
    if pa is None or pa.client_id != client.id:
        return jsonify(error="ההגשה לא נמצאה"), 404
    if pa.status == "cancelled":
        return jsonify(error="ההגעה בוטלה — אין מה לתקן"), 409
    if pa.status == "error":
        return jsonify(error="ההגשה בבירור מול המשרד — פנו אלינו לתיקון"), 409
    open_cancel = (DepotArrivalCancel.query
                   .filter(DepotArrivalCancel.prearrival_id == pa.id,
                           DepotArrivalCancel.status.in_(("pending", "fetched"))).first())
    if open_cancel is not None:
        return jsonify(error="יש ביטול הגעה בטיפול להגשה הזו"), 409

    data = request.get_json(silent=True) or {}
    made = []
    live = pa.status == "pending"       # הגשר עוד לא משך — מעדכנים במקום

    if "internal_ref" in data:
        new = _ref_clean(data.get("internal_ref"))
        old = (pa.internal_ref or "").strip()
        if new != old:
            if not new:
                return jsonify(error="מרכז רווח לא נמחק מהפורטל — להסרה פנו למשרד"), 400
            pa.internal_ref = new
            made.append(_mk(client, "prearrival", pa.tank_number, "internal_ref", old, new,
                            prearrival_id=pa.id))

    if "carrier" in data or "carrier_new" in data:
        carrier = (str(data.get("carrier") or "")).strip()[:200]
        carrier_new = (str(data.get("carrier_new") or "")).strip()[:200]
        if carrier and carrier not in _carriers():
            return jsonify(error="המוביל שנבחר אינו ברשימה — בחרו מהרשימה או הקלידו מוביל חדש"), 400
        if not carrier and not carrier_new:
            return jsonify(error="בוחרים מוביל מהרשימה או מקלידים מוביל חדש"), 400
        new = carrier or carrier_new
        old = pa.carrier or pa.carrier_new or ""
        if new != old:
            pa.carrier = carrier or None
            pa.carrier_new = carrier_new or None
            made.append(_mk(client, "prearrival", pa.tank_number, "carrier_in", old, new,
                            prearrival_id=pa.id, carrier_is_new=not carrier))

    if not made:
        return jsonify(error="לא שונה דבר"), 400
    for a in made:
        if live:
            a.status, a.posted_at = "posted", datetime.utcnow()
            a.bridge_note = "עודכן לפני פתיחת השורה — השורה תיפתח עם הערך החדש"
        db.session.add(a)
    db.session.commit()
    try:
        _notify_office(made, client, pa=pa)
    except Exception as exc:
        current_app.logger.error("amendment office notification failed: %s", exc)
    return jsonify(ok=True, live=live, ids=[a.id for a in made]), 201


# ------------------------------------------------------------- הנכסים שלנו
@depot_amend.route("/depot/portal/assets/amend", methods=["POST"])
@jwt_required()
def amend_asset():
    """תיקון מרכז רווח של נכס באתר, ו/או מוביל אוסף של בקשת השחרור שלו.
    העוגן = (ביקור, מכל) מתמונת המלאי; הנכס חייב להיות של הלקוח ובאתר."""
    client = _depot_client_for_request()
    if client is None:
        return jsonify(error="depot customers only"), 403
    data = request.get_json(silent=True) or {}
    visit_id = (str(data.get("visit_id") or "")).strip()
    tank = (str(data.get("tank") or "")).strip()
    a = DepotAssetSnapshot.query.filter_by(visit_id=visit_id, tank=tank).first() if visit_id and tank else None
    if a is None or _norm(a.storage_payer) not in _client_payer_keys(client):
        return jsonify(error="הנכס לא נמצא ברשימה שלכם"), 404
    if a.exited:
        return jsonify(error="הנכס כבר יצא — לתיקון פנו למשרד"), 409

    made = []
    if "internal_ref" in data:
        new = _ref_clean(data.get("internal_ref"))
        old = (a.profit_center or "").strip()
        if new != old:
            if not new:
                return jsonify(error="מרכז רווח לא נמחק מהפורטל — להסרה פנו למשרד"), 400
            made.append(_mk(client, "asset", a.tank, "internal_ref", old, new, visit_id=a.visit_id))

    if "carrier" in data:
        new = (str(data.get("carrier") or "")).strip()[:200]
        if not new:
            return jsonify(error="חסר מוביל אוסף"), 400
        rq = (DepotReleaseRequest.query
              .filter(DepotReleaseRequest.visit_id == a.visit_id,
                      DepotReleaseRequest.tank == a.tank,
                      DepotReleaseRequest.action == "release",
                      DepotReleaseRequest.status.in_(("pending", "fetched", "posted")))
              .order_by(DepotReleaseRequest.id.desc()).first())
        if rq is None:
            return jsonify(error="אין לנכס הזה בקשת שחרור — מוביל אוסף נמסר בבקשת השחרור"), 409
        old = (rq.carrier or "").strip()
        if new != old:
            rq.carrier = new
            am = _mk(client, "asset", a.tank, "carrier_out", old, new,
                     visit_id=a.visit_id, release_request_id=rq.id)
            if rq.status == "pending":   # הגשר עוד לא משך את הבקשה — תלך עם המוביל החדש
                am.status, am.posted_at = "posted", datetime.utcnow()
                am.bridge_note = "עודכן לפני שהבקשה נקלטה — הבקשה תיקלט עם המוביל החדש"
            made.append(am)

    if not made:
        return jsonify(error="לא שונה דבר"), 400
    for am in made:
        db.session.add(am)
    db.session.commit()
    try:
        _notify_office(made, client, asset=a)
    except Exception as exc:
        current_app.logger.error("amendment office notification failed: %s", exc)
    return jsonify(ok=True, ids=[am.id for am in made]), 201


# ------------------------------------------------------------ מייל למשרד
def _notify_office(made, client, pa=None, asset=None):
    """מייל פנימי אחד לכל שמירה — טבלה RTL עם מסגרות (כלל העיצוב)."""
    from .mailer import send_office_email

    def tr(k, v):
        return (f'<tr><td style="border:1px solid #999;padding:6px 10px;'
                f'background:#EDF3F2;font-weight:bold">{k}</td>'
                f'<td style="border:1px solid #999;padding:6px 10px">{v or "—"}</td></tr>')

    submitter = db.session.get(User, made[0].submitted_by_user_id or 0)
    tank = made[0].tank
    where = ("הגשה מקדימה מ-%s" % pa.created_at.strftime("%d/%m/%Y") if pa is not None
             else "נכס באתר — ביקור %s" % (asset.visit_id if asset is not None else "?"))
    rows = ""
    for a in made:
        how = ("יעודכן אוטומטית ע\"י הגשר" if a.status in AMEND_OPEN else a.bridge_note)
        rows += tr(FIELD_HEB.get(a.field, a.field),
                   f"<b>{a.new_value or '—'}</b> &nbsp;(היה: {a.old_value or 'ריק'}) — {how}"
                   + (" · מוביל שלא ברשימה — לבדיקת המשרד" if a.carrier_is_new else ""))
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif">
<p>הלקוח תיקן בפורטל הדיפו <b>פרטים אחרי שליחה</b>. הערך החדש דורס את מה שבקובץ (הכרעת לימור 06/10/2026).</p>
<table style="border-collapse:collapse">
{tr("לקוח", client.name)}
{tr("מספר איזוטנק", tank)}
{tr("איפה", where)}
{rows}
{tr("תוקן על ידי", submitter.email if submitter else None)}
</table>
<p style="margin-top:14px"><a href="https://depot.eco-oil.co.il/depot-admin"
style="background:#5B9E96;color:#fff;padding:9px 18px;border-radius:8px;
text-decoration:none;font-weight:bold">לצפייה — מסך ניהול הדיפו</a></p></div>"""
    send_office_email(subject=f"תיקון פרטים מהפורטל — {tank} ({client.name})",
                      html=html, to="shtifot@eco-oil.co.il")


# ------------------------------------------------------------- bridge side
@depot_amend.route("/depot/portal/bridge/amendments", methods=["GET"])
@bridge_required
def bridge_pending_amendments():
    """הגשר של יעל מושך תיקונים פתוחים. תיקון להגשה שעדיין לא נפתחה לה שורה
    (fetched) מחכה — יוגש רק אחרי ש-posted, כשיש שורה לכתוב אליה. כמו שאר
    הצינורות: גם fetched מוגש שוב (נמשך ולא אושר → חוזר בסבב הבא)."""
    rows = (DepotAmendment.query
            .filter(DepotAmendment.status.in_(AMEND_OPEN))
            .order_by(DepotAmendment.id).limit(50).all())
    out = []
    for a in rows:
        if a.kind == "prearrival":
            pa = db.session.get(DepotPreArrival, a.prearrival_id or 0)
            if pa is None or pa.status != "posted":
                continue
        a.status = "fetched"
        out.append({
            "id": a.id, "kind": a.kind, "field": a.field,
            "client_name": a.client.name if a.client else "?",
            "created_at": a.created_at.isoformat(),
            "tank": a.tank, "visit_id": a.visit_id,
            "old_value": a.old_value, "new_value": a.new_value,
            "carrier_is_new": bool(a.carrier_is_new),
        })
    db.session.commit()
    return jsonify(amendments=out)


@depot_amend.route("/depot/portal/bridge/amendments/ack", methods=["POST"])
@bridge_required
def bridge_ack_amendment():
    data = request.get_json(silent=True) or {}
    a = db.session.get(DepotAmendment, int(data.get("id") or 0))
    if a is None:
        return jsonify(error="not found"), 404
    status = data.get("status")
    if status not in ("posted", "rejected", "error"):
        return jsonify(error="status must be posted/rejected/error"), 400
    a.status = status
    a.bridge_note = (data.get("note") or "")[:400] or None
    if status == "posted":
        a.posted_at = datetime.utcnow()
        # הפורטל דורס: תמונת המלאי מציגה את הערך החדש כבר עכשיו, לא רק
        # אחרי הדחיפה השעתית הבאה
        if a.field == "internal_ref" and a.visit_id:
            snap = DepotAssetSnapshot.query.filter_by(visit_id=a.visit_id, tank=a.tank).first()
            if snap is not None:
                snap.profit_center = a.new_value
    db.session.commit()
    return jsonify(ok=True, id=a.id, status=a.status)


# -------------------------------------------------------------- admin side
@depot_amend.route("/depot/admin/amendments", methods=["GET"])
@depot_admin_required
def admin_amendments():
    heb = {"pending": "ממתין לגשר", "fetched": "בקליטה",
           "posted": "בוצע — עודכן בקובץ", "rejected": "נדחה (ראו הערה)",
           "error": "תקלה — ראו הערה"}
    rows = (DepotAmendment.query.order_by(DepotAmendment.created_at.desc()).limit(100).all())
    users = {u.id: u.email for u in User.query.filter(
        User.id.in_({r.submitted_by_user_id for r in rows if r.submitted_by_user_id})).all()} if rows else {}
    return jsonify(amendments=[{
        "id": a.id,
        "created_at": a.created_at.isoformat(),
        "client_name": a.client.name if a.client else "?",
        "submitted_by": users.get(a.submitted_by_user_id, ""),
        "tank": a.tank,
        "where": ("הגשה מקדימה" if a.kind == "prearrival" else "ביקור %s" % (a.visit_id or "?")),
        "field_heb": FIELD_HEB.get(a.field, a.field),
        "old_value": a.old_value or "",
        "new_value": a.new_value or "",
        "carrier_is_new": bool(a.carrier_is_new),
        "status": a.status,
        "status_heb": heb.get(a.status, a.status),
        "bridge_note": a.bridge_note or "",
    } for a in rows])
