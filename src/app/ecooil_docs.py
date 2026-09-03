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

# חסימת מסמכים ברמת החברה (לימור 17/08) — הנוסח שבחרה, מנומס ומפנה
# להנהלת החשבונות. אין לשנות בלי אישורה.
DOCS_BLOCKED_NOTICE = ("לצפייה במסמכים יש לפנות להנהלת החשבונות של אקו-אויל.")

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


def _decl_scope_ids(user, include_indirect=True):
    """מזהי החברות שהצהרותיהן מוצגות למשתמש.

    החברות שלו (ראשית + נוספות), ובנוסף — היצרנים העקיפים שהחברות שלו הן
    "המוביל האחראי" שלהם (Client.parent_client_id). זו החלטה 4 ממאי, שעד
    17/08 מומשה רק לאישורי פריקה דרך שם החיוב ומעולם לא להצהרות: מוביל לא
    ראה את ההצהרות וההסכמות של לקוחותיו העקיפים (מקרה ורידיס/אלביט
    סייקלון). ⚠ הרחבה זו היא לצפייה בלבד — פעולות כתיבה (העלאת המסמך
    החתום) נשארות אצל החברה שההצהרה שלה, ולכן include_indirect=False שם.
    התיוק ב-Z: לא מושפע כלל: הוא נשאר לפי הכלל היציב — אצל היצרן עצמו."""
    return _expand_indirect(user.allowed_client_ids(), include_indirect)


def _expand_indirect(ids, include_indirect=True):
    """רשימת חברות + היצרנים העקיפים שהן המוביל האחראי שלהם."""
    ids = list(ids)
    if not ids or not include_indirect:
        return ids
    for c in Client.query.filter(Client.parent_client_id.in_(ids)).all():
        if c.id not in ids:
            ids.append(c.id)
    return ids


def _decl_in_user_scope(decl_id, include_indirect=True):
    """הצהרת פורטל בהיקף החברות של המשתמש המחובר — או None.
    זהה להיקף של my-declaration-docs (כולל תפקיד "הצהרות בלבד" ורב-חברות)."""
    from .db import ProducerDeclaration
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return None
    allowed = _decl_scope_ids(user, include_indirect)
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


# ── שמות קבצים למסמכי ההצהרה/ההסכמה (לימור 17/08) ────────────────────────
# הכלל שקבעה: השם משקף את המסמך עצמו, לא רק את שם החברה. המבנה —
#   הסכמה_חומצה גדול_גלבוע תעשיות_אתר ספיר_8.26
#   סוג_זרם גודל-יצרן_שם קצר_אתר_חודש.שנה של תחילת התוקף
# הכרעותיה: האתר = שדה "כתובת העסק / מפעל" (ולא "מתקן הייצור", שהוא
# התהליך — לקח אידיאה 13/08); התאריך = תחילת התוקף; והעותקים שהגשר מתייק
# ב-Z: מקבלים את אותו שם בתוספת מספר ההסכמה. שם החברה: 17/08 היו שתי
# המילים הראשונות, ומ-18/08 — שם קצר ידני בכרטיס, ובלעדיו השם המלא (ראי
# _short_company). השם נבנה כאן בשרת בלבד — הפורטל והגשר קוראים אותו
# מוכן, כדי ששני המקומות לא ייפרדו לעולם.
_FS_FORBIDDEN = r'[\\/:*?"<>|]'
_LTD_SUFFIX = re.compile(r'\s*בע\s*["\']?\s*מ\s*$')


