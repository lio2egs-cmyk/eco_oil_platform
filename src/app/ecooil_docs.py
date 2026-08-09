# -*- coding: utf-8 -*-
""""המסמכים שלי" — Eco-Oil customer documents API.

Scoping (Limor's ruling 2026-07-13): an account sees rows where THEY are the
billed party (חיוב); an end-customer login (on request) sees rows where they
are the לקוח (source). Mode picked automatically: billed rows exist → billed
view; otherwise source view. Downloads are served as short-lived presigned B2
URLs — the bucket stays private.
"""
import os
import re
from datetime import datetime
from flask import Blueprint, Response, current_app, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from sqlalchemy import and_, func, or_

from .db import db, Client, User, EcoOilUnloadEvent

ecooil_docs = Blueprint("ecooil_docs", __name__, url_prefix="/eco-oil")

PRESIGN_SECONDS = 300

# doc_status values that withhold the filed documents from the customer
# (Limor's ריכוז column "הערות למערכת פורטל", 30/07/2026):
# awaiting_declaration → orange legal notice + declaration button;
# unpublished → nothing shown, no explanation.
WITHHELD_STATUSES = {"awaiting_declaration", "unpublished"}

# תפקיד "הצהרות בלבד" (לימור 05/08) — לקוח עקיף שרואה רק הצהרה+הסכמה,
# לעולם לא את אזור המסמכים (אישורי פריקה / טופסי מלווה).
DECLARATION_ONLY_ROLE = "eco_oil_declaration_only"

# הסריקה החתומה (לימור 09/08): מתקבלת גם כצילום טלפון — הרבה יצרנים מצלמים
# את הדף החתום במקום לסרוק. לימור שופטת קריאוּת ברגע האישור הסופי.
MAX_SCAN_BYTES = 15 * 1024 * 1024
ALLOWED_SCAN_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def _read_scan_upload():
    """קובץ הסריקה מהבקשה → (bytes, name, mime) או (None, הודעת שגיאה בעברית, None)."""
    f = request.files.get("scan")
    if f is None or not f.filename:
        return None, "לא צורף קובץ", None
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_SCAN_EXT:
        return None, "סוג הקובץ לא נתמך — אפשר PDF או תמונה (צילום)", None
    data = f.read()
    if len(data) > MAX_SCAN_BYTES:
        return None, "הקובץ גדול מדי (עד 15MB)", None
    if not data:
        return None, "הקובץ ריק", None
    return data, f.filename[:200], (f.mimetype or "application/octet-stream")[:60]


def _scan_response(d):
    """הסריקה השמורה כתשובת הורדה/צפייה."""
    return Response(
        d.signed_scan_data,
        mimetype=d.signed_scan_mime or "application/octet-stream",
        headers={"Content-Disposition":
                 f"inline; filename=signed_declaration_{d.id}"
                 + os.path.splitext(d.signed_scan_filename or "")[1].lower()})


def _decl_in_user_scope(decl_id):
    """הצהרת פורטל בהיקף החברות של המשתמש המחובר — או None.
    זהה להיקף של my-declaration-docs (כולל תפקיד "הצהרות בלבד" ורב-חברות)."""
    from .db import ProducerDeclaration
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return None
    allowed = user.allowed_client_ids()
    if not allowed:
        return None
    d = db.session.get(ProducerDeclaration, decl_id)
    if d is None or d.submitted_by_user_id is None or d.client_id not in allowed:
        return None
    return d


def _client_for_request():
    """The client whose documents this request may see.

    Admin: any client via ?client_id (preview). Customer: their primary client,
    or — for multi-company users (Limor 02/08) — any client from their
    allowed_client_ids() via ?client_id (the portal's company switcher).
    A client_id outside the allowed set falls back to the primary, never leaks."""
    claims = get_jwt()
    client_id = claims.get("client_id")
    requested = request.args.get("client_id")
    if claims.get("role") == "admin":
        if requested:
            client_id = int(requested)
    elif requested and requested.isdigit():
        user = db.session.get(User, int(get_jwt_identity()))
        if user and int(requested) in user.allowed_client_ids():
            client_id = int(requested)
    return db.session.get(Client, client_id) if client_id else None


