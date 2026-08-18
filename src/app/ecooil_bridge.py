# -*- coding: utf-8 -*-
"""Eco-Oil bridge endpoints — the secure door the office bridge pushes through.

The ריכוז workbook on the office drive is the source of truth (Limor 2026-07-13);
the office bridge reads it hourly, uploads certificate PDFs to B2 cloud storage,
and pushes the unload-event rows here. The cloud only mirrors — it never edits.

Auth: ECOOIL_BRIDGE_TOKEN env var (Bearer), same pattern as FIELD_BRIDGE_TOKEN.
"""
import os
import re
import secrets as _secrets
from datetime import datetime, date
from functools import wraps

from flask import Blueprint, current_app, request, jsonify
from sqlalchemy import func

from .db import db, EcoOilUnloadEvent

ecooil_bridge = Blueprint("ecooil_bridge", __name__, url_prefix="/bridge/ecooil")

MAX_EVENTS = 30000

# Whitelisted event fields the bridge may set (everything except id/synced_at).
_STR_FIELDS = (
    "code", "vehicle", "transporter", "customer", "address", "billed_to",
    "stream", "stream_norm", "doc_status", "package_type", "exit_time", "notes",
    "pdf_path", "pdf_key", "manifest_path", "manifest_key", "source_sheet",
)
_INT_FIELDS = ("year", "month", "serial", "package_count", "source_row")
_FLOAT_FIELDS = ("weight_in", "weight_out", "weight_net", "declared_tons")

# Column length caps from the model — Postgres enforces VARCHAR limits that
# SQLite silently ignores, and one overlong stray value (a date-string pasted
# into the code column) must not fail the whole snapshot.
_MAX_LEN = {c.name: c.type.length
            for c in EcoOilUnloadEvent.__table__.columns
            if hasattr(c.type, "length") and c.type.length}


def _bearer_token():
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.startswith("Bearer ") else None


def ecooil_bridge_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        expected = os.environ.get("ECOOIL_BRIDGE_TOKEN")
        tok = _bearer_token()
        if not expected or not tok or not _secrets.compare_digest(tok, expected):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


# Filing-folder derivation (Limor's ruling 06/08/2026: the folder a certificate
# is FILED in is the portal-visibility anchor). The chain keeps sub-entity
# folders (e.g. 'גדות_כולל / גדות אחסון ושינוע') and drops year/month/
# bookkeeping folders, mirroring the office matcher's owner logic.
_FILING_ROOTS = {"מובילים", "לקוחות"}
_FILING_SKIP = {"אישורים", "ישן"}

# חוק לימור 06/08/2026: תיקיות חסומות לעולמים — שורה שהקבצים שלה מתויקים שם
# נקלטת בלי קבצים ובלי שיוך תיקייה, כך שהיא לא מוצגת ולא ניתנת להורדה לאף
# חשבון (השכבה הענן־צדית; המַתְאִמים במשרד גם מפסיקים לסרוק את התיקייה).
_BLOCKED_SEGMENTS = {"איציק"}


def _path_blocked(path):
    if not path:
        return False
    parts = [p.strip() for p in str(path).replace("\\", "/").split("/") if p.strip()]
    return any(p in _BLOCKED_SEGMENTS for p in parts)


def _filed_owner_from_path(path):
    if not path:
        return None
    parts = [p.strip() for p in str(path).replace("\\", "/").split("/") if p.strip()]
    for i, p in enumerate(parts[:-1]):
        if p in _FILING_ROOTS:
            segs = parts[i + 1:-1]
            if not segs:
                return None
            keep = [segs[0]] + [
                s for s in segs[1:]
                if s not in _FILING_SKIP and "מלווה" not in s
                and not re.fullmatch(r"\d{4}", s)
                and not re.fullmatch(r"\d{1,2}([\./]\d{2,4})?", s)
            ]
            return " / ".join(keep)[:200] or None
    return None