def _fs_clean(s, maxlen=None):
    """טקסט חופשי → מקטע בטוח לשם קובץ בחלונות."""
    s = re.sub(_FS_FORBIDDEN, " ", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip(" .")
    if maxlen and len(s) > maxlen:
        cut = s[:maxlen].rsplit(" ", 1)[0]      # לא חותכים באמצע מילה
        s = (cut or s[:maxlen]).strip()
    return s


def _short_name_map():
    """norm(שם חברה) → שם קצר לקבצים, לכל חברה שהוגדר לה אחד."""
    return {_norm_name(c.name): c.file_short_name.strip()
            for c in Client.query.filter(Client.division == "eco_oil",
                                         Client.file_short_name.isnot(None)).all()
            if (c.file_short_name or "").strip()}


def _short_company(name, short_map=None):
    """שם החברה בשם הקובץ (לימור 18/08): שם קצר שהוגדר לה ידנית בכרטיס,
    ואם לא הוגדר — השם המלא בלי בע"מ.

    קודם היו שתי המילים הראשונות, וזה הפיל את "אלביט מערכות סאיקלון"
    ל-"אלביט מערכות" — שם שמתנגש עם "אלביט מערכות כרמיאל", מפעל אחר של
    אותה חברה באותה עיר. חיתוך קשיח בולע בדיוק את המילה המבדילה, ולכן
    ברירת המחדל היא השם המלא, והקיצור הוא החלטה אנושית לכל חברה."""
    base = _LTD_SUFFIX.sub("", _fs_clean(name))
    if short_map:
        chosen = short_map.get(_norm_name(base)) or short_map.get(_norm_name(name))
        if chosen:
            return _fs_clean(chosen, maxlen=40)
    return _fs_clean(base, maxlen=40)


def _site_part(site, company_part):
    """מקטע האתר — ריק כשהאתר כבר מופיע בתוך שם החברה (לימור 18/08:
    "אלביט מערכות כרמיאל" + אתר כרמיאל ≠ כרמיאל פעמיים). ההשוואה על
    הטקסט המנורמל בלבד, בלי ניחושים."""
    s = _fs_clean(site, maxlen=30)
    if not s:
        return ""
    a = " ".join(w for w in _norm_name(s).split() if w != "אתר")
    if a and a in _norm_name(company_part):
        return ""
    return s


def _doc_file_name(d, kind, number=None):
    """שם הקובץ למסמך הצהרה/הסכמה. kind = 'הצהרה' / 'הסכמה'.
    number — מספר ההסכמה; נוסף רק לעותק המתויק ב-Z:, לא להורדה מהפורטל."""
    stream = _fs_clean(" ".join(x for x in (d.material_name, d.producer_size) if x))
    when = f"{d.valid_from.month}.{d.valid_from:%y}" if d.valid_from else ""
    company = _short_company(d.producer_name, _short_name_map())
    parts = [kind, stream, company,
             _site_part(d.client_address, company), when]
    if number:
        parts.append(f"מס {number}")
    return "_".join(p for p in parts if p)


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
        # שם הקובץ להורדה (לימור 17/08) — נבנה בשרת כדי שהפורטל והתיוק ב-Z:
        # ישתמשו באותו שם בדיוק
        "file_name": _doc_file_name(d, "הצהרה"),
        "notes": d.notes,
        "fix_note": d.fix_note,
        "released_at": d.released_at.isoformat() if d.released_at else None,
        # הסריקה החתומה + האישור הסופי (09/08)
        "has_signed_scan": bool(d.signed_scan_at),
        "signed_scan_at": d.signed_scan_at.isoformat() if d.signed_scan_at else None,
        "signed_scan_source": d.signed_scan_source,
        "signed_scan_filename": d.signed_scan_filename,
        "approved_at": d.approved_at.isoformat() if d.approved_at else None,
        # מחוון התיוק (לימור 18/08): הגשר כבר רשם מתי כל מסמך תויק, אבל
        # המידע לא הוצג בשום מקום — ולכן היחיד שידע לספר שמשהו עבד היה
        # היעדר מייל כישלון. עכשיו זה מוצג במסך.
        "scan_filed_at": d.scan_filed_at.isoformat() if d.scan_filed_at else None,
        "scan_file_note": d.scan_file_note,
        # מסמך ההסכמה שהופק מהפורטל (לימור 12/08) — רק מסמכים ממוספרים
        "agreement": next(({"id": a.id, "number": a.number,
                            "filed_at": a.filed_at.isoformat() if a.filed_at else None,
                            "file_note": a.file_note}
                           for a in sorted(d.agreement_documents,
                                           key=lambda a: a.id, reverse=True)
                           if a.number), None),
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
        d.released_at = datetime.utcnow()
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
        d.released_at = None
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
    הנוסח אושר על ידה 12/08/2026 (החליף את נוסח 03/08 — חיזוק "זה לא סוף
    התהליך" אחרי מקרה גלבוע) — אין לשנות בלי אישורה."""
    from .mailer import send_office_email

    submitter = db.session.get(User, d.submitted_by_user_id) if d.submitted_by_user_id else None
    if submitter is None or not submitter.email:
        return False
    portal_url = "https://portal.eco-oil.co.il"
    biz = (d.producer_name or "").strip()
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p>שלום,</p>
<p>הצהרת היצרן של <b>{biz}</b> נבדקה, והנוסח שלה אושר על ידי אקו-אויל.</p>
<p><b>שימו לב — זה עדיין לא סוף התהליך: ההצהרה תיכנס לתוקף רק לאחר
החתימה והאישור הסופי.</b> כדי להשלים, נותרו שלושה צעדים:</p>
<ol style="line-height:1.8;">
<li>היכנסו לפורטל והורידו או הדפיסו את המסמך.</li>
<li>חתמו עליו בחתימה ובחותמת של יצרן הפסולת.</li>
<li>העלו את המסמך החתום בפורטל — אפשר גם צילום ברור מהטלפון.</li>
</ol>
<p>לאחר מכן אקו-אויל תבדוק את המסמך החתום ותאשר סופית — ובכך יושלם התהליך.</p>
<p style="margin:22px 0;">
<a href="{portal_url}" style="background:#5B9E96;color:#fff;text-decoration:none;
padding:12px 28px;border-radius:8px;font-weight:bold;">כניסה לפורטל</a></p>
<p>בברכה,<br>פורטל הלקוחות של אקו-אויל</p></div>"""
    return send_office_email(
        subject=f"מסמך הצהרת יצרן ממתין לחתימתכם — {biz}",
        html=html, to=submitter.email)


def _notify_customer_declaration_edited(d):
    """מייל למגיש אחרי עריכת משרד (לימור 20/08) — מודיע שהנוסח תוקן ושאפשר
    להוריד את הגרסה המעודכנת לחתימה. נשלח רק ביוזמתה, בשאלה אחרי השמירה.
    הנוסח אושר על ידי לימור 20/08/2026 — אין לשנות בלי אישורה."""
    from .mailer import send_office_email

    submitter = db.session.get(User, d.submitted_by_user_id) if d.submitted_by_user_id else None
    if submitter is None or not submitter.email:
        return False
    portal_url = "https://portal.eco-oil.co.il"
    biz = (d.producer_name or "").strip()
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p>שלום,</p>
<p>בהצהרת היצרן של <b>{biz}</b> בוצע תיקון פרטים על ידי משרד אקו-אויל,
והנוסח המעודכן כבר זמין בפורטל.</p>
<p><b>אם הדפסתם או הורדתם עותק קודם — אנא השתמשו מעתה בגרסה המעודכנת:</b></p>
<ol style="line-height:1.8;">
<li>היכנסו לפורטל והורידו או הדפיסו את המסמך המעודכן.</li>
<li>חתמו עליו בחתימה ובחותמת של יצרן הפסולת.</li>
<li>העלו את המסמך החתום בפורטל — אפשר גם צילום ברור מהטלפון.</li>
</ol>
<p style="margin:22px 0;">
<a href="{portal_url}" style="background:#5B9E96;color:#fff;text-decoration:none;
padding:12px 28px;border-radius:8px;font-weight:bold;">כניסה לפורטל</a></p>
<p>בברכה,<br>פורטל הלקוחות של אקו-אויל</p></div>"""
    return send_office_email(
        subject=f"עדכון במסמך הצהרת יצרן — {biz}",
        html=html, to=submitter.email)


# שדות שמותר למשרד לערוך (לימור 13/08, אחרי שם-כפול של מסד זילבר) —
# טקסט חופשי בלבד; שדות-בחירה מרשימות מבוקרות נשארים דרך "החזירי לתיקון".
_ADMIN_EDITABLE_FIELDS = {
    "producer_name": "producer_name",
    "business_id": "business_id",
    "permit_number": "permit_number",
    "ceo_name": "ceo_name",
    "producer_email": "client_email",
    "address": "client_address",
    "production_facility": "production_facility",
    "waste_stream_number": "waste_stream_number",
    "concentration_range": "concentration_range",
}


@ecooil_docs.route("/admin/producer-declarations/<int:decl_id>/fields",
                   methods=["PATCH"])
@jwt_required()
def admin_edit_declaration_fields(decl_id):
    """עריכת משרד לפרטי הצהרה (לימור 13/08) — חוסכת החזרות לתיקון על טעויות
    הקלדה. מותר רק לפני חתימת הלקוח (הוגשה / בתא הלקוח): מהחתימה והלאה
    המסמך חייב להתאים למה שנחתם. כל שינוי נרשם בהערות (מעקב)."""
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "admin only"}), 403
    from .db import ProducerDeclaration

    d = db.session.get(ProducerDeclaration, decl_id)
    if d is None or d.submitted_by_user_id is None:
        return jsonify({"error": "not found"}), 404
    if d.status not in ("submitted", "released"):
        return jsonify({"error": "עריכה אפשרית רק לפני חתימת הלקוח — "
                                  "אחרי חתימה השתמשי בביטול אישור או בהחזרה לתיקון"}), 409

    data = request.get_json(silent=True) or {}
    changes = []
    for key, col in _ADMIN_EDITABLE_FIELDS.items():
        if key not in data:
            continue
        new = (str(data.get(key) or "")).strip() or None
        old = getattr(d, col)
        if (old or None) != new:
            setattr(d, col, new)
            changes.append(f"{key}: '{old or ''}' ← '{new or ''}'")
    if not changes:
        return jsonify({"id": d.id, "changed": 0})
    stamp = (f"עריכת משרד {datetime.utcnow():%d/%m/%Y}: " + " | ".join(changes))
    d.notes = f"{d.notes}\n{stamp}" if d.notes else stamp
    db.session.commit()
    return jsonify({"id": d.id, "changed": len(changes)})


