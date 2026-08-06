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

from flask import Blueprint, request, jsonify
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
