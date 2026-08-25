# -*- coding: utf-8 -*-
"""פורטל הדיפו — צד הלקוח, שלב 1 (לימור 06/08/2026): טופס המידע המקדים.

המחליף של המייל המקדים. הלקוח מגיש בפורטל → הענן שומר (pending) → הגשר של
יעל מושך בכל סבב תקשורת (אותו צינור כמו אירועי המסופונים), פותח שורת
"בדרך להיכנס" מלאה בקובץ החי (חוק 53), מוריד את ה-MSDS לתיוק, ומאשר קליטה
(posted) — ואז קובץ ה-MSDS נמחק מהענן.

רשימות הבחירה (חומרים/מובילים) נדחפות ע"י הגשר — מקור האמת נשאר במשרד
(המסד + CARRIER_OPTIONS, חוק 47ג); הענן רק מציג.
"""
import json
import re
from datetime import date, datetime

from flask import Blueprint, Response, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from .db import db, Client, DepotFormOptions, DepotPreArrival, User
from .field import bridge_required

depot_portal = Blueprint("depot_portal", __name__, url_prefix="/depot/portal")

PURPOSES = ("שטיפה + אחסנה", "אחסנה בלבד", "שטיפה בלבד", "אחר")
PHOTO_SETS = ("2 פנים / 4 חוץ", "סט מלא (הכל)")
MAX_MSDS_BYTES = 10 * 1024 * 1024

# ISO-6346: ערכי אותיות מדלגים על כפולות 11
_ISO_LETTERS = {c: v for c, v in zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    [10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28,
     29, 30, 31, 32, 34, 35, 36, 37, 38])}


def iso6346_ok(tank):
    """אימות ספרת ביקורת — אותו חישוב כמו בטופס המשרד ובמסופונים."""
    t = (tank or "").upper().replace(" ", "")
    if not re.fullmatch(r"[A-Z]{4}\d{7}", t):
        return False
    s = sum((_ISO_LETTERS[ch] if i < 4 else int(ch)) * (2 ** i)
            for i, ch in enumerate(t[:10]))
    return (s % 11) % 10 == int(t[10])


def _depot_client_for_request():
    claims = get_jwt()
    if claims.get("role") != "eco_depot_client":
        return None
    client = db.session.get(Client, claims.get("client_id") or 0)
    if client is None or client.division != "eco_depot":
        return None
    return client


# ------------------------------------------------------------ customer side
@depot_portal.route("/form-options", methods=["GET"])
@jwt_required()
def form_options():
    if _depot_client_for_request() is None:
        # תצוגת מנהלת (לימור 24/08): הצוות פותח את הטופס בתיבה מתוך מסך
        # הניהול ורואה אותו עם הרשימות האמיתיות. קריאה בלבד — שליחה נשארת
        # חסומה לצוות בצד השרת (submit_prearrival בודק לקוח דיפו בלבד).
        if get_jwt().get("role") not in ("admin", "depot_admin"):
            return jsonify(error="depot customers only"), 403
    row = DepotFormOptions.query.first()
    data = {}
    if row and row.data:
        try:
            data = json.loads(row.data)
        except ValueError:
            data = {}
    return jsonify(materials=data.get("materials") or [],
                   carriers=data.get("carriers") or [])


