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
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required

from .db import db, Client, DepotDailyReport, User
from .depot_certs import _folder_client_map, _norm
from .depot_portal import _depot_client_for_request
from .ecooil_bridge import ecooil_bridge_required
from .file_gate import _s3, signed_file_url, storage_configured
from .mailer import send_office_email

depot_daily = Blueprint("depot_daily", __name__)

LIST_LIMIT = 30
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# ── מייל הבוקר האוטומטי (לימור 14/09/2026) ──────────────────────────────
# דוח שנרשם בפורטל נשלח כצרופה לאנשי הקשר של הלקוח שסומנו "דוח יומי במייל".
# נשלח רק דוח שנרשם ב-24 השעות האחרונות (כדי שסימון איש קשר היום לא ישלח
# לו דוחות של ימים קודמים) ושתאריכו בחלון של המחולל (אתמול..4 ימים אחורה).
# פעם אחת בלבד — mailed_at. יום בלי פעילות = אין קובץ = אין מייל.
MAIL_WINDOW_DAYS = 4
MAIL_FRESH_HOURS = 24


def _daily_mail_content(client_name, report_date):
    """הנוסח שאושר ע"י לימור 14/09/2026 — לא לשנות בלי לשאול אותה."""
    d = report_date.strftime("%d/%m/%Y") if report_date else ""
    subject = f"דוח פעילות יומי אקו-דיפו — {client_name} — {d}"
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;font-size:15px;line-height:1.7">
<p>שלום,</p>
<p>מצורף דוח הפעילות היומי של אתמול ({d}), באותו מבנה כמו בפורטל.</p>
<p>בברכה,<br>צוות אקו-דיפו</p></div>"""
    text = (f"שלום,\nמצורף דוח הפעילות היומי של אתמול ({d}), באותו מבנה כמו בפורטל.\n"
            "בברכה, צוות אקו-דיפו")
    return subject, html, text


def _daily_mail_recipients(client):
    return [u for u in User.query.filter_by(client_id=client.id,
                                            role="eco_depot_client").all()
            if u.email and u.is_active and u.daily_report_mail]


def _fetch_report_bytes(b2_key):
    obj = _s3().get_object(Bucket=os.environ["B2_BUCKET_CERTS"], Key=b2_key)
    return obj["Body"].read()


def mail_pending_daily_reports(dry_run=False, only_ids=None):
    """שולח את הדוחות הטריים שטרם נשלחו. מוחזר דוח פעולה לכל דוח.
    דוח שלא נשלח (תיקייה לא מזוהה / אין נמענים / כשל) נשאר לא-מוחתם ומנוסה
    שוב בדחיפה השעתית הבאה, עד שיוצא מחלון 24 השעות."""
    now = datetime.utcnow()
    q = (DepotDailyReport.query
         .filter(DepotDailyReport.mailed_at.is_(None),
                 DepotDailyReport.created_at >= now - timedelta(hours=MAIL_FRESH_HOURS),
                 DepotDailyReport.report_date >= date.today() - timedelta(days=MAIL_WINDOW_DAYS)))
    if only_ids is not None:
        if not only_ids:
            return []
        q = q.filter(DepotDailyReport.id.in_(list(only_ids)))
    fmap = _folder_client_map()
    out = []
    for r in q.order_by(DepotDailyReport.report_date, DepotDailyReport.id).all():
        item = {"id": r.id, "folder": r.folder, "file": r.file_name,
                "report_date": r.report_date.isoformat() if r.report_date else None}
        c = fmap.get(_norm(r.folder))
        if c is None:
            item["result"] = "תיקייה לא מזוהה"
            out.append(item)
            continue
        recips = _daily_mail_recipients(c)
        item["client"] = c.name
        item["recipients"] = [u.email for u in recips]
        if not recips:
            item["result"] = "אין נמענים מסומנים"
            out.append(item)
            continue
        if dry_run:
            item["result"] = "dry_run"
            out.append(item)
            continue
        try:
            data = _fetch_report_bytes(r.b2_key)
        except Exception as exc:
            current_app.logger.error("daily-report mail: fetch failed %s: %s", r.b2_key, exc)
            item["result"] = "כשל בהבאת הקובץ"
            out.append(item)
            continue
        subject, html, text = _daily_mail_content(c.name, r.report_date)
        sent, failed = [], []
        for u in recips:
            ok = send_office_email(subject=subject, html=html, text=text, to=u.email,
                                   attachments=[(r.file_name, data, XLSX_MIME)])
            (sent if ok else failed).append(u.email)
        if sent:
            r.mailed_at = now
            r.mailed_to = ", ".join(sent) + (f" | נכשל: {', '.join(failed)}" if failed else "")
        item["sent"], item["failed"] = sent, failed
        item["result"] = "נשלח" if sent and not failed else ("נשלח חלקית" if sent else "כשל בשליחה")
        out.append(item)
    if not dry_run:
        db.session.commit()
    return out


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
    new_rows = []
    for it in items:
        key = (it.get("b2_key") or "").strip()
        if not key:
            continue
        r = DepotDailyReport.query.filter_by(b2_key=key).first()
        if r is None:
            r = DepotDailyReport(b2_key=key, created_at=now)
            db.session.add(r)
            new_rows.append(r)
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
    # מייל הבוקר: הדוחות שנרשמו הרגע יוצאים מיד לנמענים המסומנים. כשל
    # במייל לעולם לא מכשיל את הרישום — הדוח כבר בפורטל, והשליחה תנוסה
    # שוב בדחיפה הבאה.
    mailed = []
    if new_rows:
        try:
            mailed = mail_pending_daily_reports(only_ids=[r.id for r in new_rows])
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error("daily-report mail failed: %s", exc)
    return jsonify(ok=True, added=added, updated=updated, mailed=mailed)


@depot_daily.route("/depot/portal/bridge/daily-reports/mail", methods=["POST"])
@ecooil_bridge_required
def bridge_mail_daily_reports():
    """הפעלה ידנית / בדיקה של מייל הבוקר: dry_run=true מראה מה היה נשלח למי,
    בלי לשלוח ובלי להחתים. בלי dry_run — שולח את הטריים שטרם נשלחו."""
    body = request.get_json(silent=True) or {}
    dry = bool(body.get("dry_run"))
    return jsonify(ok=True, dry_run=dry, items=mail_pending_daily_reports(dry_run=dry))
