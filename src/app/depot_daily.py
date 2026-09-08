# -*- coding: utf-8 -*-
"""פורטל הדיפו — הדוח היומי לאקסל (בקשת לקוחות הפריוריטי, לימור 08/09/2026).

טנקו והי טנק טוענים את הדוח היומי שלנו ישירות למערכת הפריוריטי שלהם —
ולכן הפורמט קדוש: הפורטל מגיש בדיוק את קובצי האקסל שהמחולל הקיים
(gen_daily_pdf.py במחשב של לימור) מפיק ומתייק בתיקיות הלקוחות. שום הפקה
מחדש בענן — קובץ אחד, מקור אמת אחד. הכפתור זמין לכל לקוחות הדיפו
(הכרעת לימור 08/09).

הצינור: depot_daily_reports_push.py (הסבב השעתי) סורק את
לקוחות\\{לקוח}\\{שנה}\\{חודש}\\דוחות יומיים\\דוח_יומי_DD-MM-YYYY.xlsx,
מעלה ל-B2 ודוחף את הרישום לכאן. השיוך ללקוח = עוגן תיקיית התיוק,
אותו מנגנון בדיוק כמו תעודות השטיפה (שם + כתיבים, שוויון בלבד).
"""
import os
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required

from .db import db, Client, DepotDailyReport
from .depot_certs import _norm
from .depot_portal import _depot_client_for_request
from .ecooil_bridge import ecooil_bridge_required

depot_daily = Blueprint("depot_daily", __name__)

PRESIGN_SECONDS = 300
LIST_LIMIT = 30
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _client_folders(client):
    """תיקיות הדוחות היומיים שנפתרות לכרטיס הזה (שם + כתיבים, כמו בתעודות)."""
    keys = {_norm(client.name)} | {_norm(n) for n in client.billed_names()}
    keys.discard("")
    folders = [r[0] for r in db.session.query(DepotDailyReport.folder).distinct()]
    return [f for f in folders if _norm(f) in keys]


def _client_or_preview():
    """הלקוח המחובר, או מבט-מנהלת בעיני הלקוח (?client_id=) — כמו במסך התעודות."""
    client = _depot_client_for_request()
    preview = None
    if client is None:
        claims = get_jwt()
        cid = request.args.get("client_id", type=int)
        if claims.get("role") in ("admin", "depot_admin") and cid:
            c = db.session.get(Client, cid)
            if c is not None and c.division == "eco_depot":
                client, preview = c, {"client_id": c.id, "client_name": c.name}
    return client, preview


# ------------------------------------------------------------ customer side
@depot_daily.route("/depot/portal/my-daily-reports", methods=["GET"])
@jwt_required()
def my_daily_reports():
    client, preview = _client_or_preview()
    if client is None:
        return jsonify(error="depot customers only"), 403

    folders = _client_folders(client)
    rows = []
    if folders:
        rows = (DepotDailyReport.query
                .filter(DepotDailyReport.folder.in_(folders))
                .order_by(DepotDailyReport.report_date.desc().nullslast(),
                          DepotDailyReport.id.desc())
                .limit(LIST_LIMIT).all())
    out = {"reports": [{
        "id": r.id,
        "report_date": r.report_date.isoformat() if r.report_date else None,
        "file_name": r.file_name,
    } for r in rows]}
    if preview:
        out["preview"] = preview
    return jsonify(out)


@depot_daily.route("/depot/portal/my-daily-reports/<int:report_id>/download",
                   methods=["GET"])
@jwt_required()
def download_daily_report(report_id):
    client, _ = _client_or_preview()
    if client is None:
        return jsonify(error="depot customers only"), 403

    r = db.session.get(DepotDailyReport, report_id)
    if r is None or r.folder not in _client_folders(client):
        return jsonify(error="not found"), 404
    for var in ("B2_KEY_ID", "B2_APP_KEY", "B2_BUCKET_CERTS", "B2_ENDPOINT"):
        if not os.environ.get(var):
            return jsonify(error="storage not configured"), 503
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        "s3", endpoint_url=f"https://{os.environ['B2_ENDPOINT']}",
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APP_KEY"],
        config=Config(signature_version="s3v4"),
    )
    from urllib.parse import quote
    fname = quote(r.file_name)
    # תמיד הורדה (attachment) — הקובץ מיועד לטעינה לפריוריטי, לא לצפייה בדפדפן
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["B2_BUCKET_CERTS"], "Key": r.b2_key,
                "ResponseContentType": XLSX_MIME,
                "ResponseContentDisposition":
                    f"attachment; filename*=UTF-8''{fname}"},
        ExpiresIn=PRESIGN_SECONDS,
    )
    return jsonify({"url": url})


# ------------------------------------------------------------ bridge side
@depot_daily.route("/depot/portal/bridge/daily-reports", methods=["POST"])
@ecooil_bridge_required
def bridge_upsert_daily_reports():
    """הסקריפט במחשב של לימור דוחף את הרישום אחרי שהקבצים אושרו ב-B2 —
    הפורטל לעולם לא מציע הורדה שאין מאחוריה קובץ (אותו עיקרון כמו התעודות)."""
    body = request.get_json(silent=True) or {}
    items = body.get("items") or []
    now = datetime.utcnow()
    added = updated = 0
    for it in items:
        key = (it.get("b2_key") or "").strip()
        if not key:
            continue
        r = DepotDailyReport.query.filter_by(b2_key=key).first()
        if r is None:
            r = DepotDailyReport(b2_key=key, created_at=now)
            db.session.add(r)
            added += 1
        else:
            updated += 1
        r.folder = it.get("folder") or r.folder
        r.file_name = it.get("file_name") or r.file_name
        r.size = it.get("size") or r.size
        rd = it.get("report_date")
        if rd:
            try:
                r.report_date = datetime.fromisoformat(rd).date()
            except ValueError:
                pass
        fd = it.get("file_date")
        if fd:
            try:
                r.file_date = datetime.fromisoformat(fd)
            except ValueError:
                pass
    db.session.commit()
    return jsonify(ok=True, added=added, updated=updated)