def _coerce_event(item):
    """Validate + coerce one incoming event dict → kwargs for the model.
    Returns None for rows missing the essentials (year, month, event_date)."""
    kwargs = {}
    for k in _STR_FIELDS:
        v = item.get(k)
        if v is not None:
            v = str(v).strip() or None
        if v is not None and k in _MAX_LEN:
            v = v[:_MAX_LEN[k]]
        kwargs[k] = v
    for k in _INT_FIELDS:
        try:
            kwargs[k] = int(item[k]) if item.get(k) is not None else None
        except (TypeError, ValueError):
            kwargs[k] = None
    for k in _FLOAT_FIELDS:
        try:
            kwargs[k] = float(item[k]) if item.get(k) is not None else None
        except (TypeError, ValueError):
            kwargs[k] = None
    d = item.get("event_date")
    if d:
        try:
            kwargs["event_date"] = date.fromisoformat(str(d)[:10])
        except ValueError:
            kwargs["event_date"] = None
    else:
        kwargs["event_date"] = None
    if not kwargs.get("year") or not kwargs.get("month") or kwargs["event_date"] is None:
        return None
    # Blocked-folder enforcement BEFORE anything else: strip the files so the
    # row carries no document and no folder identity.
    if _path_blocked(kwargs.get("pdf_path")):
        kwargs["pdf_path"] = kwargs["pdf_key"] = None
    if _path_blocked(kwargs.get("manifest_path")):
        kwargs["manifest_path"] = kwargs["manifest_key"] = None
    # The certificate's filing folder is the anchor; a row with only a signed
    # manifest follows the manifest's folder (same filing act by Limor).
    kwargs["filed_owner"] = _filed_owner_from_path(
        kwargs.get("pdf_path") or kwargs.get("manifest_path"))
    kwargs["synced_at"] = datetime.utcnow()
    return kwargs


@ecooil_bridge.route("/sync", methods=["POST"])
@ecooil_bridge_required
def sync_events():
    """Wholesale snapshot replace — mirrors the office reader's wipe+reload model.
    Body: {"events": [...]}  (one atomic transaction: readers never see a gap)."""
    data = request.get_json(silent=True) or {}
    events = data.get("events")
    if not isinstance(events, list):
        return jsonify({"error": "events list required"}), 400
    if len(events) > MAX_EVENTS:
        return jsonify({"error": f"too many events (max {MAX_EVENTS})"}), 400

    rows, skipped = [], 0
    for item in events:
        if not isinstance(item, dict):
            skipped += 1
            continue
        kwargs = _coerce_event(item)
        if kwargs is None:
            skipped += 1
            continue
        rows.append(kwargs)

    EcoOilUnloadEvent.query.delete()
    if rows:
        db.session.bulk_insert_mappings(EcoOilUnloadEvent, rows)
    db.session.commit()
    return jsonify({"ok": True, "loaded": len(rows), "skipped": skipped})


@ecooil_bridge.route("/status", methods=["GET"])
@ecooil_bridge_required
def status():
    total = db.session.query(func.count(EcoOilUnloadEvent.id)).scalar() or 0
    last = db.session.query(func.max(EcoOilUnloadEvent.synced_at)).scalar()
    with_pdf = (db.session.query(func.count(EcoOilUnloadEvent.id))
                .filter(EcoOilUnloadEvent.pdf_key.isnot(None)).scalar() or 0)
    with_manifest = (db.session.query(func.count(EcoOilUnloadEvent.id))
                     .filter(EcoOilUnloadEvent.manifest_key.isnot(None)).scalar() or 0)
    with_filed_owner = (db.session.query(func.count(EcoOilUnloadEvent.id))
                        .filter(EcoOilUnloadEvent.filed_owner.isnot(None)).scalar() or 0)
    per_year = dict(
        db.session.query(EcoOilUnloadEvent.year, func.count(EcoOilUnloadEvent.id))
        .group_by(EcoOilUnloadEvent.year).all())
    per_stream = dict(
        db.session.query(EcoOilUnloadEvent.stream_norm, func.count(EcoOilUnloadEvent.id))
        .group_by(EcoOilUnloadEvent.stream_norm).all())
    per_doc_status = dict(
        db.session.query(EcoOilUnloadEvent.doc_status, func.count(EcoOilUnloadEvent.id))
        .filter(EcoOilUnloadEvent.doc_status.isnot(None))
        .group_by(EcoOilUnloadEvent.doc_status).all())
    return jsonify({
        "total": total,
        "with_pdf_key": with_pdf,
        "with_manifest_key": with_manifest,
        "with_filed_owner": with_filed_owner,
        "per_year": {str(k): v for k, v in per_year.items()},
        "per_stream": {str(k): v for k, v in per_stream.items()},
        "per_doc_status": per_doc_status,
        "last_synced_at": last.isoformat() if last else None,
    })