@ecooil_docs.route("/admin/producer-declarations/<int:decl_id>/notify-edited",
                   methods=["POST"])
@jwt_required()
def admin_notify_declaration_edited(decl_id):
    """מייל עדכון ללקוח אחרי עריכת משרד (לימור 20/08) — נשלח רק בלחיצה שלה
    (שאלה אחרי שמירת העריכה), ורק כשההצהרה בתא הלקוח — אחרת אין לו מה להוריד
    (בהצהרה שרק "הוגשה" מייל השחרור הרגיל כבר יכסה את זה)."""
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "admin only"}), 403
    from .db import ProducerDeclaration

    d = db.session.get(ProducerDeclaration, decl_id)
    if d is None or d.submitted_by_user_id is None:
        return jsonify({"error": "not found"}), 404
    if d.status != "released":
        return jsonify({"error": "מייל עדכון נשלח רק כשההצהרה בתא הלקוח"}), 409
    sent = False
    try:
        sent = _notify_customer_declaration_edited(d)
    except Exception as exc:
        current_app.logger.error("edit notification failed: %s", exc)
    return jsonify({"id": d.id, "email_sent": sent})


@ecooil_docs.route("/admin/producer-declarations/<int:decl_id>/agreement",
                   methods=["POST"])
@jwt_required()
def admin_issue_agreement(decl_id):
    """הפקת מסמך הסכמה (לימור 12/08, מנגנון ב'): רק להצהרה שאושרה סופית,
    ורק בלחיצה שלה מדף הטיוטה. המספר נולד כאן — סדרה קבועה שמתחילה
    ב-1001, לא תלויה בגיליון המסד ולא משתנה לעולם."""
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "admin only"}), 403
    from .db import ProducerDeclaration, AgreementDocument

    d = db.session.get(ProducerDeclaration, decl_id)
    if d is None or d.submitted_by_user_id is None:
        return jsonify({"error": "not found"}), 404
    if d.status != "approved":
        return jsonify({"error": "אפשר להפיק מסמך הסכמה רק להצהרה שאושרה סופית"}), 409
    existing = next((a for a in d.agreement_documents if a.number), None)
    if existing:
        return jsonify({"id": existing.id, "number": existing.number,
                        "existing": True}), 200

    max_num = db.session.query(db.func.max(AgreementDocument.number)).scalar()
    agreement = AgreementDocument(
        declaration_id=d.id,
        number=max(1000, max_num or 0) + 1,
        issued_by_name="אקו-אויל (פורטל)",
        valid_from=d.valid_from,
        valid_until=d.valid_until,
    )
    db.session.add(agreement)
    db.session.commit()

    email_sent = False
    try:
        email_sent = _notify_customer_agreement_issued(d, agreement)
    except Exception as exc:
        current_app.logger.error("agreement notification failed: %s", exc)

    # יידוע המוביל האחראי (לימור 13/08) — רק ליצרן עקיף מקושר; היעדר קישור
    # או היעדר משתמשי פורטל למוביל מדווח ללימור בתשובת ההפקה, לא נבלע.
    transporter = None
    client = db.session.get(Client, d.client_id)
    if client is not None and client.client_type == "indirect":
        if not client.parent_client_id:
            transporter = "not_linked"
        else:
            parent = db.session.get(Client, client.parent_client_id)
            emails = [u.email for u in User.query.filter_by(
                client_id=client.parent_client_id, is_active=True).all() if u.email]
            if not emails:
                transporter = "no_users"
            else:
                try:
                    sent = _notify_transporter_agreement_issued(d, agreement, emails)
                    transporter = f"sent:{sent}" if sent else "send_failed"
                except Exception as exc:
                    current_app.logger.error("transporter notify failed: %s", exc)
                    transporter = "send_failed"

    resp = {"id": agreement.id, "number": agreement.number, "email_sent": email_sent}
    if transporter is not None:
        resp["transporter"] = transporter
    return jsonify(resp), 201


