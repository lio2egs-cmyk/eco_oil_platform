# -*- coding: utf-8 -*-
"""פורטל הדיפו — חיבור הכתיבה למערכת של הלקוח (טנקו, לימור 02/11/2026).

בקשת ניר (טנקו): "שידורים בין המערכות ולא הקלדות ידניות" — הפריוריטי שלהם
שולח בקשה מקדימה / בקשת שחרור / ביטולים ישר לפורטל, בלי שאדם יקליד בטופס.

העיקרון הקבוע של הפורטל לא משתנה: הלקוח אף פעם לא כותב לקובץ החי — הוא
מגיש בקשה. כל בקשה כאן עוברת את אותן בדיקות בדיוק כמו הטופס בפורטל
(validate_prearrival / _release_target / _release_fields), נרשמת באותן
טבלאות, המשרד מקבל את אותו מייל (עם "הוגש על ידי: מערכת הלקוח (API)"),
והגשר של יעל מטפל בה כמו בכל בקשה מהטופס — הוא לא יודע מאיפה היא הגיעה.

השער: אותו מפתח של חיבור הקריאה (depot_movements.api_gate) — מפתח, כתובת
IP מורשית, קצב. כתיבה רק למפתח שסומן "מורשה לכתוב" במסך הניהול.
בקשה שנדחתה בבדיקה חוזרת מיד עם הסיבה בעברית, לכל שדה, ולא נשמר כלום.
"""
import base64
import binascii
import json
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

from .db import (db, DepotArrivalCancel, DepotAssetSnapshot, DepotFormOptions,
                 DepotPreArrival, DepotReleaseRequest)
from .depot_assets import (OPEN_STATES, READY_STATUS, REQ_STATUS_HEB, STATUS_HEB,
                           _client_payer_keys, _notify_office as _notify_release,
                           _notify_office_batch as _notify_release_batch,
                           _release_fields, _release_target)
from .depot_certs import _norm
from .depot_movements import _api_fail, api_gate, api_log
from .depot_portal import (CANCELLABLE_STATES, PHOTO_SETS, PURPOSES,
                           _notify_office_cancel, create_arrival_cancel,
                           notify_new_prearrival, validate_prearrival)

depot_api_write = Blueprint("depot_api_write", __name__, url_prefix="/depot/api/v1")

# קודים באנגלית למערכת של הלקוח — מקבלים גם את הנוסח העברי כלשונו
PURPOSE_CODES = {"wash_storage": PURPOSES[0], "storage": PURPOSES[1],
                 "wash": PURPOSES[2], "other": PURPOSES[3]}
PHOTO_CODES = {"2in_4out": PHOTO_SETS[0], "full": PHOTO_SETS[1]}
PREARRIVAL_STATUS_HEB = {"pending": "נקלט — ממתין לפתיחת שורה במשרד",
                         "fetched": "בקליטה במשרד",
                         "posted": "נפתחה שורת צפי — הנכס מוכר למערכת",
                         "error": "בבירור מול המשרד",
                         "cancelled": "ההגעה בוטלה"}
TEXT_FIELDS = ("tank_number", "material", "un_number", "hazard_class", "carrier",
               "carrier_new", "purpose_other", "expected_date", "svc_repairs",
               "internal_ref", "emergency_phone", "payer_storage", "payer_wash",
               "payer_extras", "payer_repairs", "notes")
MAX_DAYS = 60


def _truthy(v):
    return v is True or str(v).strip().lower() in ("1", "true", "yes", "on")


def _form_from_json(d):
    """JSON של המערכת → מילון שדות כמו בטופס (מחרוזות; "1" = מסומן), כדי
    שהבדיקה תהיה אותה פונקציה בדיוק."""
    f = {k: ("" if d.get(k) is None else str(d.get(k))) for k in TEXT_FIELDS}
    purpose = str(d.get("purpose") or "").strip()
    f["purpose"] = PURPOSE_CODES.get(purpose, purpose)
    f["svc_dry"] = "1" if _truthy(d.get("svc_dry")) else ""
    f["svc_vacuum"] = "1" if _truthy(d.get("svc_vacuum")) else ""
    photos = str(d.get("svc_photos") or "").strip()
    if photos:
        f["svc_photos_on"] = "1"
        f["svc_photos"] = PHOTO_CODES.get(photos, photos)
    if f["svc_repairs"].strip():
        f["svc_repairs_on"] = "1"
    return f