def _companies_for_user(claims):
    """[{id, name}] the logged-in customer may switch between (empty for admin)."""
    if claims.get("role") == "admin":
        return []
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return []
    ids = user.allowed_client_ids()
    if len(ids) < 2:
        return []
    clients = {c.id: c for c in Client.query.filter(Client.id.in_(ids)).all()}
    return [{"id": i, "name": clients[i].name} for i in ids if i in clients]


def _norm_name(s):
    """Deterministic name normalization — the same recipe as the office
    matcher's norm(): quotes/dashes/underscores out, בע"מ out, punctuation
    out, spaces collapsed. Equality after this is exact, never fuzzy."""
    if not s:
        return ""
    s = str(s)
    s = s.replace('"', "").replace("'", "").replace("_", " ").replace("-", " ")
    s = re.sub(r"בע\s*מ", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _billed_core(billed):
    """Billed name without a parenthetical customer suffix: 'X (customer)' → X."""
    if not billed:
        return ""
    return re.sub(r"\s*\(.*\)\s*$", "", str(billed)).strip()


def _client_name_map():
    """norm(name) → client_id over every Eco-Oil client's name + aliases.
    This is how a filing folder (or a billed spelling) is recognized as a
    registered company — registration is what activates the folder anchor."""
    m = {}
    for c in Client.query.filter(Client.division == "eco_oil").all():
        for n in c.billed_names():
            key = _norm_name(n)
            if key:
                m.setdefault(key, c.id)
    return m


def _resolve_folder(chain, name_map):
    """filed_owner chain ('top / sub / …') → client_id or None.
    Deepest segment wins: umbrella folders (גדות_כולל, טמבור_אתרים) hold one
    sub-folder per real entity, so the entity folder outranks its parent."""
    for seg in reversed([p.strip() for p in (chain or "").split(" / ") if p.strip()]):
        cid = name_map.get(_norm_name(seg))
        if cid is not None:
            return cid
    return None


def _folder_partition(client):
    """Distinct filed_owner values split into (mine, other-client's).
    Values resolving to NO registered company are neutral — the billed
    fallback governs those rows (Limor's option-A ruling, 06/08/2026)."""
    name_map = _client_name_map()
    mine, other = [], []
    vals = [v for (v,) in db.session.query(EcoOilUnloadEvent.filed_owner)
            .filter(EcoOilUnloadEvent.filed_owner.isnot(None)).distinct().all()]
    for v in vals:
        cid = _resolve_folder(v, name_map)
        if cid == client.id:
            mine.append(v)
        elif cid is not None:
            other.append(v)
    return mine, other


def _scoped_query(client):
    """Visibility ruling (Limor 06/08/2026, after the Idan/Mikush incident):
    THE FILING FOLDER of the certificate is the anchor. A row whose file is
    filed in a folder recognized as ANOTHER registered company is theirs —
    never shown here, even if the billed column still says otherwise.
    Fallback (option A): a row with no file, or with a folder no registered
    company owns, is scoped by billed name + billing_aliases as before
    (parenthetical billed 'X (customer)' belongs to X, rule 21/07)."""
    names = client.billed_names()
    billed_match = or_(
        EcoOilUnloadEvent.billed_to.in_(names),
        *[EcoOilUnloadEvent.billed_to.like(n + " (%") for n in names],
    )
    mine, other = _folder_partition(client)
    # NOT IN evaluates to NULL for NULL filed_owner — the is_(None) arm keeps
    # file-less rows inside the billed fallback.
    folder_neutral = EcoOilUnloadEvent.filed_owner.is_(None)
    if other:
        folder_neutral = or_(folder_neutral,
                             EcoOilUnloadEvent.filed_owner.notin_(other))
    conds = [and_(billed_match, folder_neutral)]
    if mine:
        conds.append(EcoOilUnloadEvent.filed_owner.in_(mine))
    scoped = EcoOilUnloadEvent.query.filter(or_(*conds))
    if db.session.query(scoped.exists()).scalar():
        return scoped, "billed"
    return (EcoOilUnloadEvent.query.filter(EcoOilUnloadEvent.customer.in_(names)),
            "source")


@ecooil_docs.route("/admin/billed-count", methods=["GET"])
@jwt_required()
def billed_count():
    """Admin screen helper: how many unload rows a billed-name spelling (or a
    whole client incl. aliases) matches — catches spelling mistakes instantly."""
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "admin only"}), 403
    name = (request.args.get("name") or "").strip()
    if name:
        cnt = EcoOilUnloadEvent.query.filter(or_(
            EcoOilUnloadEvent.billed_to == name,
            EcoOilUnloadEvent.billed_to.like(name + " (%"))).count()
        # folder matches too — a spelling may exist only as a filing folder
        nkey = _norm_name(name)
        vals = [v for (v,) in db.session.query(EcoOilUnloadEvent.filed_owner)
                .filter(EcoOilUnloadEvent.filed_owner.isnot(None)).distinct().all()]
        owned = [v for v in vals if any(
            _norm_name(seg) == nkey
            for seg in v.split(" / ") if seg.strip())]
        folder_cnt = (EcoOilUnloadEvent.query
                      .filter(EcoOilUnloadEvent.filed_owner.in_(owned)).count()
                      if owned else 0)
        return jsonify({"name": name, "count": cnt, "folder_count": folder_cnt})
    cid = request.args.get("client_id")
    if cid:
        client = db.session.get(Client, int(cid))
        if client is None:
            return jsonify({"error": "client not found"}), 404
        q, mode = _scoped_query(client)
        return jsonify({"client_id": client.id, "count": q.count(), "mode": mode})
    return jsonify({"error": "name or client_id required"}), 400