@depot_portal.route("/prearrivals", methods=["POST"])
@jwt_required()
def submit_prearrival():
    """הגשת טופס מידע מקדים (multipart: שדות + קובץ MSDS רשות).
    כל שדות החובה נאכפים גם כאן — שורה נולדת שלמה (חוק 53/54)."""
    client = _depot_client_for_request()
    if client is None:
        return jsonify(error="depot customers only"), 403

    f = request.form
    errors = {}

    tank = (f.get("tank_number") or "").upper().replace(" ", "").strip()
    if not tank:
        errors["tank_number"] = "חסר מספר איזוטנק"
    elif not iso6346_ok(tank):
        errors["tank_number"] = "מספר האיזוטנק לא עובר את בדיקת ספרת הביקורת — בדקו את ההקלדה"

    material = (f.get("material") or "").strip()
    if not material:
        errors["material"] = "חסר החומר האחרון"
    un_number = (f.get("un_number") or "").strip()
    if not un_number:
        errors["un_number"] = "חסר מספר או\"ם"
    hazard_class = (f.get("hazard_class") or "").strip()
    if not hazard_class:
        errors["hazard_class"] = "חסר Class סכנה"

    carrier = (f.get("carrier") or "").strip()
    carrier_new = (f.get("carrier_new") or "").strip()
    if not carrier and not carrier_new:
        errors["carrier"] = "בוחרים מוביל מהרשימה או מקלידים מוביל חדש"

    purpose = (f.get("purpose") or "").strip()
    purpose_other = (f.get("purpose_other") or "").strip()
    if purpose not in PURPOSES:
        errors["purpose"] = "חסרה מטרת הכניסה"
    elif purpose == "אחר" and not purpose_other:
        errors["purpose"] = "בחרתם \"אחר\" — נא לפרט את מטרת הכניסה"

    expected = None
    if (f.get("expected_date") or "").strip():
        try:
            expected = date.fromisoformat(f["expected_date"].strip())
        except ValueError:
            errors["expected_date"] = "תאריך הגעה לא תקין"

    svc_photos = (f.get("svc_photos") or "").strip()
    if f.get("svc_photos_on") == "1" and svc_photos not in PHOTO_SETS:
        errors["svc_photos"] = "סימנתם סט תמונות — נא לבחור את סוג הסט"
    svc_repairs = (f.get("svc_repairs") or "").strip()
    if f.get("svc_repairs_on") == "1" and not svc_repairs:
        errors["svc_repairs"] = "סימנתם תיקונים — נא לפרט מה לתקן"

    msds = request.files.get("msds")
    msds_bytes = msds_name = msds_mime = None
    if msds and msds.filename:
        msds_bytes = msds.read()
        if len(msds_bytes) > MAX_MSDS_BYTES:
            errors["msds"] = "קובץ ה-MSDS גדול מדי (עד 10MB)"
        msds_name = msds.filename[:200]
        msds_mime = (msds.mimetype or "application/pdf")[:60]

    if errors:
        return jsonify(errors=errors), 400

    row = DepotPreArrival(
        client_id=client.id,
        submitted_by_user_id=int(get_jwt_identity()),
        tank_number=tank,
        material=material[:200], un_number=un_number[:20],
        hazard_class=hazard_class[:20],
        carrier=carrier[:200] or None, carrier_new=carrier_new[:200] or None,
        purpose=purpose, purpose_other=purpose_other[:200] or None,
        expected_date=expected,
        svc_dry=f.get("svc_dry") == "1",
        svc_vacuum=f.get("svc_vacuum") == "1",
        svc_photos=svc_photos or None,
        svc_repairs=svc_repairs[:400] or None,
        internal_ref=(f.get("internal_ref") or "").strip()[:100] or None,
        emergency_phone=(f.get("emergency_phone") or "").strip()[:60] or None,
        notes=(f.get("notes") or "").strip()[:400] or None,
        msds_filename=msds_name, msds_mime=msds_mime,
        msds_size=len(msds_bytes) if msds_bytes else None,
        msds_data=msds_bytes,
    )
    db.session.add(row)
    db.session.commit()

    try:
        _notify_office(row, client)
    except Exception as exc:
        current_app.logger.error("prearrival office notification failed: %s", exc)

    return jsonify(id=row.id, tank_number=row.tank_number), 201


@depot_portal.route("/prearrivals", methods=["GET"])
@jwt_required()
def my_prearrivals():
    """ההגשות של הלקוח המחובר — כדי שיראה שהמידע נקלט (הגרעין של תיק הביקור)."""
    client = _depot_client_for_request()
    if client is None:
        return jsonify(error="depot customers only"), 403
    rows = (DepotPreArrival.query.filter_by(client_id=client.id)
            .order_by(DepotPreArrival.created_at.desc()).limit(50).all())
    heb = {"pending": "נקלט — ממתין לפתיחת שורה במשרד",
           "fetched": "בקליטה במשרד",
           "posted": "נפתחה שורת צפי — הנכס מוכר למערכת",
           "error": "בבירור מול המשרד"}
    return jsonify(prearrivals=[{
        "id": r.id,
        "created_at": r.created_at.isoformat(),
        "tank_number": r.tank_number,
        "material": r.material,
        "purpose": r.purpose if r.purpose != "אחר" else (r.purpose_other or "אחר"),
        "expected_date": r.expected_date.strftime("%d/%m/%Y") if r.expected_date else None,
        "status": heb.get(r.status, r.status),
    } for r in rows])