def _days_arg():
    try:
        return max(1, min(MAX_DAYS, int(request.args.get("days") or 7)))
    except ValueError:
        return 7


def _iso(dt):
    return dt.replace(microsecond=0).isoformat() + "Z" if dt else None


def _my_onsite(client):
    """הנכסים של הלקוח שנמצאים אצלנו עכשיו (תמונת המצב השעתית)."""
    keys = _client_payer_keys(client)
    rows = (DepotAssetSnapshot.query
            .filter(DepotAssetSnapshot.exited.is_(False))
            .order_by(DepotAssetSnapshot.arrival_date.desc().nullslast(),
                      DepotAssetSnapshot.id.desc()).all())
    return [a for a in rows if _norm(a.storage_payer) in keys]


def _norm_tank(t):
    return str(t or "").upper().replace(" ", "").strip()


# ------------------------------------------------------------------ read
@depot_api_write.route("/form-options", methods=["GET"])
def api_form_options():
    """רשימות הבחירה של הטופס — אותן רשימות שהלקוח רואה בפורטל."""
    key, ip, fail = api_gate("form-options")
    if fail is not None:
        return fail
    row = DepotFormOptions.query.first()
    data = {}
    if row and row.data:
        try:
            data = json.loads(row.data)
        except ValueError:
            data = {}
    api_log(key, ip, "form-options", 200)
    return jsonify(materials=data.get("materials") or [],
                   carriers=data.get("carriers") or [],
                   purposes=[{"code": c, "text": t} for c, t in PURPOSE_CODES.items()],
                   photo_sets=[{"code": c, "text": t} for c, t in PHOTO_CODES.items()])


@depot_api_write.route("/assets", methods=["GET"])
def api_assets():
    """הנכסים של הלקוח שנמצאים אצלנו עכשיו — מה שהוא רואה ב"הנכסים שלנו"."""
    key, ip, fail = api_gate("assets")
    if fail is not None:
        return fail
    mine = _my_onsite(key.client)
    open_keys = {(r.visit_id, r.tank) for r in DepotReleaseRequest.query.filter(
        DepotReleaseRequest.client_id == key.client_id,
        DepotReleaseRequest.status.in_(OPEN_STATES)).all()}
    out = [{
        "tank": a.tank,
        "profit_center": a.profit_center,
        "status": STATUS_HEB.get(a.status, a.status),
        "arrival_date": a.arrival_date.isoformat() if a.arrival_date else None,
        "open_request": (a.visit_id, a.tank) in open_keys,
        "can_release": a.status == "באחסון" and (a.visit_id, a.tank) not in open_keys,
        "can_cancel_release": a.status == "הכנה לשחרור" and (a.visit_id, a.tank) not in open_keys,
    } for a in mine]
    pushed = max((a.pushed_at for a in mine), default=None)
    api_log(key, ip, "assets", 200, rows=len(out))
    return jsonify(snapshot_at=_iso(pushed), count=len(out), assets=out)


@depot_api_write.route("/prearrivals", methods=["GET"])
def api_list_prearrivals():
    """הבקשות המקדימות של הלקוח (מהטופס ומהמערכת) ומצב כל אחת."""
    key, ip, fail = api_gate("prearrivals")
    if fail is not None:
        return fail
    cut = datetime.utcnow() - timedelta(days=_days_arg())
    rows = (DepotPreArrival.query
            .filter(DepotPreArrival.client_id == key.client_id,
                    db.or_(DepotPreArrival.created_at >= cut,
                           DepotPreArrival.status.in_(("pending", "fetched"))))
            .order_by(DepotPreArrival.created_at.desc()).limit(300).all())
    cancels = {c.prearrival_id: c for c in DepotArrivalCancel.query.filter(
        DepotArrivalCancel.prearrival_id.in_([r.id for r in rows] or [0]))
        .order_by(DepotArrivalCancel.id).all()}
    out = []
    for r in rows:
        c = cancels.get(r.id)
        out.append({
            "id": r.id,
            "created_at": _iso(r.created_at),
            "source": r.source or "portal",
            "tank_number": r.tank_number,
            "internal_ref": r.internal_ref,
            "purpose": r.purpose if r.purpose != "אחר" else (r.purpose_other or "אחר"),
            "expected_date": r.expected_date.isoformat() if r.expected_date else None,
            "status": r.status,
            "status_text": PREARRIVAL_STATUS_HEB.get(r.status, r.status),
            "cancel": ({"status": c.status, "note": c.bridge_note} if c is not None else None),
            "can_cancel": r.status in CANCELLABLE_STATES and c is None,
        })
    api_log(key, ip, "prearrivals", 200, rows=len(out))
    return jsonify(count=len(out), prearrivals=out)