@ecooil_docs.route("/admin/filing-discrepancies", methods=["GET"])
@jwt_required()
def filing_discrepancies():
    """Limor's safety net (approved 06/08/2026 with the folder-anchor ruling):
    every row where the filing folder and the billed column DISAGREE about a
    registered company, grouped so the list stays readable. Three kinds:
      conflict            — folder belongs to company B, billed says company A
                            (the Idan/Mikush case; the portal follows B).
      pulled_by_folder    — folder belongs to a registered company, billed names
                            someone unregistered; the folder pulls the row in.
      unrecognized_folder — billed belongs to a registered company but the
                            folder spelling is unknown → the folder shield is
                            NOT active for these rows (fix: add the folder
                            name as an alias on the company card)."""
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "admin only"}), 403
    name_map = _client_name_map()
    client_names = {c.id: c.name for c in Client.query.all()}

    rows = (EcoOilUnloadEvent.query
            .filter(EcoOilUnloadEvent.filed_owner.isnot(None))
            .order_by(EcoOilUnloadEvent.event_date.desc())
            .all())

    folder_cache, billed_cache = {}, {}
    groups = {}
    for r in rows:
        fo = r.filed_owner
        if fo not in folder_cache:
            folder_cache[fo] = _resolve_folder(fo, name_map)
        b = r.billed_to or ""
        if b not in billed_cache:
            billed_cache[b] = name_map.get(_norm_name(_billed_core(b)))
        f_cid, b_cid = folder_cache[fo], billed_cache[b]

        if f_cid is not None and b_cid is not None and f_cid != b_cid:
            kind = "conflict"
        elif f_cid is not None and b_cid is None and b.strip():
            kind = "pulled_by_folder"
        elif f_cid is None and b_cid is not None:
            kind = "unrecognized_folder"
        else:
            continue

        key = (kind, b, fo)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "kind": kind, "billed_to": b, "filed_owner": fo,
                "folder_client": client_names.get(f_cid),
                "billed_client": client_names.get(b_cid),
                "count": 0, "latest_date": None, "sample": None,
            }
        g["count"] += 1
        d = r.event_date.strftime("%d/%m/%Y") if r.event_date else ""
        if g["latest_date"] is None:      # rows arrive newest-first
            g["latest_date"] = d
            g["sample"] = {"date": d, "code": r.code, "customer": r.customer,
                           "transporter": r.transporter}

    out = sorted(groups.values(),
                 key=lambda g: ({"conflict": 0, "pulled_by_folder": 1,
                                 "unrecognized_folder": 2}[g["kind"]], -g["count"]))
    counts = {}
    for g in out:
        counts[g["kind"]] = counts.get(g["kind"], 0) + g["count"]
    return jsonify({"groups": out, "row_counts": counts})