# משפחות הזרמים לכותרת המסמך — אותה חלוקה כמו שתי תבניות הוורד הישנות
_AGREEMENT_FAMILY = {
    "mineral": "מינרלי/ אמולסיה/ מזוט",
    "emulsion": "מינרלי/ אמולסיה/ מזוט",
    "gasoil": "מינרלי/ אמולסיה/ מזוט",
    "acid": "חומצות/ בסיסים/ מי שטיפה",
    "base": "חומצות/ בסיסים/ מי שטיפה",
    "washwater": "חומצות/ בסיסים/ מי שטיפה",
}


@ecooil_docs.route("/portal/agreement-doc-data", methods=["GET"])
@jwt_required()
def agreement_doc_data():
    """נתונים לדף מסמך ההסכמה: ?agreement_id= — מסמך שהופק (מנהלת, או לקוח
    בהיקף החברות שלו); ?declaration_id= — תצוגת טיוטה לפני הפקה (מנהלת בלבד)."""
    from .db import ProducerDeclaration, AgreementDocument

    is_admin = get_jwt().get("role") == "admin"
    ag_id = request.args.get("agreement_id", type=int)
    decl_id = request.args.get("declaration_id", type=int)
    agreement = None
    if ag_id:
        agreement = db.session.get(AgreementDocument, ag_id)
        if agreement is None or not agreement.number:
            return jsonify({"error": "not found"}), 404
        d = agreement.declaration
        if d is None or d.submitted_by_user_id is None:
            return jsonify({"error": "not found"}), 404
        if not is_admin and _decl_in_user_scope(d.id) is None:
            return jsonify({"error": "not found"}), 404
    elif decl_id:
        if not is_admin:
            return jsonify({"error": "admin only"}), 403
        d = db.session.get(ProducerDeclaration, decl_id)
        if d is None or d.submitted_by_user_id is None:
            return jsonify({"error": "not found"}), 404
    else:
        return jsonify({"error": "agreement_id or declaration_id required"}), 400

    clients = {d.client_id: d.client.name if d.client else f"חברה #{d.client_id}"}
    users = {}
    if d.submitted_by_user_id:
        u = db.session.get(User, d.submitted_by_user_id)
        if u:
            users[u.id] = u.email
    return jsonify({
        "declaration": _decl_dict(d, clients, users),
        "family_title": _AGREEMENT_FAMILY.get(d.material_classification,
                                              "חומצות/ בסיסים/ מי שטיפה"),
        "agreement": ({"id": agreement.id, "number": agreement.number,
                       "issued_at": agreement.issued_at.isoformat()}
                      if agreement else None),
        # שם הקובץ להורדת מסמך ההסכמה (17/08) — בלי המספר; המספר מתווסף רק
        # לעותק שהגשר מתייק ב-Z:
        "file_name": _doc_file_name(d, "הסכמה"),
    })