# ---------------------------------------------------------------------------
# הזנה אוטומטית למסד (לימור 10/08, עקרונות אושרו 03/08):
# הגשר המשרדי מושך הצהרות שאושרו סופית וכותב אותן למסד על Z: —
# שורה חדשה תמיד בגיליון "הצהרות"; עדכון-במקום לפי ח.פ. בגיליון
# ח.פ.-היתר-תוקף (לקוח חדש = שורה חדשה עם שם/ח.פ./היתר); אי-ודאות
# (כפילות ח.פ., אין ח.פ.) לא נכתבת — מתריעים ולא מנחשים.
# ---------------------------------------------------------------------------

@ecooil_bridge.route("/masad-feed", methods=["GET"])
@ecooil_bridge_required
def masad_feed_pending():
    """ההצהרות שממתינות להזנה — approved שאחד משני החצאים שלהן חסר."""
    from .db import Client, ProducerDeclaration

    decls = (ProducerDeclaration.query
             .filter(ProducerDeclaration.status == "approved",
                     ProducerDeclaration.submitted_by_user_id.isnot(None),
                     db.or_(ProducerDeclaration.masad_log_at.is_(None),
                            ProducerDeclaration.masad_summary_at.is_(None)))
             .order_by(ProducerDeclaration.approved_at.asc())
             .limit(50).all())
    clients = {c.id: c for c in Client.query.filter(
        Client.id.in_({d.client_id for d in decls})).all()} if decls else {}

    def row(d):
        c = clients.get(d.client_id)
        return {
            "id": d.id,
            "log_pending": d.masad_log_at is None,
            "summary_pending": d.masad_summary_at is None,
            "approved_at": d.approved_at.isoformat() if d.approved_at else None,
            "account_name": c.name if c else None,
            "account_type": (c.client_type if c else None) or "direct",
            "producer_name": d.producer_name,
            "address": d.client_address,
            "business_id": d.business_id,
            "permit_number": d.permit_number,
            "producer_size": d.producer_size,
            "material_name": d.material_name,
            "material_classification": d.material_classification,
            "waste_stream_number": d.waste_stream_number,
            "production_facility": d.production_facility,
            "y_code": d.basel_y_code,
            "annex8": d.basel_annexviii_code,
            "h_code": d.basel_h_code,
            "un_group": d.un_risk_group,
            "catalog": d.european_catalog_code,
            "treatment_type": d.treatment_facility_type,
            "r_code": d.basel_r_code,
            "d_code": d.basel_d_code,
            "quantity": d.annual_quantity_text,
            "packaging": d.packaging_type,
            "characteristic": d.waste_main_characteristic,
            "pollutant_type": d.pollutant_type,
            "concentration_range": d.concentration_range,
            "addressed_to": d.addressed_to,
            "producer_email": d.client_email,
            "valid_from": d.valid_from.isoformat() if d.valid_from else None,
            "valid_until": d.valid_until.isoformat() if d.valid_until else None,
        }

    return jsonify({"declarations": [row(d) for d in decls]})