def _decl_dict(d, clients, users):
    """הצהרת יצרן כמילון מלא — משרת גם את מסך הניהול וגם את מסמך-החתימה."""
    return {
        "id": d.id,
        "submitted_at": d.issued_at.isoformat() if d.issued_at else None,
        "status": d.status,
        "is_active": d.is_active,
        "client_id": d.client_id,
        "client_name": clients.get(d.client_id, f"חברה #{d.client_id}"),
        "submitted_by": users.get(d.submitted_by_user_id, "?"),
        # פרטי יצרן הפסולת
        "producer_name": d.producer_name,
        "address": d.client_address,
        "business_id": d.business_id,
        "permit_number": d.permit_number,
        "ceo_name": d.ceo_name,
        "producer_email": d.client_email,
        "producer_size": d.producer_size,
        # פרטי הזרם — בחירות הלקוח
        "material_name": d.material_name,
        "waste_stream_number": d.waste_stream_number,
        "production_facility": d.production_facility,
        "quantity": d.annual_quantity_text,
        "packaging": d.packaging_type,
        "treatment_type": d.treatment_facility_type,
        "pollutant_type": d.pollutant_type,
        "concentration_range": d.concentration_range,
        # ערכים שנגזרו בשרת לפי הזרם
        "characteristic": d.waste_main_characteristic,
        "y_code": d.basel_y_code,
        "annex8": d.basel_annexviii_code,
        "catalog": d.european_catalog_code,
        "h_code": d.basel_h_code,
        "un_group": d.un_risk_group,
        "r_code": d.basel_r_code,
        "d_code": d.basel_d_code,
        # תוקף
        "valid_from": d.valid_from.strftime("%d/%m/%Y") if d.valid_from else None,
        "valid_until": d.valid_until.strftime("%d/%m/%Y") if d.valid_until else None,
        "notes": d.notes,
        "fix_note": d.fix_note,
        # הסריקה החתומה + האישור הסופי (09/08)
        "has_signed_scan": bool(d.signed_scan_at),
        "signed_scan_at": d.signed_scan_at.isoformat() if d.signed_scan_at else None,
        "signed_scan_source": d.signed_scan_source,
        "signed_scan_filename": d.signed_scan_filename,
        "approved_at": d.approved_at.isoformat() if d.approved_at else None,
    }


