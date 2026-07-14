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


def _client_for_request():
    claims = get_jwt()
    client_id = claims.get("client_id")
    if claims.get("role") == "admin" and request.args.get("client_id"):
        client_id = int(request.args["client_id"])
    return db.session.get(Client, client_id) if client_id else None


def _scoped_query(client_name):
    billed = EcoOilUnloadEvent.query.filter(EcoOilUnloadEvent.billed_to == client_name)
    if db.session.query(billed.exists()).scalar():
        return billed, "billed"
    return (EcoOilUnloadEvent.query.filter(EcoOilUnloadEvent.customer == client_name),
            "source")


@ecooil_docs.route("/my-documents", methods=["GET"])
@jwt_required()
def my_documents():
    client = _client_for_request()
    if client is None:
        return jsonify({"error": "no client"}), 403
    q, mode = _scoped_query(client.name)

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
            "has_pdf": bool(r.pdf_key),
        } for r in rows],
    })


@ecooil_docs.route("/my-documents/<int:event_id>/download", methods=["GET"])
@jwt_required()
def download(event_id):
    client = _client_for_request()
    if client is None:
        return jsonify({"error": "no client"}), 403
    q, _mode = _scoped_query(client.name)
    ev = q.filter(EcoOilUnloadEvent.id == event_id).first()
    if ev is None:
        return jsonify({"error": "not found"}), 404
    if not ev.pdf_key:
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
    fname = quote(ev.pdf_key.rsplit("/", 1)[-1])
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["B2_BUCKET_CERTS"], "Key": ev.pdf_key,
                "ResponseContentDisposition": f"attachment; filename*=UTF-8''{fname}"},
        ExpiresIn=PRESIGN_SECONDS,
    )
    return jsonify({"url": url})