@depot_api_write.route("/release-requests", methods=["GET"])
def api_list_releases():
    """בקשות השחרור / ביטול השחרור של הלקוח ומצב כל אחת."""
    key, ip, fail = api_gate("release-requests")
    if fail is not None:
        return fail
    cut = datetime.utcnow() - timedelta(days=_days_arg())
    rows = (DepotReleaseRequest.query
            .filter(DepotReleaseRequest.client_id == key.client_id,
                    db.or_(DepotReleaseRequest.created_at >= cut,
                           DepotReleaseRequest.status.in_(OPEN_STATES)))
            .order_by(DepotReleaseRequest.created_at.desc()).limit(300).all())
    out = [{
        "id": r.id,
        "created_at": _iso(r.created_at),
        "source": r.source or "portal",
        "tank": r.tank,
        "action": r.action,
        "requested_date": r.requested_date.isoformat() if r.requested_date else None,
        "requested_date_to": r.requested_date_to.isoformat() if r.requested_date_to else None,
        "carrier": r.carrier,
        "status": r.status,
        "status_text": REQ_STATUS_HEB.get((r.action, r.status), r.status),
        "note": r.bridge_note if r.status in ("rejected", "error") else None,
    } for r in rows]
    api_log(key, ip, "release-requests", 200, rows=len(out))
    return jsonify(count=len(out), requests=out)


# ----------------------------------------------------------------- write
@depot_api_write.route("/prearrivals", methods=["POST"])
def api_submit_prearrival():
    """בקשה מקדימה — JSON (MSDS כ-base64) או multipart כמו הטופס."""
    ep = "prearrivals:create"
    key, ip, fail = api_gate(ep, write=True)
    if fail is not None:
        return fail
    client = key.client

    msds_bytes = msds_name = msds_mime = None
    if request.mimetype == "multipart/form-data":
        src = request.form
        f = _form_from_json({k: src.get(k) for k in src.keys()})
        up = request.files.get("msds")
        if up and up.filename:
            msds_bytes, msds_name, msds_mime = up.read(), up.filename, up.mimetype
    else:
        d = request.get_json(silent=True)
        if not isinstance(d, dict):
            return _api_fail(400, "body is not a JSON object", key=key, ip=ip, endpoint=ep)
        f = _form_from_json(d)
        m = d.get("msds")
        if isinstance(m, dict) and m.get("content_base64"):
            try:
                msds_bytes = base64.b64decode(str(m["content_base64"]), validate=True)
            except (binascii.Error, ValueError):
                return _api_fail(422, "msds: invalid base64", key=key, ip=ip, endpoint=ep,
                                 errors={"msds": "קובץ ה-MSDS לא תקין (base64)"})
            msds_name = str(m.get("filename") or "msds.pdf")
            msds_mime = str(m.get("mime") or "application/pdf")

    fields, errors = validate_prearrival(f, msds_bytes, msds_name, msds_mime)
    if errors:
        return _api_fail(422, "validation: " + ", ".join(sorted(errors)), key=key, ip=ip,
                         endpoint=ep, errors=errors)

    # הגנה מפני שליחה כפולה (ניסיון חוזר של המערכת אחרי ניתוק): בקשה פתוחה
    # לאותו מכל, או מכל שכבר מופיע אצלנו כ"בדרך להיכנס" → לא נוצרת שנייה.
    tank = fields["tank_number"]
    dup = (DepotPreArrival.query
           .filter(DepotPreArrival.client_id == client.id,
                   DepotPreArrival.tank_number == tank,
                   DepotPreArrival.status.in_(("pending", "fetched")))
           .order_by(DepotPreArrival.id.desc()).first())
    if dup is not None:
        return _api_fail(409, "duplicate: open prearrival %d" % dup.id, key=key, ip=ip,
                         endpoint=ep, existing_id=dup.id,
                         errors={"tank_number": "כבר יש בקשה מקדימה פתוחה למכל הזה"})
    if any(_norm_tank(a.tank) == tank and a.status == "בדרך להיכנס" for a in _my_onsite(client)):
        return _api_fail(409, "duplicate: tank already expected", key=key, ip=ip, endpoint=ep,
                         errors={"tank_number": "המכל כבר רשום אצלנו כ'בדרך להיכנס'"})

    row = DepotPreArrival(client_id=client.id, submitted_by_user_id=None,
                          source="api", api_key_id=key.id, **fields)
    db.session.add(row)
    db.session.commit()
    notify_new_prearrival(row, client)
    api_log(key, ip, ep, 201, rows=1, note="id %d %s" % (row.id, row.tank_number))
    return jsonify(id=row.id, tank_number=row.tank_number, status=row.status,
                   status_text=PREARRIVAL_STATUS_HEB["pending"]), 201


