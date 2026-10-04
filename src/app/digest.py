# -*- coding: utf-8 -*-
"""Weekly login digest — a summary email to the office of all portal login
activity (Limor's request 2026-07-29: no per-login noise, one weekly overview).

Triggered by POST /admin/weekly-login-digest from a scheduled task on the office
PC (same pattern as the hourly bridge). Auth: ECOOIL_BRIDGE_TOKEN bearer.
Email is sent over the existing Resend channel (Railway blocks SMTP).
"""
import os
from datetime import datetime, timedelta, timezone
from difflib import get_close_matches
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import func, or_

from .db import db, User, Client, LoginAuditLog, MagicLinkToken
from .ecooil_bridge import ecooil_bridge_required

digest = Blueprint("digest", __name__)

DIGEST_TO = "office@eco-oil.co.il"


IL_TZ = ZoneInfo("Asia/Jerusalem")


def _fmt(dt):
    """DB timestamps are naive UTC; the office reads Israel time (Limor 04/10/2026)."""
    if not dt:
        return ""
    return dt.replace(tzinfo=timezone.utc).astimezone(IL_TZ).strftime("%d/%m/%Y %H:%M")


def _unknown_note(em, by_email):
    """Why an 'unknown' address is in the list (Limor 04/10/2026: the same
    address showed in both tables and it read as a contradiction)."""
    u = by_email.get(em)
    if u and u.is_active:
        if u.last_login_at:
            return "נפתח חשבון בינתיים — נכנס בהצלחה"
        return "נפתח חשבון בינתיים — טרם נכנס"
    if u:
        return "חשבון קיים אך לא פעיל"
    close = get_close_matches(em, [e for e in by_email if by_email[e].is_active], n=1, cutoff=0.88)
    if close:
        return f"כנראה שגיאת הקלדה של {close[0]}"
    return "אין חשבון"


@digest.route("/admin/user-login-diagnosis", methods=["POST"])
@ecooil_bridge_required
def user_login_diagnosis():
    """Per-user login forensics (Limor's "she says she can't get in" tool,
    16/08/2026 — first case: Nataliya/אורות פנינה). Given an email, returns the
    user record, their recent magic-link tokens, and every audit event for that
    address — so "never asked for a link" vs "asked but never clicked" vs
    "clicked and failed" is answered from data, not guesses. Bridge-token auth,
    read-only."""
    email = (request.get_json(silent=True) or {}).get("email", "").strip().lower()
    if not email or "@" not in email:
        return jsonify(error="email is required"), 400

    user = User.query.filter(func.lower(User.email) == email).first()
    user_info = None
    links = []
    if user:
        client = Client.query.get(user.client_id) if user.client_id else None
        user_info = {
            "id": user.id, "email": user.email, "role": user.role,
            "is_active": bool(user.is_active),
            "client_id": user.client_id,
            "client_name": client.name if client else None,
            "client_division": client.division if client else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        }
        links = [{
            "created_at": t.created_at.isoformat(),
            "expires_at": t.expires_at.isoformat(),
            "used_at": t.used_at.isoformat() if t.used_at else None,
            "requested_from_ip": t.requested_from_ip,
        } for t in (MagicLinkToken.query.filter_by(user_id=user.id)
                    .order_by(MagicLinkToken.created_at.desc()).limit(15).all())]

    conds = [func.lower(LoginAuditLog.email_attempted) == email]
    if user:
        conds.append(LoginAuditLog.user_id == user.id)
    events = [{
        "created_at": l.created_at.isoformat(),
        "event_type": l.event_type,
        "success": bool(l.success),
        "ip_address": l.ip_address,
        "user_agent": l.user_agent,
        "notes": l.notes,
    } for l in (LoginAuditLog.query.filter(or_(*conds))
                .order_by(LoginAuditLog.created_at.desc()).limit(200).all())]

    return jsonify({"queried_email": email, "user": user_info,
                    "magic_links": links, "audit_events": events})