def _notify_customer_agreement_issued(d, agreement):
    """מייל למגיש כשמסמך ההסכמה הופק — סוף התהליך. נוסח: לימור 12/08;
    תוספת תוקף-שנתיים + שמירת עותקים לביקורת: לימור 13/08."""
    from .mailer import send_office_email

    submitter = db.session.get(User, d.submitted_by_user_id) if d.submitted_by_user_id else None
    if submitter is None or not submitter.email:
        return False
    portal_url = "https://portal.eco-oil.co.il"
    biz = (d.producer_name or "").strip()
    until = d.valid_until.strftime("%d/%m/%Y") if d.valid_until else ""
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p>שלום,</p>
<p>הצהרת היצרן של <b>{biz}</b> אושרה סופית, ומסמך ההסכמה לקליטת הפסולת
(מסמך מס' {agreement.number}) מוכן וזמין בפורטל הלקוחות — לצפייה, להורדה ולהדפסה.</p>
<p><b>בכך הושלם התהליך במלואו.</b> ההצהרה בתוקף, ואפשר לשנע את הפסולת לטיפול
בליווי המסמכים הנדרשים.</p>
<p><b>חשוב לדעת:</b> לשני המסמכים יחד — הצהרת היצרן ומסמך ההסכמה — תוקף של
שנתיים{f" (עד {until})" if until else ""}. הורידו עותק של שני המסמכים ושמרו
אותם במיקום ייעודי במחשב שלכם — הם ההוכחה בעת ביקורת לכך שהפינויים
הוסדרו לפי דרישות החוק.</p>
<p style="margin:22px 0;">
<a href="{portal_url}" style="background:#5B9E96;color:#fff;text-decoration:none;
padding:12px 28px;border-radius:8px;font-weight:bold;">כניסה לפורטל</a></p>
<p>בברכה,<br>פורטל הלקוחות של אקו-אויל</p></div>"""
    return send_office_email(
        subject=f"מסמך ההסכמה לקליטת הפסולת מוכן — {biz}",
        html=html, to=submitter.email)


def _notify_transporter_agreement_issued(d, agreement, emails):
    """מייל למוביל האחראי כשלקוח עקיף שלו השלים את ההסדרה (לימור 13/08).
    נחזיר כמה נשלחו בפועל."""
    from .mailer import send_office_email

    biz = (d.producer_name or "").strip()
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p>שלום,</p>
<p>נשמח לעדכן כי <b>{biz}</b>, מלקוחותיכם, השלים את הסדרת הצהרת היצרן מול
אקו-אויל: ההצהרה נחתמה ואושרה, ומסמך ההסכמה לקליטת הפסולת
(מסמך מס' {agreement.number}, זרם {d.material_name or ""}) הופק ובתוקף.</p>
<p>מעתה ניתן לשנע פסולת מהזרם המוסדר מלקוח זה, בליווי המסמכים הנדרשים.</p>
<p>בברכה,<br>פורטל הלקוחות של אקו-אויל</p></div>"""
    sent = 0
    for to in emails:
        try:
            if send_office_email(
                    subject=f"הושלמה הסדרת הצהרת יצרן — {biz}",
                    html=html, to=to):
                sent += 1
        except Exception as exc:
            current_app.logger.error("transporter agreement email failed (%s): %s", to, exc)
    return sent


@ecooil_docs.route("/portal/my-declaration-docs", methods=["GET"])
@jwt_required()
def my_declaration_docs():
    """תא הלקוח — כל ההצהרות שבמסלול, לתצוגת פס-השלבים (לימור 12/08):
    submitted (בבדיקת הנוסח) / released (לחתימה) / needs_fix (הוחזרה לתיקון,
    עם הערות לימור) / approved (בתוקף). פסולות וגרסאות ישנות לא מוצגות.
    ההיקף: החברות המותרות למשתמש (כולל רב-חברות). מנהלת משתמשת בנקודת
    הקצה הניהולית — כאן רשימה ריקה."""
    from .db import ProducerDeclaration

    claims = get_jwt()
    preview = None
    if claims.get("role") == "admin":
        # תצוגת "דרך העיניים של הלקוח" (לימור 17/08): מנהלת מעבירה client_id
        # ומקבלת בדיוק את מה שאותה חברה מקבלת — כולל היצרנים העקיפים שלה.
        # בלי client_id — רשימה ריקה, כמו קודם.
        cid = request.args.get("client_id", type=int)
        pc = db.session.get(Client, cid) if cid else None
        if pc is None:
            return jsonify({"declarations": []})
        own = {pc.id}
        allowed = _expand_indirect([pc.id])
        preview = {"client_id": pc.id, "client_name": pc.name}
    else:
        user = db.session.get(User, int(get_jwt_identity()))
        if user is None:
            return jsonify({"error": "no user"}), 403
        # כולל היצרנים העקיפים שהמשתמש הוא המוביל האחראי שלהם (לימור 17/08)
        allowed = _decl_scope_ids(user)
        own = set(user.allowed_client_ids())
    if not allowed:
        return jsonify({"declarations": []})

    decls = (ProducerDeclaration.query
             .filter(ProducerDeclaration.client_id.in_(allowed),
                     ProducerDeclaration.status.in_(("submitted", "released", "needs_fix", "approved")),
                     ProducerDeclaration.submitted_by_user_id.isnot(None))
             .order_by(ProducerDeclaration.issued_at.desc(),
                       ProducerDeclaration.id.desc())
             .limit(200).all())

    user_ids = {d.submitted_by_user_id for d in decls}
    users = {u.id: u.email for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    clients = {c.id: c.name for c in Client.query.filter(Client.id.in_(allowed)).all()}

    rows = []
    for d in decls:
        row = _decl_dict(d, clients, users)
        # "של לקוח עקיף שלכם" — כדי שמוביל לא יחשוב שההצהרה שלו עצמו,
        # ולא יחפש כפתור העלאה שאינו שלו (לימור 17/08)
        row["indirect"] = d.client_id not in own
        rows.append(row)
    return jsonify({"declarations": rows, "preview": preview})


@ecooil_docs.route("/portal/my-declaration-docs/<int:decl_id>/signed-scan",
                   methods=["POST"])
@jwt_required()
def upload_signed_scan(decl_id):
    """הלקוח מעלה את המסמך החתום — סריקה או צילום טלפון (לימור 09/08).

    מותר רק במעמד "בתא הלקוח" (released); העלאה חוזרת מחליפה את הקודמת עד
    האישור הסופי. אחרי האישור — נעול (לימור מבטלת אישור אם צריך להחליף)."""
    if get_jwt().get("role") == "admin":
        return jsonify({"error": "העלאת לקוח — מנהלת מצרפת דרך מסך הניהול"}), 403
    # מוביל מעלה את המסמך החתום גם עבור יצרן עקיף שלו (לימור 17/08):
    # "מבחינת המובילים הלקוח הוא שלהם ולכן זה באחריותם" — הוא זה שמעביר
    # ליצרן לחתימה ומקבל בחזרה. זו הנחת העבודה שעליה יושבת החלטה 4.
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
    if request.args.get("month"):
        # סינון לפי חודש (בקשת לקוחה דרך לימור 03/09) — משלים את סינון השנה.
        # עמודת month מגיעה מהריכוז (הגיליונות חודשיים) — תמיד מלאה.
        q = q.filter(EcoOilUnloadEvent.month == int(request.args["month"]))
    if request.args.get("stream"):
        q = q.filter(EcoOilUnloadEvent.stream_norm == request.args["stream"])
    if request.args.get("q"):
        like = f"%{request.args['q'].strip()}%"
        q = q.filter(or_(EcoOilUnloadEvent.customer.ilike(like),
                         EcoOilUnloadEvent.transporter.ilike(like)))

    # חסימת חברה (לימור 17/08): הפריקות עצמן עדיין מוצגות — הן לא מסמך;
    # רק ההורדות נחסמות, וההודעה המנומסת מוצגת במקומן.
    blocked = bool(client.docs_blocked)

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
        "docs_blocked": blocked,
        "docs_blocked_notice": DOCS_BLOCKED_NOTICE if blocked else None,
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
            # sanction. Withheld statuses hide BOTH downloads. A company-level
            # block (17/08) hides them all the same way, row by row.
            "has_pdf": (not blocked) and bool(r.pdf_key)
            and r.doc_status not in WITHHELD_STATUSES,
            "has_manifest": (not blocked) and bool(r.manifest_key)
            and r.doc_status not in WITHHELD_STATUSES,
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
    # חסימת חברה (לימור 17/08) — נאכפת בשרת, לא רק בהסתרת הכפתור.
    if client.docs_blocked:
        return jsonify({"error": "blocked",
                        "message": DOCS_BLOCKED_NOTICE}), 403
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
    # צפייה מול הורדה (לימור 18/08): עד היום כל לחיצה החזירה attachment,
    # ולכן כל פתיחה של מסמך גם הורידה אותו בשקט — לקוח על הקו צבר עשרה
    # קבצים בלי לדעת. ההורדה חייבת להיות בחירה מודעת, ולכן ?mode=view
    # מגיש את הקובץ לצפייה בלבד.
    disp = "inline" if request.args.get("mode") == "view" else "attachment"
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["B2_BUCKET_CERTS"], "Key": key,
                "ResponseContentDisposition":
                    f"{disp}; filename*=UTF-8''{fname}"},
        ExpiresIn=PRESIGN_SECONDS,
    )
    return jsonify({"url": url})


