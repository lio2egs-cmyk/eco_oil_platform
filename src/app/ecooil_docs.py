# -*- coding: utf-8 -*-
""""המסמכים שלי" — Eco-Oil customer documents API.

Scoping (Limor's ruling 2026-07-13): an account sees rows where THEY are the
billed party (חיוב); an end-customer login (on request) sees rows where they
are the לקוח (source). Mode picked automatically: billed rows exist → billed
view; otherwise source view. Downloads are served as short-lived presigned B2
URLs — the bucket stays private.
"""
import os
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy import func, or_

from .db import db, Client, EcoOilUnloadEvent

ecooil_docs = Blueprint("ecooil_docs", __name__, url_prefix="/eco-oil")

PRESIGN_SECONDS = 300

# doc_status values that withhold the filed documents from the customer
# (Limor's ריכוז column "הערות למערכת פורטל", 30/07/2026):
# awaiting_declaration → orange legal notice + declaration button;
# unpublished → nothing shown, no explanation.
WITHHELD_STATUSES = {"awaiting_declaration", "unpublished"}


def _client_for_request():
    claims = get_jwt()
    client_id = claims.get("client_id")
    if claims.get("role") == "admin" and request.args.get("client_id"):
        client_id = int(request.args["client_id"])
    return db.session.get(Client, client_id) if client_id else None


def _scoped_query(client):
    """All billed names the client owns: primary name + billing_aliases
    (former names, absorbed companies, per-site names, spelling variants).
    A parenthetical billed row like 'X (customer)' belongs to X (rule 21/07)."""
    names = client.billed_names()
    billed_match = or_(
        EcoOilUnloadEvent.billed_to.in_(names),
        *[EcoOilUnloadEvent.billed_to.like(n + " (%") for n in names],
    )
    billed = EcoOilUnloadEvent.query.filter(billed_match)
    if db.session.query(billed.exists()).scalar():
        return billed, "billed"
    return (EcoOilUnloadEvent.query.filter(EcoOilUnloadEvent.customer.in_(names)),
            "source")


@ecooil_docs.route("/my-documents", methods=["GET"])
@jwt_required()
def my_documents():
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
