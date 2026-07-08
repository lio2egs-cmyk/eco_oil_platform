# -*- coding: utf-8 -*-
"""Field-terminals relay (מסופוני שטח) — the cloud mailbox between yard tablets
and the office bridge.

Design (decided with Limor 08/07/2026):
- Tablets (SIM) capture PHYSICAL facts only: asset, event, time, photos,
  wash treatments. Commercial fields are completed at the office.
- The cloud stores and relays; it decides nothing. The office bridge polls,
  files photos per the filing rules, posts rows to the live workbook
  sequentially, then acks — photo bytes are purged on ack.

Auth:
- Terminal endpoints: per-device bearer token (FieldDevice.token).
- Bridge endpoints: FIELD_BRIDGE_TOKEN env var.
- Device management: admin JWT (same admin as the portal).
"""
import json
import os
import secrets
from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from .db import db, FieldDevice, FieldEvent, FieldPhoto, FieldOnsiteAsset

field = Blueprint("field", __name__, url_prefix="/field/api")

MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PHOTOS_PER_EVENT = 12
EVENT_TYPES = {"entry", "wash", "exit"}
ASSET_TYPES = {"iso", "rt"}


# --------------------------------------------------------------------- auth
def _bearer_token():
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.startswith("Bearer ") else None


def device_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        tok = _bearer_token()
        device = FieldDevice.query.filter_by(token=tok, active=True).first() if tok else None
        if device is None:
            return jsonify({"error": "unauthorized"}), 401
        device.last_seen_at = datetime.utcnow()
        db.session.commit()
        return f(device, *args, **kwargs)
    return wrapper


def bridge_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        expected = os.environ.get("FIELD_BRIDGE_TOKEN")
        if not expected or _bearer_token() != expected:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


def _admin_only():
    claims = get_jwt()
    return claims.get("role") == "admin"


# ---------------------------------------------------- device management (admin)
@field.route("/devices", methods=["POST"])
@jwt_required()
def create_device():
    if not _admin_only():
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    worker = (data.get("worker_name") or "").strip()
    if not worker:
        return jsonify({"error": "worker_name required"}), 400
    device = FieldDevice(worker_name=worker, token=secrets.token_hex(24))
    db.session.add(device)
    db.session.commit()
    return jsonify({"id": device.id, "worker_name": worker, "token": device.token}), 201


@field.route("/devices", methods=["GET"])
@jwt_required()
def list_devices():
    if not _admin_only():
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"devices": [
        {"id": d.id, "worker_name": d.worker_name, "active": d.active,
         "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None}
        for d in FieldDevice.query.all()]})


@field.route("/devices/<int:device_id>", methods=["DELETE"])
@jwt_required()
def deactivate_device(device_id):
    if not _admin_only():
        return jsonify({"error": "forbidden"}), 403
    d = db.session.get(FieldDevice, device_id)
    if d is None:
        return jsonify({"error": "not found"}), 404
    d.active = False
    db.session.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------- terminal side
@field.route("/events", methods=["POST"])
@device_required
def submit_event(device):
    """Multipart form: 'event' JSON field + photo files (any field name).
    Idempotent by client_uuid — a resend of the same event returns 200, not a dup."""
    try:
        meta = json.loads(request.form.get("event") or "{}")
    except ValueError:
        return jsonify({"error": "bad event json"}), 400

    uuid = (meta.get("client_uuid") or "").strip()
    etype = meta.get("event_type")
    atype = meta.get("asset_type")
    if not uuid or etype not in EVENT_TYPES or atype not in ASSET_TYPES:
        return jsonify({"error": "missing/invalid client_uuid, event_type or asset_type"}), 400

    existing = FieldEvent.query.filter_by(client_uuid=uuid).first()
    if existing is not None:
        return jsonify({"ok": True, "id": existing.id, "duplicate": True}), 200

    try:
        event_at = datetime.fromisoformat(meta.get("event_at"))
    except (TypeError, ValueError):
        event_at = datetime.utcnow()

    ev = FieldEvent(
        client_uuid=uuid,
        device_id=device.id,
        worker_name=device.worker_name,
        event_type=etype,
        asset_type=atype,
        tank_number=(meta.get("tank_number") or "").strip().upper() or None,
        event_at=event_at,
        payload=json.dumps(meta.get("payload") or {}, ensure_ascii=False),
    )
    db.session.add(ev)
    db.session.flush()

    n = 0
    for f in request.files.values():
        if n >= MAX_PHOTOS_PER_EVENT:
            break
        blob = f.read(MAX_PHOTO_BYTES + 1)
        if not blob or len(blob) > MAX_PHOTO_BYTES:
            continue
        kind = "plate" if f.name == "plate" else "photo"
        db.session.add(FieldPhoto(event_id=ev.id, kind=kind,
                                  filename=f.filename or f"photo{n}.jpg",
                                  mime=f.mimetype or "image/jpeg",
                                  data=blob, size=len(blob)))
        n += 1

    db.session.commit()
    return jsonify({"ok": True, "id": ev.id, "photos": n}), 201