@ecooil_docs.route("/admin/producer-declarations", methods=["GET"])
@jwt_required()
def admin_producer_declarations():
    """מסך הניהול — הצהרות היצרן שהוגשו דרך הפורטל, החדשות ראשונות.
    רק הגשות פורטל (submitted_by_user_id מלא)."""
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "admin only"}), 403
    from .db import ProducerDeclaration

    decls = (ProducerDeclaration.query
             .filter(ProducerDeclaration.submitted_by_user_id.isnot(None))
             .order_by(ProducerDeclaration.issued_at.desc(),
                       ProducerDeclaration.id.desc())
             .limit(500).all())

    user_ids = {d.submitted_by_user_id for d in decls}
    users = {u.id: u.email for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    clients = {c.id: c.name for c in Client.query.all()}

    return jsonify({"declarations": [_decl_dict(d, clients, users) for d in decls]})


@ecooil_docs.route("/admin/producer-declarations/<int:decl_id>", methods=["PATCH"])
@jwt_required()
def admin_release_declaration(decl_id):
    """שמירת מסמך ההצהרה לתא הלקוח (לימור 03/08) — ורק בלחיצה שלה, אחרי בדיקה.

    action=release: הוגשה → נשמרה לתא הלקוח (הלקוח רואה ומוריד לחתימה).
    action=unrelease: ביטול — חוזרת ל"הוגשה" ונעלמת מתא הלקוח."""
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "admin only"}), 403
    from .db import ProducerDeclaration

    d = db.session.get(ProducerDeclaration, decl_id)
    if d is None or d.submitted_by_user_id is None:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    email_sent = None
    if action == "release":
        if d.status != "submitted":
            return jsonify({"error": f"אי אפשר לשחרר הצהרה במעמד '{d.status}'"}), 409
        d.status = "released"
        # מייל אוטומטי למגיש (נוסח אושר ע"י לימור 03/08) — כשל בשליחה לא מפיל
        email_sent = False
        try:
            email_sent = _notify_customer_declaration_released(d)
        except Exception as exc:
            current_app.logger.error("release notification failed: %s", exc)
    elif action == "unrelease":
        if d.status != "released":
            return jsonify({"error": f"אי אפשר לבטל שיתוף במעמד '{d.status}'"}), 409
        d.status = "submitted"
    elif action == "return_fix":
        # החזרה לתיקון (לימור 03/08) — הכלי המרכזי: הערות מה לתקן, הטופס
        # נפתח ללקוח ממולא מראש, והגשה מחודשת מחליפה את הישנה.
        if d.status not in ("submitted", "released"):
            return jsonify({"error": f"אי אפשר להחזיר לתיקון במעמד '{d.status}'"}), 409
        reason = (body.get("reason") or "").strip()
        if not reason:
            return jsonify({"error": "חובה לרשום מה דורש תיקון"}), 400
        d.status = "needs_fix"
        d.fix_note = reason
    elif action == "cancel_fix":
        if d.status != "needs_fix":
            return jsonify({"error": f"אי אפשר לבטל החזרה במעמד '{d.status}'"}), 409
        d.status = "submitted"
        d.fix_note = None
    elif action == "reject":
        # פסילה — כלי צדדי (כפילות/ניסיון/ביטול); נעלמת מתא הלקוח, נשארת בתיעוד.
        if d.status not in ("submitted", "released", "needs_fix"):
            return jsonify({"error": f"אי אפשר לפסול הצהרה במעמד '{d.status}'"}), 409
        d.status = "rejected"
        reason = (body.get("reason") or "").strip()
        if reason:
            stamp = f"נפסלה: {reason}"
            d.notes = f"{d.notes}\n{stamp}" if d.notes else stamp
    elif action == "unreject":
        if d.status != "rejected":
            return jsonify({"error": f"אי אפשר להחזיר הצהרה במעמד '{d.status}'"}), 409
        d.status = "submitted"
    elif action == "approve":
        # אישור סופי (לימור 09/08) — השער: רק אחרי שהסריקה החתומה+חותמת
        # צורפה ולימור בדקה אותה (כולל קריאוּת של צילום טלפון). מכאן ההצהרה
        # פעילה; הרגע הזה הוא הטריגר העתידי להזנה האוטומטית למסד.
        if d.status != "released":
            return jsonify({"error": f"אי אפשר לאשר סופית במעמד '{d.status}'"}), 409
        if not d.signed_scan_data:
            return jsonify({"error": "אין עדיין סריקה חתומה — האישור הסופי מותנה בצירוף המסמך החתום"}), 409
        d.status = "approved"
        d.approved_at = datetime.utcnow()
        d.is_active = True
    elif action == "unapprove":
        if d.status != "approved":
            return jsonify({"error": f"אי אפשר לבטל אישור במעמד '{d.status}'"}), 409
        d.status = "released"
        d.approved_at = None
        d.is_active = False
    else:
        return jsonify({"error": "action must be release/unrelease/return_fix/cancel_fix/reject/unreject/approve/unapprove"}), 400
    db.session.commit()
    resp = {"id": d.id, "status": d.status}
    if email_sent is not None:
        resp["email_sent"] = email_sent
    return jsonify(resp)