# ---------------------------------------------------------------------------
# תיוק אוטומטי לתיקיות הלקוחות (לימור 12/08): הגשר המשרדי מושך מסמכי
# הסכמה שהופקו וסריקות חתומות של הצהרות שאושרו, מייצר/מוריד קבצים
# ומתייק ב-Z:\Eco_General\לקוחות\<לקוח>\<מסמכים|הצהרת יצרן+הסכמה>.
# כשל איתור תיקייה לא מנוחש — מדווח כהערה ומתריעים במייל פעם אחת.
# ---------------------------------------------------------------------------

def _filing_decl_fields(d, clients):
    c = clients.get(d.client_id)
    aliases = [a.strip() for a in (c.billing_aliases or "").splitlines() if a.strip()] if c else []
    return {
        "producer_name": d.producer_name,
        "account_name": c.name if c else None,
        "folder_candidates": [x for x in ([d.producer_name, c.name if c else None] + aliases) if x],
        "material_name": d.material_name,
        "material_classification": d.material_classification,
        "producer_size": d.producer_size,
        "production_facility": d.production_facility,
        "waste_stream_number": d.waste_stream_number,
        "business_id": d.business_id,
        "permit_number": d.permit_number,
        "ceo_name": d.ceo_name,
        "address": d.client_address,
        "y_code": d.basel_y_code,
        "annex8": d.basel_annexviii_code,
        "h_code": d.basel_h_code,
        "un_group": d.un_risk_group,
        "catalog": d.european_catalog_code,
        "treatment_type": d.treatment_facility_type,
        "r_code": d.basel_r_code,
        "d_code": d.basel_d_code,
        "quantity": d.annual_quantity_text,
        "packaging": d.packaging_type,
        "characteristic": d.waste_main_characteristic,
        "pollutant_type": d.pollutant_type,
        "concentration_range": d.concentration_range,
    }


@ecooil_bridge.route("/filing-feed", methods=["GET"])
@ecooil_bridge_required
def filing_feed_pending():
    """מה שממתין לתיוק: מסמכי הסכמה שהופקו (filed_at ריק) + סריקות חתומות
    של הצהרות שאושרו סופית (scan_filed_at ריק)."""
    from .db import AgreementDocument, Client, ProducerDeclaration
    from .ecooil_docs import _doc_file_name

    agreements = (AgreementDocument.query
                  .filter(AgreementDocument.number.isnot(None),
                          AgreementDocument.filed_at.is_(None))
                  .order_by(AgreementDocument.number.asc())
                  .limit(30).all())
    scans = (ProducerDeclaration.query
             .filter(ProducerDeclaration.status == "approved",
                     ProducerDeclaration.submitted_by_user_id.isnot(None),
                     ProducerDeclaration.signed_scan_at.isnot(None),
                     ProducerDeclaration.scan_filed_at.is_(None))
             .order_by(ProducerDeclaration.approved_at.asc())
             .limit(30).all())

    client_ids = ({a.declaration.client_id for a in agreements if a.declaration}
                  | {d.client_id for d in scans})
    clients = {c.id: c for c in Client.query.filter(
        Client.id.in_(client_ids)).all()} if client_ids else {}

    ag_rows = []
    for a in agreements:
        d = a.declaration
        if d is None:
            continue
        row = _filing_decl_fields(d, clients)
        # שם הקובץ נבנה בשרת (לימור 17/08) — זהה לשם שהלקוח מוריד מהפורטל,
        # בתוספת מספר ההסכמה
        row.update({"agreement_id": a.id, "number": a.number,
                    "file_name": _doc_file_name(d, "הסכמה", a.number),
                    "issued_at": a.issued_at.isoformat() if a.issued_at else None})
        ag_rows.append(row)
    scan_rows = []
    for d in scans:
        row = _filing_decl_fields(d, clients)
        row.update({"declaration_id": d.id,
                    "file_name": _doc_file_name(d, "הצהרה חתומה"),
                    "approved_at": d.approved_at.isoformat() if d.approved_at else None,
                    "scan_filename": d.signed_scan_filename,
                    "scan_mime": d.signed_scan_mime})
        scan_rows.append(row)
    return jsonify({"agreements": ag_rows, "scans": scan_rows})