# תקרת ההורדה המרוכזת — מגן על השרת; הסינון לחודש אחד רחוק מלהגיע אליה.
BULK_MAX_FILES = 150


@ecooil_docs.route("/my-documents/download-all", methods=["GET"])
@jwt_required()
def download_all():
    """הורדה מרוכזת (בקשת לקוחה דרך לימור 03/09): קובץ ZIP אחד עם כל מסמכי
    הסינון הנוכחי — אישורי פריקה וטופסי מלווה. אותם שערים בדיוק כמו בהורדה
    הבודדת: חסימת חברה נאכפת, שורות מעוכבות (סנקציה/לא-לפרסם) לא נכללות,
    ושורות בלי קובץ פשוט מדולגות."""
    if get_jwt().get("role") == DECLARATION_ONLY_ROLE:
        return jsonify({"error": "declarations only"}), 403
    client = _client_for_request()
    if client is None:
        return jsonify({"error": "no client"}), 403
    if client.docs_blocked:
        return jsonify({"error": "blocked", "message": DOCS_BLOCKED_NOTICE}), 403

    q, _mode = _scoped_query(client)
    if request.args.get("year"):
        q = q.filter(EcoOilUnloadEvent.year == int(request.args["year"]))
    if request.args.get("month"):
        q = q.filter(EcoOilUnloadEvent.month == int(request.args["month"]))
    if request.args.get("stream"):
        q = q.filter(EcoOilUnloadEvent.stream_norm == request.args["stream"])
    if request.args.get("q"):
        like = f"%{request.args['q'].strip()}%"
        q = q.filter(or_(EcoOilUnloadEvent.customer.ilike(like),
                         EcoOilUnloadEvent.transporter.ilike(like)))

    rows = q.order_by(EcoOilUnloadEvent.event_date.asc(),
                      EcoOilUnloadEvent.id.asc()).limit(5000).all()
    files = []  # (key, zip_name)
    for r in rows:
        if r.doc_status in WITHHELD_STATUSES:
            continue
        stamp = r.event_date.strftime("%Y-%m-%d") if r.event_date else "ללא-תאריך"
        if r.pdf_key:
            files.append((r.pdf_key, f"{stamp}_{r.pdf_key.rsplit('/', 1)[-1]}"))
        if r.manifest_key:
            files.append((r.manifest_key,
                          f"{stamp}_{r.manifest_key.rsplit('/', 1)[-1]}"))
    if not files:
        return jsonify({"error": "empty",
                        "message": "אין מסמכים זמינים בסינון הנוכחי"}), 404
    if len(files) > BULK_MAX_FILES:
        return jsonify({"error": "too many", "message":
                        f"הסינון הנוכחי כולל {len(files)} מסמכים — יותר מדי "
                        f"להורדה אחת (עד {BULK_MAX_FILES}). צמצמו לחודש או "
                        "לזרם מסוים והורידו בחלקים."}), 413

    for var in ("B2_KEY_ID", "B2_APP_KEY", "B2_BUCKET_CERTS", "B2_ENDPOINT"):
        if not os.environ.get(var):
            return jsonify({"error": "storage not configured"}), 503
    import io
    import zipfile
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['B2_ENDPOINT']}",
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APP_KEY"],
        config=Config(signature_version="s3v4"),
    )
    buf = io.BytesIO()
    seen = set()
    missing = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key, name in files:
            base = name
            n = 2
            while name in seen:  # שני קבצים באותו שם — לא דורסים
                stem, dot, ext = base.rpartition(".")
                name = f"{stem}_{n}{dot}{ext}" if dot else f"{base}_{n}"
                n += 1
            seen.add(name)
            try:
                obj = s3.get_object(Bucket=os.environ["B2_BUCKET_CERTS"], Key=key)
                zf.writestr(name, obj["Body"].read())
            except Exception:  # קובץ בודד שחסר באחסון לא מפיל את כל החבילה
                missing += 1
                current_app.logger.warning("bulk download: missing B2 key %s", key)
        if missing:
            zf.writestr("שימו-לב.txt",
                        f"{missing} מסמכים לא היו זמינים באחסון ולא נכללו.")
    buf.seek(0)

    parts = ["documents", client.name]
    if request.args.get("year"):
        parts.append(request.args["year"])
    if request.args.get("month"):
        parts.append(request.args["month"].zfill(2))
    from urllib.parse import quote
    fname = quote("_".join(parts) + ".zip")
    return Response(buf.getvalue(), mimetype="application/zip", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})