def _notify_customer_declaration_released(d):
    """מייל למגיש ההצהרה כשלימור מאשרת נוסח ושומרת לתא הלקוח.
    הנוסח אושר על ידה 03/08/2026 — אין לשנות בלי אישורה."""
    from .mailer import send_office_email

    submitter = db.session.get(User, d.submitted_by_user_id) if d.submitted_by_user_id else None
    if submitter is None or not submitter.email:
        return False
    portal_url = "https://portal.eco-oil.co.il"
    biz = (d.producer_name or "").strip()
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p>שלום,</p>
<p>הצהרת היצרן של <b>{biz}</b> נבדקה ואושרה על ידי אקו-אויל.<br>
המסמך ממתין לכם בפורטל הלקוחות — יש להוריד או להדפיס אותו, להחתים בחתימה
ובחותמת של יצרן הפסולת, ולהחזיר לאקו-אויל.</p>
<p style="margin:22px 0;">
<a href="{portal_url}" style="background:#5B9E96;color:#fff;text-decoration:none;
padding:12px 28px;border-radius:8px;font-weight:bold;">כניסה לפורטל</a></p>
<p>בברכה,<br>פורטל הלקוחות של אקו-אויל</p></div>"""
    return send_office_email(
        subject=f"מסמך הצהרת יצרן ממתין לחתימתכם — {biz}",
        html=html, to=submitter.email)


@ecooil_docs.route("/portal/my-declaration-docs", methods=["GET"])
@jwt_required()
def my_declaration_docs():
    """תא הלקוח — מסמכים ששוחררו לחתימה (released) + הצהרות שהוחזרו לתיקון
    (needs_fix, עם הערות לימור). ההיקף: החברות המותרות למשתמש (כולל
    רב-חברות). מנהלת משתמשת בנקודת הקצה הניהולית — כאן רשימה ריקה."""
    from .db import ProducerDeclaration

    claims = get_jwt()
    if claims.get("role") == "admin":
        return jsonify({"declarations": []})
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return jsonify({"error": "no user"}), 403
    allowed = user.allowed_client_ids()
    if not allowed:
        return jsonify({"declarations": []})

    decls = (ProducerDeclaration.query
             .filter(ProducerDeclaration.client_id.in_(allowed),
                     ProducerDeclaration.status.in_(("released", "needs_fix", "approved")),
                     ProducerDeclaration.submitted_by_user_id.isnot(None))
             .order_by(ProducerDeclaration.issued_at.desc(),
                       ProducerDeclaration.id.desc())
             .limit(200).all())

    user_ids = {d.submitted_by_user_id for d in decls}
    users = {u.id: u.email for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    clients = {c.id: c.name for c in Client.query.filter(Client.id.in_(allowed)).all()}

    return jsonify({"declarations": [_decl_dict(d, clients, users) for d in decls]})


@ecooil_docs.route("/portal/my-declaration-docs/<int:decl_id>/signed-scan",
                   methods=["POST"])
@jwt_required()
def upload_signed_scan(decl_id):
    """הלקוח מעלה את המסמך החתום — סריקה או צילום טלפון (לימור 09/08).

    מותר רק במעמד "בתא הלקוח" (released); העלאה חוזרת מחליפה את הקודמת עד
    האישור הסופי. אחרי האישור — נעול (לימור מבטלת אישור אם צריך להחליף)."""
    if get_jwt().get("role") == "admin":
        return jsonify({"error": "העלאת לקוח — מנהלת מצרפת דרך מסך הניהול"}), 403
    d = _decl_in_user_scope(decl_id)
    if d is None:
        return jsonify({"error": "not found"}), 404
    if d.status != "released":
        return jsonify({"error": "אפשר לצרף מסמך חתום רק להצהרה שאושר נוסחה וממתינה לחתימה"}), 409
    data, name_or_err, mime = _read_scan_upload()
    if data is None:
        return jsonify({"error": name_or_err}), 400
    d.signed_scan_data = data
    d.signed_scan_filename = name_or_err
    d.signed_scan_mime = mime
    d.signed_scan_at = datetime.utcnow()
    d.signed_scan_source = "customer"
    db.session.commit()
    try:
        _notify_office_scan_uploaded(d)
    except Exception as exc:
        current_app.logger.error("scan-upload office notification failed: %s", exc)
    return jsonify({"id": d.id, "has_signed_scan": True})


@ecooil_docs.route("/portal/my-declaration-docs/<int:decl_id>/signed-scan",
                   methods=["GET"])
@jwt_required()
def view_own_signed_scan(decl_id):
    """הלקוח צופה במסמך החתום שהעלה (גם אחרי האישור הסופי)."""
    if get_jwt().get("role") == "admin":
        return jsonify({"error": "admin uses the admin endpoint"}), 403
    d = _decl_in_user_scope(decl_id)
    if d is None or not d.signed_scan_data:
        return jsonify({"error": "not found"}), 404
    return _scan_response(d)


@ecooil_docs.route("/admin/producer-declarations/<int:decl_id>/signed-scan",
                   methods=["POST"])
@jwt_required()
def admin_upload_signed_scan(decl_id):
    """לימור מצרפת סריקה/צילום שקיבלה מחוץ לפורטל (ווטסאפ/מייל) — תיוק,
    לא מילוי בשם הלקוח; עיקרון "המילוי תמיד של הלקוח" נשמר."""
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "admin only"}), 403
    from .db import ProducerDeclaration
    d = db.session.get(ProducerDeclaration, decl_id)
    if d is None or d.submitted_by_user_id is None:
        return jsonify({"error": "not found"}), 404
    if d.status != "released":
        return jsonify({"error": "אפשר לצרף מסמך חתום רק להצהרה במעמד 'בתא הלקוח'"}), 409
    data, name_or_err, mime = _read_scan_upload()
    if data is None:
        return jsonify({"error": name_or_err}), 400
    d.signed_scan_data = data
    d.signed_scan_filename = name_or_err
    d.signed_scan_mime = mime
    d.signed_scan_at = datetime.utcnow()
    d.signed_scan_source = "admin"
    db.session.commit()
    return jsonify({"id": d.id, "has_signed_scan": True})


@ecooil_docs.route("/admin/producer-declarations/<int:decl_id>/signed-scan",
                   methods=["GET"])
@jwt_required()
def admin_view_signed_scan(decl_id):
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "admin only"}), 403
    from .db import ProducerDeclaration
    d = db.session.get(ProducerDeclaration, decl_id)
    if d is None or not d.signed_scan_data:
        return jsonify({"error": "not found"}), 404
    return _scan_response(d)


def _notify_office_scan_uploaded(d):
    """מייל פנימי למשרד כשלקוח מעלה מסמך חתום — כדי שלימור תדע לבדוק ולאשר."""
    from .mailer import send_office_email

    biz = (d.producer_name or "").strip()
    kind = "PDF" if (d.signed_scan_mime or "").endswith("pdf") else "צילום/תמונה"
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p>התקבל מסמך הצהרת יצרן חתום בפורטל.</p>
<table dir="rtl" style="border-collapse:collapse;">
<tr><td style="border:1px solid #999;padding:6px 12px;background:#eef3f2;"><b>העסק</b></td>
<td style="border:1px solid #999;padding:6px 12px;">{biz}</td></tr>
<tr><td style="border:1px solid #999;padding:6px 12px;background:#eef3f2;"><b>זרם</b></td>
<td style="border:1px solid #999;padding:6px 12px;">{d.material_name or ""}</td></tr>
<tr><td style="border:1px solid #999;padding:6px 12px;background:#eef3f2;"><b>סוג הקובץ</b></td>
<td style="border:1px solid #999;padding:6px 12px;">{kind}</td></tr>
</table>
<p>לבדיקה ואישור סופי — מסך הניהול, כרטיס "הצהרות יצרן שהוגשו בפורטל".</p></div>"""
    return send_office_email(
        subject=f"מסמך חתום התקבל בפורטל — {biz}", html=html)


