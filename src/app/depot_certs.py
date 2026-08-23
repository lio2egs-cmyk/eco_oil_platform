# -*- coding: utf-8 -*-
"""פורטל הדיפו — שלב 2 במפת הדרכים (לימור 23/08/2026): תעודות שטיפה.

המחליף של שליחת התעודות במייל ע"י המשרד. הסקריפט השעתי במחשב של לימור
(depot_certs_push.py) סורק את O:\\SHTIFOT\\תעודות שטיפה — קריאה בלבד,
2026 ואילך (הכרעתה 23/08) — מעלה קבצי PDF חדשים ל-B2 ודוחף את הרישום לכאן.

עקרון השיוך = עוגן תיקיית התיוק (הכרעת 06/08 באויל, חלה גם כאן): התיקייה
שבה מתויקת התעודה קובעת איזה לקוח רואה אותה. תיקייה נפתרת לכרטיס חברה
לפי שם + כתיבים (billing_aliases) בהשוואה מנורמלת — שוויון בלבד, אף פעם
לא ניחוש. תיקייה לא מזוהה לא מוצגת לאף לקוח, ומופיעה במסך ניהול הדיפו
כדי ששום תעודה לא תיעלם בשקט.

הסיכום היומי (הכרעת 23/08): מייל אחד ביום לכל לקוח שהצטברו לו תעודות
חדשות — לא מייל על כל תעודה. ההטענה ההיסטורית מוחתמת מראש כך שהמייל
הראשון סופר רק תעודות שנוצרו אחרי העלייה לאוויר.
"""
import os
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required

from .auth import depot_admin_required
from .db import db, Client, DepotWashCert, User
from .depot_portal import _depot_client_for_request
from .ecooil_bridge import ecooil_bridge_required
from .mailer import send_office_email

depot_certs = Blueprint("depot_certs", __name__)

PRESIGN_SECONDS = 300
# תעודה "חדשה" לצורך הסיכום היומי: חותמת קובץ בימים האחרונים. כל מה שישן
# יותר מוחתם בשקט — כך גם הטענה היסטורית גדולה לא מציפה אף אחד במייל.
DIGEST_FRESH_DAYS = 4


def _norm(s):
    """אותו מתכון נרמול כמו בצד האויל (_norm_name) — שוויון בלבד."""
    if not s:
        return ""
    s = str(s)
    s = s.replace('"', "").replace("'", "").replace("_", " ").replace("-", " ")
    s = re.sub(r"בע\s*מ", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def _folder_client_map():
    """norm(שם/כתיב) → Client, ללקוחות דיפו בלבד. התנגשות בין שתי חברות על
    אותו כתיב — הכתיב מושמט (דו-משמעות לא מנוחשת, כמו באויל)."""
    mapping, clash = {}, set()
    for c in Client.query.filter_by(division="eco_depot").all():
        names = c.billed_names()
        for n in names:
            key = _norm(n)
            if not key:
                continue
            if key in mapping and mapping[key].id != c.id:
                clash.add(key)
                continue
            mapping.setdefault(key, c)
    for key in clash:
        mapping.pop(key, None)
    return mapping


def _client_folders(client):
    """כל שמות התיקיות בטבלת התעודות שנפתרים לכרטיס הזה."""
    keys = {_norm(client.name)} | {_norm(n) for n in client.billed_names()}
    keys.discard("")
    folders = [r[0] for r in db.session.query(DepotWashCert.folder).distinct()]
    return [f for f in folders if _norm(f) in keys]


def _cert_dict(r):
    return {
        "id": r.id,
        "tank": r.tank or "",
        "year": r.year,
        "month": r.month,
        "file_name": r.file_name,
        "file_date": r.file_date.isoformat() if r.file_date else None,
    }


# ------------------------------------------------------------ customer side
@depot_certs.route("/depot/portal/my-certs", methods=["GET"])
@jwt_required()
def my_certs():
    client = _depot_client_for_request()
    # מבט-מנהלת בעיני הלקוח (?client_id=) — הלקח מ-17/08: אין לבנות מסך
    # לקוח בלי שללימור/יעל יש דרך לראות בדיוק את מה שהלקוח רואה.
    preview = None
    if client is None:
        claims = get_jwt()
        cid = request.args.get("client_id", type=int)
        if claims.get("role") in ("admin", "depot_admin") and cid:
            c = db.session.get(Client, cid)
            if c is not None and c.division == "eco_depot":
                client, preview = c, {"client_id": c.id, "client_name": c.name}
    if client is None:
        return jsonify(error="depot customers only"), 403

    folders = _client_folders(client)
    rows = []
    if folders:
        rows = (DepotWashCert.query
                .filter(DepotWashCert.folder.in_(folders))
                .order_by(DepotWashCert.file_date.desc().nullslast(),
                          DepotWashCert.id.desc())
                .all())
    out = {"certs": [_cert_dict(r) for r in rows]}
    if preview:
        out["preview"] = preview
    return jsonify(out)


@depot_certs.route("/depot/portal/my-certs/<int:cert_id>/download", methods=["GET"])
@jwt_required()
def download_cert(cert_id):
    client = _depot_client_for_request()
    if client is None:
        claims = get_jwt()
        cid = request.args.get("client_id", type=int)
        if claims.get("role") in ("admin", "depot_admin") and cid:
            c = db.session.get(Client, cid)
            if c is not None and c.division == "eco_depot":
                client = c
    if client is None:
        return jsonify(error="depot customers only"), 403

    r = db.session.get(DepotWashCert, cert_id)
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
    # צפייה מול הורדה (הלקח מ-18/08): הורדה רק בבחירה מודעת, ?mode=view לצפייה.
    disp = "inline" if request.args.get("mode") == "view" else "attachment"
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["B2_BUCKET_CERTS"], "Key": r.b2_key,
                "ResponseContentDisposition":
                    f"{disp}; filename*=UTF-8''{fname}"},
        ExpiresIn=PRESIGN_SECONDS,
    )
    return jsonify({"url": url})


