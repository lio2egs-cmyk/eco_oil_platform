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
from .file_gate import signed_file_url, storage_configured

depot_daily = Blueprint("depot_daily", __name__)

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
    if not storage_configured():
        return jsonify(error="storage not configured"), 503
    # תמיד הורדה (attachment) — הקובץ מיועד לטעינה לפריוריטי, לא לצפייה בדפדפן.
    # 09/09 (ישקר): הקישור על הדומיין שלנו, לא ישירות לאחסון — file_gate.
    return jsonify({"url": signed_file_url(r.b2_key, r.file_name, "attachment",
                                           content_type=XLSX_MIME)})


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