@ecooil_docs.route("/my-documents", methods=["GET"])
@jwt_required()
def my_documents():
    if get_jwt().get("role") == DECLARATION_ONLY_ROLE:
        return jsonify({"error": "declarations only"}), 403
    client = _client_for_request()
    if client is None:
        return jsonify({"error": "no client"}), 403
    q, mode = _scoped_query(client)

    base = q  # facets reflect the full scope, not the current filter
    if request.args.get("year"):
        q = q.filter(EcoOilUnloadEvent.year == int(request.args["year"]))
    if request.args.get("stream"):
        q = q.filter(EcoOilUnloadEvent.stream_norm == request.args["stream"])
    if request.args.get("q"):
        like = f"%{request.args['q'].strip()}%"
        q = q.filter(or_(EcoOilUnloadEvent.customer.ilike(like),
                         EcoOilUnloadEvent.transporter.ilike(like)))

    rows = q.order_by(EcoOilUnloadEvent.event_date.desc(),
                      EcoOilUnloadEvent.id.desc()).limit(5000).all()
    years = [y for (y,) in base.with_entities(EcoOilUnloadEvent.year)
             .distinct().order_by(EcoOilUnloadEvent.year.desc()).all()]
    streams = [s for (s,) in base.with_entities(EcoOilUnloadEvent.stream_norm)
               .distinct().order_by(EcoOilUnloadEvent.stream_norm).all() if s]

    return jsonify({
        "mode": mode,
        "client_name": client.name,
        "client_id": client.id,
        "companies": _companies_for_user(get_jwt()),
        "years": years,
        "streams": streams,
        "rows": [{
            "id": r.id,
            "date": r.event_date.strftime("%d/%m/%Y") if r.event_date else "",
            "customer": r.customer,
            "transporter": r.transporter,
            "stream": r.stream,
            "stream_norm": r.stream_norm,
            "tons": r.declared_tons,
            "code": r.code,
            # Sanction (Limor 29/07): she ALWAYS produces+files the documents and
            # withholds only the SENDING — so a filed PDF must never override the
            # sanction. Withheld statuses hide BOTH downloads.
            "has_pdf": bool(r.pdf_key) and r.doc_status not in WITHHELD_STATUSES,
            "has_manifest": bool(r.manifest_key) and r.doc_status not in WITHHELD_STATUSES,
            "doc_status": r.doc_status,
        } for r in rows],
    })