# ------------------------------------------------------------ bridge side
@depot_certs.route("/depot/portal/bridge/certs", methods=["POST"])
@ecooil_bridge_required
def bridge_upsert_certs():
    """הסקריפט במחשב של לימור דוחף את הרישום אחרי שהקבצים אושרו ב-B2.
    seed_notified=true (הרצת הטענה ראשונית) מחתים notified_at מיד —
    הסיכום היומי הראשון לא יספור את ההיסטוריה."""
    body = request.get_json(silent=True) or {}
    items = body.get("items") or []
    seed = bool(body.get("seed_notified"))
    now = datetime.utcnow()
    added = updated = 0
    for it in items:
        key = (it.get("b2_key") or "").strip()
        if not key:
            continue
        r = DepotWashCert.query.filter_by(b2_key=key).first()
        if r is None:
            r = DepotWashCert(b2_key=key, created_at=now)
            db.session.add(r)
            added += 1
            if seed:
                r.notified_at = now
        else:
            updated += 1
        r.folder = it.get("folder") or r.folder
        r.tank = it.get("tank") or r.tank
        r.year = it.get("year") or r.year
        r.month = it.get("month") or r.month
        r.file_name = it.get("file_name") or r.file_name
        r.size = it.get("size") or r.size
        fd = it.get("file_date")
        if fd:
            try:
                r.file_date = datetime.fromisoformat(fd)
            except ValueError:
                pass
    db.session.commit()
    return jsonify(ok=True, added=added, updated=updated)