@digest.route("/admin/weekly-login-digest", methods=["POST"])
@ecooil_bridge_required
def weekly_login_digest():
    body = request.get_json(silent=True) or {}
    days = int(body.get("days", 7))
    dry_run = bool(body.get("dry_run"))
    since = datetime.utcnow() - timedelta(days=days)
    logs = (LoginAuditLog.query.filter(LoginAuditLog.created_at >= since)
            .order_by(LoginAuditLog.created_at).all())

    per_user = {}
    unknown = {}
    for l in logs:
        if l.user_id:
            d = per_user.setdefault(l.user_id, {"req": 0, "ok": 0, "fail": 0, "last": None})
            if l.event_type == "magic_link_requested":
                d["req"] += 1
            elif l.event_type == "magic_link_verified" and l.success:
                d["ok"] += 1
                d["last"] = l.created_at
            elif not l.success:
                d["fail"] += 1
        elif l.email_attempted:
            em = l.email_attempted.strip().lower()
            unknown[em] = unknown.get(em, 0) + 1

    users = {u.id: u for u in User.query.filter(User.id.in_(per_user.keys())).all()} if per_user else {}
    clients = {c.id: c.name for c in Client.query.all()}
    new_users = User.query.filter(User.role.in_(("eco_oil_client", "eco_depot_client", "transport_company"))).count()

    rows_html = ""
    active = 0
    for uid, d in sorted(per_user.items(), key=lambda kv: -(kv[1]["ok"] + kv[1]["req"])):
        u = users.get(uid)
        if not u:
            continue
        active += 1
        comp = clients.get(u.client_id, "")
        rows_html += (
            f"<tr><td>{comp}</td><td>{u.email}</td><td>{d['req']}</td>"
            f"<td>{d['ok']}</td><td>{d['fail']}</td><td>{_fmt(d['last'])}</td></tr>"
        )
    if not rows_html:
        rows_html = '<tr><td colspan="6">לא הייתה פעילות כניסה השבוע</td></tr>'

    unknown_html = ""
    if unknown:
        by_email = {(u.email or "").strip().lower(): u
                    for u in User.query.filter(User.email.isnot(None)).all()}
        for em, n in sorted(unknown.items(), key=lambda kv: -kv[1]):
            unknown_html += f"<tr><td>{em}</td><td>{n}</td><td>{_unknown_note(em, by_email)}</td></tr>"

    total_ok = sum(d["ok"] for d in per_user.values())
    total_req = sum(d["req"] for d in per_user.values())
    period = f"{_fmt(since)[:10]} — {_fmt(datetime.utcnow())[:10]}"

    td = "border:1px solid #999;padding:6px 10px;text-align:right;"
    th = td + "background:#D9E2F3;font-weight:bold;"
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;font-size:14px;color:#222;">
<h2 style="color:#2F6B62;">סיכום כניסות שבועי — פורטל הלקוחות</h2>
<p>תקופה: {period} · סה"כ בקשות קישור: <b>{total_req}</b> · כניסות מוצלחות: <b>{total_ok}</b> · משתמשים פעילים: <b>{active}</b> · סה"כ חשבונות לקוח במערכת: <b>{new_users}</b></p>
<table style="border-collapse:collapse;">
<tr><th style="{th}">חברה</th><th style="{th}">מייל</th><th style="{th}">בקשות קישור</th><th style="{th}">כניסות</th><th style="{th}">כשלונות</th><th style="{th}">כניסה אחרונה</th></tr>
{rows_html.replace('<td>', f'<td style="{td}">')}
</table>"""
    if unknown_html:
        html += f"""<h3 style="color:#B45309;">נסיונות כניסה של מיילים לא מוכרים</h3>
<table style="border-collapse:collapse;">
<tr><th style="{th}">מייל</th><th style="{th}">נסיונות</th><th style="{th}">הסבר</th></tr>
{unknown_html.replace('<td>', f'<td style="{td}">')}
</table>"""
    html += "<p style='color:#777;'>השעות לפי שעון ישראל. נשלח אוטומטית על ידי פורטל אקו-אויל.</p></div>"

    if dry_run:
        return jsonify({"sent": False, "dry_run": True, "html": html})

    resend_key = os.environ.get("RESEND_API_KEY")
    from_addr = os.environ.get("MAIL_FROM_ADDRESS", os.environ.get("MAIL_USERNAME", ""))
    from_name = os.environ.get("MAIL_FROM_NAME", "")
    sent = False
    if resend_key and from_addr:
        from email.utils import formataddr
        import requests as _rq
        r = _rq.post(
            "https://api.resend.com/emails",
            headers={"Authorization": "Bearer " + resend_key},
            json={
                "from": formataddr((from_name, from_addr)) if from_name else from_addr,
                "to": [DIGEST_TO],
                "subject": "סיכום כניסות שבועי — פורטל הלקוחות",
                "html": html,
            },
            timeout=20,
        )
        sent = r.status_code < 300
        if not sent:
            current_app.logger.error("weekly digest send failed: %s %s", r.status_code, r.text[:200])
    else:
        current_app.logger.info("weekly digest (no mail channel): %d active users", active)

    return jsonify({"sent": sent, "active_users": active, "total_logins": total_ok,
                    "total_requests": total_req, "unknown_attempts": len(unknown)})
