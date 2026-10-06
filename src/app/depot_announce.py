# -*- coding: utf-8 -*-
"""הודעה אחת לכל משתמשי פורטל הדיפו (לימור 06/10/2026: "לא עדיף מייל אוטומטי
לכולם דרך הפורטל, כמו הדוחות היומיים?").

אותו ערוץ כמו מייל הבוקר: שולח portal@ (Resend), מייל אחד לכל איש קשר פעיל
עם כתובת, בכל חברות הדיפו (חברת הבדיקה מוחרגת). הנוסח מגיע מהמשרד בקריאה
(הסקריפט depot_announce.py קורא קובץ טקסט שלימור אישרה) — אין נוסח בקוד.

שני שלבים תמיד: dry_run=true מחזיר את רשימת הנמענים לפי חברה בלי לשלוח;
רק אחרי שלימור ראתה את הרשימה ואמרה "שלחי" — שליחה אמיתית. כל שליחה נרשמת
ביומן הפעולות של מסך הניהול.
"""
import html as _html
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from .db import db, AdminActionLog, Client, User
from .ecooil_bridge import ecooil_bridge_required
from .mailer import send_office_email

depot_announce = Blueprint("depot_announce", __name__)

TEST_CLIENT_NAMES = {"בדיקה - פורטל"}


def _recipients(only_emails=None):
    """אנשי הקשר הפעילים עם כתובת, בחברות הדיפו האמיתיות. [(client_name, user)]."""
    only = {e.strip().lower() for e in (only_emails or []) if e and e.strip()}
    out = []
    for u in (User.query.filter_by(role="eco_depot_client", is_active=True)
              .order_by(User.client_id, User.id).all()):
        if not u.email:
            continue
        if only and u.email.lower() not in only:
            continue
        c = db.session.get(Client, u.client_id or 0)
        if c is None or c.division != "eco_depot" or c.name in TEST_CLIENT_NAMES:
            continue
        out.append((c.name, u))
    return out


def _wrap(text):
    """טקסט פשוט → HTML באותו עיצוב כמו מייל הבוקר (RTL, Arial, שורות = פסקאות)."""
    paras = "".join(f"<p>{_html.escape(p).replace(chr(10), '<br>')}</p>"
                    for p in text.strip().split("\n\n") if p.strip())
    return (f'<div dir="rtl" style="font-family:Arial,sans-serif;font-size:15px;line-height:1.7">'
            f'{paras}</div>')


@depot_announce.route("/depot/portal/bridge/announce", methods=["POST"])
@ecooil_bridge_required
def bridge_announce():
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject") or "").strip()[:200]
    text = (body.get("text") or "").strip()
    dry = bool(body.get("dry_run", True))
    if not subject or not text:
        return jsonify(error="subject and text required"), 400
    recips = _recipients(body.get("only_emails"))
    by_client = {}
    for name, u in recips:
        by_client.setdefault(name, []).append(u.email)
    if dry:
        return jsonify(ok=True, dry_run=True, subject=subject, count=len(recips),
                       recipients=by_client, html=_wrap(text))

    html = _wrap(text)
    sent, failed = [], []
    for name, u in recips:
        try:
            ok = send_office_email(subject=subject, html=html, text=text, to=u.email)
        except Exception as exc:
            current_app.logger.error("announce: send to %s failed: %s", u.email, exc)
            ok = False
        (sent if ok else failed).append(u.email)
    db.session.add(AdminActionLog(
        actor="portal@ (הודעה לכל הלקוחות)", division="eco_depot", action="announce",
        details=(f"{subject} — נשלח ל-{len(sent)}" + (f", נכשל: {', '.join(failed)}" if failed else ""))[:400]))
    db.session.commit()
    return jsonify(ok=True, dry_run=False, subject=subject, sent=sent, failed=failed,
                   at=datetime.utcnow().isoformat())