@depot_api_write.route("/prearrivals/<int:row_id>/cancel", methods=["POST"])
def api_cancel_prearrival(row_id):
    """ביטול הגעה — אותו צינור כמו הכפתור בפורטל (מקור 'priority')."""
    ep = "prearrivals:cancel"
    key, ip, fail = api_gate(ep, write=True)
    if fail is not None:
        return fail
    client = key.client
    r = db.session.get(DepotPreArrival, row_id)
    if r is None or r.client_id != client.id:
        return _api_fail(404, "prearrival %d not found" % row_id, key=key, ip=ip, endpoint=ep,
                         errors={"id": "הבקשה המקדימה לא נמצאה"})
    if r.status not in CANCELLABLE_STATES:
        return _api_fail(409, "not cancellable (%s)" % r.status, key=key, ip=ip, endpoint=ep,
                         errors={"id": "את הבקשה הזו כבר אי-אפשר לבטל — פנו למשרד"})
    if DepotArrivalCancel.query.filter(DepotArrivalCancel.prearrival_id == r.id).first():
        return _api_fail(409, "cancel already sent", key=key, ip=ip, endpoint=ep,
                         errors={"id": "כבר נשלח ביטול לבקשה הזו — הוא בטיפול המשרד"})
    d = request.get_json(silent=True) or {}
    row = create_arrival_cancel(client, r.tank_number, source="priority",
                                reason=str(d.get("reason") or "").strip(), prearrival=r)
    try:
        _notify_office_cancel(row, r, client)
    except Exception as exc:
        current_app.logger.error("api arrival-cancel office notification failed: %s", exc)
    api_log(key, ip, ep, 201, rows=1, note="prearrival %d %s" % (r.id, r.tank_number))
    return jsonify(id=row.id, prearrival_id=r.id, tank=row.tank, status=row.status), 201


@depot_api_write.route("/release-requests", methods=["POST"])
def api_submit_release():
    """בקשת שחרור למכל אחד או לכמה — כמו השחרור המרובה בפורטל: הכול-או-כלום,
    פרטים כלליים (תאריך, מוביל, הערות) + אפשרות לדרוס לכל מכל. המכל מזוהה
    לפי המספר בלבד — הפורטל מוצא את הביקור שנמצא אצלנו עכשיו."""
    ep = "release-requests:create"
    key, ip, fail = api_gate(ep, write=True)
    if fail is not None:
        return fail
    client = key.client
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _api_fail(400, "body is not a JSON object", key=key, ip=ip, endpoint=ep)
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return _api_fail(422, "no items", key=key, ip=ip, endpoint=ep,
                         errors={"items": "לא נשלח אף מכל"})
    if len(items) > 60:
        return _api_fail(422, "too many items", key=key, ip=ip, endpoint=ep,
                         errors={"items": "אפשר לבקש עד 60 מכלים בבת אחת"})

    onsite = _my_onsite(client)
    targets, errors, seen = [], [], set()
    for it in items:
        it = it if isinstance(it, dict) else {}
        tank = _norm_tank(it.get("tank"))
        if not tank:
            errors.append({"tank": "?", "error": "חסר מספר מכל"})
            continue
        if tank in seen:
            continue
        seen.add(tank)
        cands = [a for a in onsite if _norm_tank(a.tank) == tank]
        if not cands:
            errors.append({"tank": tank, "error": "המכל לא נמצא אצלנו כרגע ברשימה שלכם"})
            continue
        a0 = next((a for a in cands if a.status == "באחסון"), cands[0])
        a, err = _release_target(client, a0.visit_id, a0.tank)
        if err:
            errors.append({"tank": tank, "error": err})
            continue
        merged = {k: data.get(k) for k in ("requested_date", "requested_date_to", "carrier", "notes")}
        for k in ("requested_date", "requested_date_to", "carrier", "notes"):
            if str(it.get(k) or "").strip():
                merged[k] = it.get(k)
        if str(it.get("requested_date") or "").strip() and not str(it.get("requested_date_to") or "").strip():
            merged["requested_date_to"] = None   # תאריך משלו בלי "עד" = יום אחד
        merged = {k: ("" if v is None else str(v)) for k, v in merged.items()}
        fields, err = _release_fields(merged)
        if err:
            errors.append({"tank": tank, "error": err})
            continue
        targets.append((a, fields))
    if errors:
        return _api_fail(422, "rejected: " + ", ".join(e["tank"] for e in errors),
                         key=key, ip=ip, endpoint=ep,
                         message="חלק מהמכלים לא ניתנים לשחרור — לא נשלחה אף בקשה",
                         errors=errors)

    rows = []
    for a, fields in targets:
        row = DepotReleaseRequest(client_id=client.id, submitted_by_user_id=None,
                                  visit_id=a.visit_id, tank=a.tank, action="release",
                                  source="api", api_key_id=key.id, **fields)
        db.session.add(row)
        rows.append((row, a))
    db.session.commit()
    try:
        if len(rows) == 1:
            _notify_release(rows[0][0], client, rows[0][1])
        else:
            _notify_release_batch([r for r, _ in rows], client, {r.id: a for r, a in rows})
    except Exception as exc:
        current_app.logger.error("api release office notification failed: %s", exc)
    api_log(key, ip, ep, 201, rows=len(rows), note=", ".join(r.tank for r, _ in rows))
    return jsonify(count=len(rows), requests=[{
        "id": r.id, "tank": r.tank, "status": r.status,
        "status_text": REQ_STATUS_HEB.get(("release", r.status), r.status)} for r, _ in rows]), 201