def _digest_email(client_name, fresh):
    """נוסח הסיכום היומי — טיוטה; אושר ע"י לימור לפני השליחה האמיתית הראשונה.
    בלי קישור ישיר לפורטל — הכניסה דרך האתר בלבד (הכרעת 09/08)."""
    n = len(fresh)
    tanks = sorted({r.tank for r in fresh if r.tank})
    tanks_line = ", ".join(tanks[:12]) + ("…" if len(tanks) > 12 else "")
    subject = f"תעודות שטיפה חדשות ממתינות לכם בפורטל אקו-דיפו"
    rows = "".join(
        f"<tr><td style='border:1px solid #cbd5d3;padding:6px 10px'>{r.tank or '—'}</td>"
        f"<td style='border:1px solid #cbd5d3;padding:6px 10px'>"
        f"{r.file_date.strftime('%d/%m/%Y') if r.file_date else '—'}</td></tr>"
        for r in fresh[:25])
    more = (f"<p>ועוד {n - 25} תעודות נוספות.</p>" if n > 25 else "")
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;font-size:15px;line-height:1.7">
<p>שלום {client_name},</p>
<p>הצטברו לכם היום <b>{n} תעודות שטיפה חדשות</b> בפורטל הלקוחות של אקו-דיפו.</p>
<table style="border-collapse:collapse;font-size:14px">
<tr><th style="border:1px solid #cbd5d3;background:#EDF3F2;padding:6px 10px">מספר מכל</th>
<th style="border:1px solid #cbd5d3;background:#EDF3F2;padding:6px 10px">תאריך התעודה</th></tr>
{rows}</table>{more}
<p>לצפייה ולהורדה: נכנסים לאתר <b>www.eco-oil.co.il</b> ← "כניסת לקוחות" ←
"לקוחות אקו-דיפו" ← מקלידים את כתובת המייל ומקבלים קישור כניסה.</p>
<p>בברכה,<br>צוות אקו-דיפו</p></div>"""
    text = (f"שלום {client_name},\n"
            f"הצטברו לכם היום {n} תעודות שטיפה חדשות בפורטל אקו-דיפו"
            + (f" (מכלים: {tanks_line})" if tanks_line else "") + ".\n"
            "לצפייה ולהורדה: www.eco-oil.co.il ← כניסת לקוחות ← לקוחות אקו-דיפו.\n"
            "בברכה, צוות אקו-דיפו")
    return subject, html, text


@depot_certs.route("/depot/portal/bridge/certs-digest", methods=["POST"])
@ecooil_bridge_required
def bridge_certs_digest():
    """הסיכום היומי — מופעל פעם ביום מהמשימה השעתית במחשב של לימור.
    לכל לקוח: התעודות שטרם נכללו בסיכום. טריות (ימים אחרונים) → מייל אחד
    לכל המורשים; ישנות → מוחתמות בשקט. dry_run=true — בלי מיילים ובלי חתימה."""
    body = request.get_json(silent=True) or {}
    dry = bool(body.get("dry_run"))
    now = datetime.utcnow()
    fresh_cut = now - timedelta(days=DIGEST_FRESH_DAYS)

    pending = (DepotWashCert.query
               .filter(DepotWashCert.notified_at.is_(None))
               .all())
    fmap = _folder_client_map()
    by_client, unresolved = {}, 0
    for r in pending:
        c = fmap.get(_norm(r.folder))
        if c is None:
            unresolved += 1          # תיקייה לא מזוהה — נשארת לא-מוחתמת, תופיע במסך הניהול
            continue
        by_client.setdefault(c.id, {"client": c, "rows": []})["rows"].append(r)

    report = []
    for entry in by_client.values():
        c, rows = entry["client"], entry["rows"]
        fresh = [r for r in rows
                 if r.file_date and r.file_date >= fresh_cut]
        emails = [u.email for u in User.query.filter_by(client_id=c.id).all()
                  if u.email and u.role == "eco_depot_client"]
        sent = 0
        if fresh and emails and not dry:
            subject, html, text = _digest_email(c.name, fresh)
            for addr in emails:
                if send_office_email(subject=subject, html=html, text=text,
                                     to=addr):
                    sent += 1
        if not dry:
            for r in rows:
                r.notified_at = now
        report.append({"client": c.name, "pending": len(rows),
                       "fresh": len(fresh), "recipients": len(emails),
                       "sent": sent})
    if not dry:
        db.session.commit()
    return jsonify(ok=True, dry_run=dry, clients=report,
                   unresolved_pending=unresolved)


# ------------------------------------------------------------ admin side
@depot_certs.route("/depot/admin/certs-overview", methods=["GET"])
@depot_admin_required
def certs_overview():
    """מסך הניהול: ספירת תעודות לכל תיקייה + לאיזו חברה היא נפתרת.
    תיקייה לא מזוהה מסומנת — התעודות שלה לא מוצגות לאף לקוח עד שיוסף
    כתיב מתאים בכרטיס החברה."""
    fmap = _folder_client_map()
    agg = (db.session.query(
               DepotWashCert.folder,
               db.func.count(DepotWashCert.id),
               db.func.max(DepotWashCert.file_date))
           .group_by(DepotWashCert.folder).all())
    out = []
    for folder, count, latest in agg:
        c = fmap.get(_norm(folder))
        out.append({
            "folder": folder,
            "count": count,
            "latest": latest.isoformat() if latest else None,
            "client_id": c.id if c else None,
            "client_name": c.name if c else None,
        })
    out.sort(key=lambda x: (x["client_name"] is not None, x["folder"]))
    return jsonify(folders=out,
                   total=sum(x["count"] for x in out),
                   unrecognized=sum(1 for x in out if not x["client_name"]))