@ecooil_bridge.route("/filing-feed/scan/<int:decl_id>", methods=["GET"])
@ecooil_bridge_required
def filing_feed_scan(decl_id):
    """הקובץ החתום עצמו — להורדת הגשר לצורך התיוק."""
    from flask import Response
    from .db import ProducerDeclaration

    d = db.session.get(ProducerDeclaration, decl_id)
    if d is None or not d.signed_scan_data:
        return jsonify({"error": "not found"}), 404
    return Response(d.signed_scan_data,
                    mimetype=d.signed_scan_mime or "application/octet-stream")


@ecooil_bridge.route("/filing-feed/ack", methods=["POST"])
@ecooil_bridge_required
def filing_feed_ack():
    """הגשר מדווח מה תויק. body: {"agreements":[{id,done,note}],"scans":[{id,done,note}]}.
    הערה חדשה (שטרם דווחה) → מייל התראה אחד למשרד — לא נדנוד שעתי."""
    from .db import AgreementDocument, ProducerDeclaration
    from .mailer import send_office_email

    data = request.get_json(silent=True) or {}
    now = datetime.utcnow()
    alerts, updated = [], 0

    for item in (data.get("agreements") or []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        a = db.session.get(AgreementDocument, int(item["id"]))
        if a is None or not a.number:
            continue
        if item.get("done") and a.filed_at is None:
            a.filed_at = now
        note = (item.get("note") or "").strip() or None
        if note and note != a.file_note:
            d = a.declaration
            alerts.append((f"מסמך הסכמה מס' {a.number}",
                           d.producer_name if d else "", note))
        a.file_note = note
        updated += 1

    for item in (data.get("scans") or []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        d = db.session.get(ProducerDeclaration, int(item["id"]))
        if d is None:
            continue
        if item.get("done") and d.scan_filed_at is None:
            d.scan_filed_at = now
        note = (item.get("note") or "").strip() or None
        if note and note != d.scan_file_note:
            alerts.append((f"הצהרה חתומה ({d.material_name or ''})",
                           d.producer_name or "", note))
        d.scan_file_note = note
        updated += 1
    db.session.commit()

    emailed = False
    if alerts:
        rows = "".join(
            f"<tr><td style='border:1px solid #999;padding:6px 12px;'>{what}</td>"
            f"<td style='border:1px solid #999;padding:6px 12px;'>{who}</td>"
            f"<td style='border:1px solid #999;padding:6px 12px;'>{note}</td></tr>"
            for what, who, note in alerts)
        html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p>התיוק האוטומטי לתיקיות הלקוחות לא הצליח עבור המסמכים הבאים:</p>
<table dir="rtl" style="border-collapse:collapse;">
<tr><td style="border:1px solid #999;padding:6px 12px;background:#eef3f2;"><b>מסמך</b></td>
<td style="border:1px solid #999;padding:6px 12px;background:#eef3f2;"><b>העסק</b></td>
<td style="border:1px solid #999;padding:6px 12px;background:#eef3f2;"><b>מה חסר</b></td></tr>
{rows}</table>
<p>אחרי שתסדרי את התיקייה — התיוק יושלם אוטומטית בסיבוב השעתי הבא.</p></div>"""
        try:
            emailed = send_office_email(
                subject="תיוק מסמכים אוטומטי — נדרשת השלמה ידנית", html=html)
        except Exception as exc:
            current_app.logger.error("filing-feed alert email failed: %s", exc)

    return jsonify({"ok": True, "updated": updated, "alert_emailed": emailed})


@ecooil_bridge.route("/masad-feed/ack", methods=["POST"])
@ecooil_bridge_required
def masad_feed_ack():
    """הגשר מדווח מה בוצע. body: {"results":[{id, log_done, summary_done, note}]}.
    note חדש (שלא דווח כבר) → מייל התראה למשרד — פעם אחת, לא נדנוד שעתי."""
    from .db import ProducerDeclaration
    from .mailer import send_office_email

    data = request.get_json(silent=True) or {}
    results = data.get("results")
    if not isinstance(results, list):
        return jsonify({"error": "results list required"}), 400

    now = datetime.utcnow()
    alerts, updated = [], 0
    for item in results:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        d = db.session.get(ProducerDeclaration, int(item["id"]))
        if d is None or d.status != "approved":
            continue
        if item.get("log_done") and d.masad_log_at is None:
            d.masad_log_at = now
        if item.get("summary_done") and d.masad_summary_at is None:
            d.masad_summary_at = now
        note = (item.get("note") or "").strip() or None
        if note and note != d.masad_note:
            alerts.append((d, note))
        d.masad_note = note
        updated += 1
    db.session.commit()

    emailed = False
    if alerts:
        # ניסוח ההודעה (לימור 18/08): הודעה שדורשת התייחסות חייבת לומר
        # במפורש לאיזה קובץ ולאיזה גיליון ללכת — מספרי שורות בלי זה הם
        # חסרי תכלית. הערות השורה כבר נושאות את שם הגיליון מהסקריפט המשרדי.
        import html as _html

        masad_path = (data.get("masad_path") or
                      r"Z:\Eco_General\מסד מלא_הצהרות_היתרים_מובילים.xlsx")
        rows = "".join(
            f"<tr><td style='border:1px solid #999;padding:6px 12px;'>{_html.escape(d.producer_name or '')}</td>"
            f"<td style='border:1px solid #999;padding:6px 12px;'>{_html.escape(d.material_name or '')}</td>"
            f"<td style='border:1px solid #999;padding:6px 12px;'>{_html.escape(note)}</td></tr>"
            for d, note in alerts)
        n = len(alerts)
        html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p>רשמתי את ההצהרות המאושרות למסד.
{'הצהרה אחת נרשמה' if n == 1 else f'{n} הצהרות נרשמו'} רק חלקית
{'ודורשת' if n == 1 else 'ודורשות'} השלמה ידנית שלך.</p>
<p style="background:#EEF3F7;border:1px solid #B9CBDA;border-radius:8px;padding:8px 12px;">
<b>הקובץ לעדכון:</b><br>{_html.escape(masad_path)}<br>
<span style="color:#555;">שם הגיליון והשורה מופיעים בעמודה "מה חסר ומה לעשות".</span></p>
<table dir="rtl" style="border-collapse:collapse;">
<tr><td style="border:1px solid #999;padding:6px 12px;background:#eef3f2;"><b>העסק</b></td>
<td style="border:1px solid #999;padding:6px 12px;background:#eef3f2;"><b>זרם</b></td>
<td style="border:1px solid #999;padding:6px 12px;background:#eef3f2;"><b>מה חסר ומה לעשות</b></td></tr>
{rows}</table>
<p>אחרי שתעדכני בקובץ — אין צורך לעשות דבר נוסף. ההזנה תושלם לבד
בסיבוב השעתי הבא (בין 07:00 ל-18:00).</p></div>"""
        try:
            emailed = send_office_email(
                subject=("מסד ההצהרות — הצהרה אחת ממתינה לך" if n == 1
                         else f"מסד ההצהרות — {n} הצהרות ממתינות לך"), html=html)
        except Exception as exc:
            current_app.logger.error("masad-feed alert email failed: %s", exc)

    return jsonify({"ok": True, "updated": updated, "alert_emailed": emailed})