@field.route("/onsite", methods=["GET"])
@device_required
def onsite_assets(device):
    """The wash/exit dropdown: assets currently on site (pushed by the bridge)."""
    atype = request.args.get("asset_type")
    q = FieldOnsiteAsset.query
    if atype in ASSET_TYPES:
        q = q.filter_by(asset_type=atype)
    return jsonify({"assets": [
        {"asset_type": a.asset_type, "tank_number": a.tank_number,
         "customer": a.customer, "status": a.status}
        for a in q.order_by(FieldOnsiteAsset.tank_number).all()]})


@field.route("/events/status", methods=["GET"])
@device_required
def events_status(device):
    """Terminal polls this to show the worker green 'נקלט במשרד' checkmarks."""
    uuids = [u for u in (request.args.get("uuids") or "").split(",") if u][:50]
    rows = FieldEvent.query.filter(FieldEvent.client_uuid.in_(uuids)).all() if uuids else []
    return jsonify({"events": {
        r.client_uuid: {"status": r.status, "note": r.bridge_note} for r in rows}})


# --------------------------------------------------------------- bridge side
@field.route("/bridge/pending", methods=["GET"])
@bridge_required
def bridge_pending():
    rows = (FieldEvent.query.filter(FieldEvent.status.in_(("pending", "fetched")))
            .order_by(FieldEvent.id).limit(50).all())
    out = []
    for r in rows:
        r.status = "fetched"
        out.append({
            "id": r.id, "client_uuid": r.client_uuid, "worker_name": r.worker_name,
            "event_type": r.event_type, "asset_type": r.asset_type,
            "tank_number": r.tank_number, "event_at": r.event_at.isoformat(),
            "payload": json.loads(r.payload or "{}"),
            "photos": [{"id": p.id, "kind": p.kind, "filename": p.filename,
                        "mime": p.mime, "size": p.size} for p in r.photos],
        })
    db.session.commit()
    return jsonify({"events": out})


@field.route("/bridge/photo/<int:photo_id>", methods=["GET"])
@bridge_required
def bridge_photo(photo_id):
    p = db.session.get(FieldPhoto, photo_id)
    if p is None or p.data is None:
        return jsonify({"error": "not found"}), 404
    return p.data, 200, {"Content-Type": p.mime or "image/jpeg"}


@field.route("/bridge/ack", methods=["POST"])
@bridge_required
def bridge_ack():
    """Body: {"events": [{"id": 1, "status": "posted"|"error",
                          "tank_number": "...", "note": "..."}]}
    On 'posted' the photo bytes are purged (they now live on O:)."""
    data = request.get_json(silent=True) or {}
    done = 0
    for item in data.get("events", []):
        ev = db.session.get(FieldEvent, item.get("id"))
        if ev is None:
            continue
        status = item.get("status")
        if status not in ("posted", "error"):
            continue
        ev.status = status
        ev.bridge_note = (item.get("note") or "")[:400]
        if item.get("tank_number"):
            ev.tank_number = str(item["tank_number"]).strip().upper()
        if status == "posted":
            ev.posted_at = datetime.utcnow()
            for p in ev.photos:
                p.data = None
        done += 1
    db.session.commit()
    return jsonify({"ok": True, "updated": done})


@field.route("/bridge/onsite", methods=["POST"])
@bridge_required
def bridge_onsite():
    """Wholesale replace of the on-site assets snapshot.
    Body: {"assets": [{"asset_type": "iso", "tank_number": "...", "customer": "...", "status": "..."}]}"""
    data = request.get_json(silent=True) or {}
    assets = data.get("assets")
    if not isinstance(assets, list):
        return jsonify({"error": "assets list required"}), 400
    FieldOnsiteAsset.query.delete()
    now = datetime.utcnow()
    for a in assets[:2000]:
        tank = (a.get("tank_number") or "").strip()
        if not tank or a.get("asset_type") not in ASSET_TYPES:
            continue
        db.session.add(FieldOnsiteAsset(
            asset_type=a["asset_type"], tank_number=tank,
            customer=(a.get("customer") or "")[:200],
            status=(a.get("status") or "")[:60], updated_at=now))
    db.session.commit()
    return jsonify({"ok": True})