def _notify_office(row, client):
    """מייל פנימי למשרד הדיפו על כל הגשה — טבלה RTL עם מסגרות (כלל העיצוב)."""
    from .mailer import send_office_email

    def tr(k, v):
        return (f'<tr><td style="border:1px solid #999;padding:6px 10px;'
                f'background:#EDF3F2;font-weight:bold">{k}</td>'
                f'<td style="border:1px solid #999;padding:6px 10px">{v or "—"}</td></tr>')

    services = " · ".join(filter(None, [
        "ייבוש" if row.svc_dry else None,
        "בדיקת ואקום" if row.svc_vacuum else None,
        f"סט תמונות ({row.svc_photos})" if row.svc_photos else None,
        f"תיקונים: {row.svc_repairs}" if row.svc_repairs else None])) or "—"
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif">
<p>התקבל טופס מידע מקדים חדש בפורטל הדיפו — שורת הצפי תיפתח אוטומטית ע"י הגשר.</p>
<table style="border-collapse:collapse">
{tr("לקוח", client.name)}
{tr("מספר איזוטנק", row.tank_number)}
{tr("חומר אחרון", row.material)}
{tr('או"ם / Class', f"{row.un_number} / {row.hazard_class}")}
{tr("מוביל", row.carrier or (row.carrier_new and 'חדש: ' + row.carrier_new))}
{tr("מטרת הכניסה", row.purpose if row.purpose != 'אחר' else row.purpose_other)}
{tr("תאריך הגעה משוער", row.expected_date.strftime('%d/%m/%Y') if row.expected_date else None)}
{tr("שירותים מוזמנים", services)}
{tr("אסמכתא פנימית", row.internal_ref)}
{tr("טלפון חרום", row.emergency_phone)}
{tr("הערות", row.notes)}
{tr("MSDS", row.msds_filename or "לא צורף")}
</table>
<p style="margin-top:14px"><a href="https://depot.eco-oil.co.il/depot-admin"
style="background:#5B9E96;color:#fff;padding:9px 18px;border-radius:8px;
text-decoration:none;font-weight:bold">לצפייה בכל ההגשות — מסך ניהול הדיפו</a></p></div>"""
    send_office_email(subject=f"מידע מקדים חדש — {row.tank_number} ({client.name})",
                      html=html, to="shtifot@eco-oil.co.il")


# ------------------------------------------------------------- bridge side
@depot_portal.route("/bridge/prearrivals", methods=["GET"])
@bridge_required
def bridge_pending():
    # כמו אירועי המסופונים: גם fetched מוגש שוב — טופס שנמשך אבל לא אושר
    # (קובץ נעול / סבב שנפל) חוזר בסבב הבא במקום להיתקע לנצח
    rows = (DepotPreArrival.query.filter(DepotPreArrival.status.in_(("pending", "fetched")))
            .order_by(DepotPreArrival.id).limit(50).all())
    for r in rows:
        r.status = "fetched"
    db.session.commit()
    return jsonify(prearrivals=[{
        "id": r.id, "client_id": r.client_id, "client_name": r.client.name,
        "created_at": r.created_at.isoformat(),
        "tank_number": r.tank_number, "material": r.material,
        "un_number": r.un_number, "hazard_class": r.hazard_class,
        "carrier": r.carrier, "carrier_new": r.carrier_new,
        "purpose": r.purpose, "purpose_other": r.purpose_other,
        "expected_date": r.expected_date.isoformat() if r.expected_date else None,
        "svc_dry": r.svc_dry, "svc_vacuum": r.svc_vacuum,
        "svc_photos": r.svc_photos, "svc_repairs": r.svc_repairs,
        "internal_ref": r.internal_ref, "emergency_phone": r.emergency_phone,
        "notes": r.notes, "has_msds": bool(r.msds_size),
        "msds_filename": r.msds_filename,
    } for r in rows])


@depot_portal.route("/bridge/prearrivals/<int:row_id>/msds", methods=["GET"])
@bridge_required
def bridge_msds(row_id):
    r = db.session.get(DepotPreArrival, row_id)
    if r is None or not r.msds_data:
        return jsonify(error="not found"), 404
    return Response(r.msds_data, mimetype=r.msds_mime or "application/pdf",
                    headers={"Content-Disposition":
                             f"attachment; filename={r.msds_filename or 'msds.pdf'}"})


@depot_portal.route("/bridge/prearrivals/ack", methods=["POST"])
@bridge_required
def bridge_ack():
    """הגשר מאשר: posted (שורת צפי נפתחה) או error. ב-posted קובץ ה-MSDS
    נמחק מהענן (כמו תמונות השטח) — הוא כבר מתויק במשרד."""
    data = request.get_json(silent=True) or {}
    r = db.session.get(DepotPreArrival, int(data.get("id") or 0))
    if r is None:
        return jsonify(error="not found"), 404
    status = data.get("status")
    if status not in ("posted", "error"):
        return jsonify(error="status must be posted/error"), 400
    r.status = status
    r.bridge_note = (data.get("note") or "")[:400] or None
    if status == "posted":
        r.posted_at = datetime.utcnow()
        r.msds_data = None
    db.session.commit()
    return jsonify(ok=True, id=r.id, status=r.status)


@depot_portal.route("/bridge/form-options", methods=["POST"])
@bridge_required
def bridge_form_options():
    data = request.get_json(silent=True) or {}
    materials = data.get("materials")
    carriers = data.get("carriers")
    if not isinstance(materials, list) or not isinstance(carriers, list):
        return jsonify(error="materials + carriers lists required"), 400
    row = DepotFormOptions.query.first()
    if row is None:
        row = DepotFormOptions()
        db.session.add(row)
    row.data = json.dumps({"materials": materials[:3000], "carriers": carriers[:200]},
                          ensure_ascii=False)
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(ok=True, materials=len(materials), carriers=len(carriers))