@depot_api_write.route("/release-requests/cancel", methods=["POST"])
def api_cancel_release():
    """ביטול שחרור — רק כל עוד העובד לא סימן "מוכן לשחרור" (כלל לימור 02/09)."""
    ep = "release-requests:cancel"
    key, ip, fail = api_gate(ep, write=True)
    if fail is not None:
        return fail
    client = key.client
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return _api_fail(400, "body is not a JSON object", key=key, ip=ip, endpoint=ep)
    tank = _norm_tank(d.get("tank"))
    cands = [a for a in _my_onsite(client) if _norm_tank(a.tank) == tank] if tank else []
    if not cands:
        return _api_fail(404, "tank not on site: %s" % (tank or "?"), key=key, ip=ip, endpoint=ep,
                         errors={"tank": "המכל לא נמצא אצלנו כרגע ברשימה שלכם"})
    a = next((x for x in cands if x.status in ("הכנה לשחרור", READY_STATUS)), cands[0])
    if DepotReleaseRequest.query.filter(DepotReleaseRequest.visit_id == a.visit_id,
                                        DepotReleaseRequest.tank == a.tank,
                                        DepotReleaseRequest.status.in_(OPEN_STATES)).first():
        return _api_fail(409, "open request exists", key=key, ip=ip, endpoint=ep,
                         errors={"tank": "כבר יש בקשה פתוחה לנכס הזה — היא בטיפול המשרד"})
    if a.status == READY_STATUS:
        return _api_fail(409, "already ready for pickup", key=key, ip=ip, endpoint=ep,
                         errors={"tank": "הנכס כבר הוכן לאיסוף — לביטול פנו למשרד"})
    if a.status != "הכנה לשחרור":
        return _api_fail(409, "no open release", key=key, ip=ip, endpoint=ep,
                         errors={"tank": "אין לנכס הזה שחרור פתוח לביטול"})
    row = DepotReleaseRequest(client_id=client.id, submitted_by_user_id=None,
                              visit_id=a.visit_id, tank=a.tank, action="cancel",
                              requested_date=None, requested_date_to=None,
                              carrier=str(d.get("carrier") or "").strip()[:200] or None,
                              notes=str(d.get("notes") or "").strip()[:400] or None,
                              source="api", api_key_id=key.id)
    db.session.add(row)
    db.session.commit()
    try:
        _notify_release(row, client, a)
    except Exception as exc:
        current_app.logger.error("api release-cancel office notification failed: %s", exc)
    api_log(key, ip, ep, 201, rows=1, note=row.tank)
    return jsonify(id=row.id, tank=row.tank, status=row.status,
                   status_text=REQ_STATUS_HEB.get(("cancel", row.status), row.status)), 201