@ecooil_docs.route("/my-documents/<int:event_id>/download", methods=["GET"])
@jwt_required()
def download(event_id):
    if get_jwt().get("role") == DECLARATION_ONLY_ROLE:
        return jsonify({"error": "declarations only"}), 403
    client = _client_for_request()
    if client is None:
        return jsonify({"error": "no client"}), 403
    q, _mode = _scoped_query(client)
    ev = q.filter(EcoOilUnloadEvent.id == event_id).first()
    if ev is None:
        return jsonify({"error": "not found"}), 404
    # Sanction enforcement at the API level (not just the UI): a withheld row
    # serves NOTHING, even though the files are filed.
    if ev.doc_status in WITHHELD_STATUSES:
        return jsonify({"error": "withheld"}), 403
    # ?doc=manifest serves the signed טופס מלווה scan; default = the certificate
    key = ev.manifest_key if request.args.get("doc") == "manifest" else ev.pdf_key
    if not key:
        return jsonify({"error": "no file"}), 404
    for var in ("B2_KEY_ID", "B2_APP_KEY", "B2_BUCKET_CERTS", "B2_ENDPOINT"):
        if not os.environ.get(var):
            return jsonify({"error": "storage not configured"}), 503
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['B2_ENDPOINT']}",
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APP_KEY"],
        config=Config(signature_version="s3v4"),
    )
    from urllib.parse import quote
    fname = quote(key.rsplit("/", 1)[-1])
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["B2_BUCKET_CERTS"], "Key": key,
                "ResponseContentDisposition": f"attachment; filename*=UTF-8''{fname}"},
        ExpiresIn=PRESIGN_SECONDS,
    )
    return jsonify({"url": url})
