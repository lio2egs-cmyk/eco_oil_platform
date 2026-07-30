# -*- coding: utf-8 -*-
"""Declaration-expiry reminders — PILOT stage (Limor's plan, approved 29-30/07/2026).

On the 15th of each month a scheduled task on the office PC reads the masad
validity sheet (ח.פ.-היתר-תוקף) and POSTs the computed lists here. This
endpoint enriches each name with its portal-account status (matched against
Client.name + billing_aliases, incl. the users' emails), builds ONE
consolidated RTL email and sends it to the office ONLY — no customer receives
anything in the pilot; Limor reviews and sends manually. Auto-send to
customers/transporters is a later stage (needs Yoav-approved wording).

Auth: ECOOIL_BRIDGE_TOKEN bearer (same pattern as the weekly digest).
"""
import re

from flask import Blueprint, jsonify, request

from .db import db, User, Client
from .ecooil_bridge import ecooil_bridge_required
from .mailer import send_office_email

reminders = Blueprint("reminders", __name__)

PORTAL_URL = "https://portal.eco-oil.co.il"


def _norm(name):
    return re.sub(r"\s+", " ", str(name or "")).strip()


def _portal_index():
    """normalized client-name/alias → (client, [user emails])"""
    idx = {}
    clients = Client.query.filter_by(division="eco_oil").all()
    users = User.query.filter(User.client_id.isnot(None)).all()
    emails_by_client = {}
    for u in users:
        emails_by_client.setdefault(u.client_id, []).append(u.email)
    for c in clients:
        entry = (c, emails_by_client.get(c.id, []))
        idx[_norm(c.name)] = entry
        for alias in (c.billing_aliases or "").splitlines():
            if _norm(alias):
                idx[_norm(alias)] = entry
    return idx


def _portal_status(idx, name):
    entry = idx.get(_norm(name))
    if entry is None:
        return "לא מחובר לפורטל", []
    _c, emails = entry
    if not emails:
        return "חשבון קיים, ללא משתמשים", []
    return "מחובר", emails


TH = "border:1px solid #999;background:#e8f0ee;padding:6px 10px;text-align:right;"
TD = "border:1px solid #999;padding:6px 10px;text-align:right;vertical-align:top;"


def _streams_txt(items):
    return ", ".join(f"{s['stream']} ({s['month']})" for s in items)


@reminders.route("/admin/declaration-reminders", methods=["POST"])
@ecooil_bridge_required
def declaration_reminders():
    data = request.get_json(silent=True) or {}
    window = data.get("window", "")
    direct = data.get("direct", [])
    via = data.get("via", [])
    expired = data.get("expired", [])
    expired_older = data.get("expired_older", 0)
    notes = data.get("notes", [])

    idx = _portal_index()

    # ── section A: direct customers expiring in the window ──
    rows_a = ""
    for item in direct:
        status, emails = _portal_status(idx, item["customer"])
        mail_txt = "<br>".join(emails) if emails else ""
        rows_a += (f'<tr><td style="{TD}">{item["customer"]}</td>'
                   f'<td style="{TD}">{_streams_txt(item["expiring"])}</td>'
                   f'<td style="{TD}">{status}</td>'
                   f'<td style="{TD}">{mail_txt}</td></tr>')

    # ── section B: indirect customers grouped by transporter ──
    rows_b = ""
    for item in via:
        status, emails = _portal_status(idx, item["transporter"])
        mail_txt = "<br>".join(emails) if emails else ""
        cust_txt = "<br>".join(
            f'{c["customer"]} — {_streams_txt(c["expiring"])}' for c in item["customers"])
        rows_b += (f'<tr><td style="{TD}">{item["transporter"]}</td>'
                   f'<td style="{TD}">{cust_txt}</td>'
                   f'<td style="{TD}">{status}</td>'
                   f'<td style="{TD}">{mail_txt}</td></tr>')

    # ── section C: already expired ──
    rows_c = ""
    for item in expired:
        status, _em = _portal_status(idx, item["customer"])
        rows_c += (f'<tr><td style="{TD}">{item["customer"]}</td>'
                   f'<td style="{TD}">{item.get("routing", "")}</td>'
                   f'<td style="{TD}">{_streams_txt(item["streams"])}</td>'
                   f'<td style="{TD}">{status}</td></tr>')

    notes_html = ""
    if notes:
        notes_html = ("<h3 style='color:#B45309;'>לתשומת לבך (נתונים לבדיקה במסד)</h3><ul>"
                      + "".join(f"<li>{n}</li>" for n in notes) + "</ul>")

    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;">
<h2 style="color:#2C6E63;">תזכורות הצהרות יצרן — סבב {window} (פיילוט)</h2>
<p>ריכוז הלקוחות שהצהרתם פגה בחודש <b>{window}</b>, לפי המסד.
<b>אף לקוח לא קיבל דבר</b> — בשלב הפיילוט הרשימה נשלחת רק אלייך, לשליחה ידנית.</p>

<h3 style="color:#2C6E63;">א. לקוחות ישירים ({len(direct)})</h3>
<table style="border-collapse:collapse;">
<tr><th style="{TH}">לקוח</th><th style="{TH}">זרמים שפגים</th><th style="{TH}">פורטל</th><th style="{TH}">מיילים בפורטל</th></tr>
{rows_a or f'<tr><td style="{TD}" colspan="4">אין</td></tr>'}
</table>

<h3 style="color:#2C6E63;">ב. לקוחות עקיפים — לפי המוביל האחראי ({len(via)} מובילים)</h3>
<table style="border-collapse:collapse;">
<tr><th style="{TH}">מוביל</th><th style="{TH}">הלקוחות שלו שפגים</th><th style="{TH}">פורטל</th><th style="{TH}">מיילים בפורטל</th></tr>
{rows_b or f'<tr><td style="{TD}" colspan="4">אין</td></tr>'}
</table>

<h3 style="color:#B45309;">ג. הצהרות שפגו בשלושת החודשים האחרונים ולא חודשו ({len(expired)})</h3>
<table style="border-collapse:collapse;">
<tr><th style="{TH}">לקוח</th><th style="{TH}">שיוך</th><th style="{TH}">זרמים שפגו</th><th style="{TH}">פורטל</th></tr>
{rows_c or f'<tr><td style="{TD}" colspan="4">אין</td></tr>'}
</table>
<p style="color:#777;">בנוסף קיימות במסד עוד {expired_older} שורות שפגו לפני כן (רובן ככל הנראה לקוחות שאינם פעילים) — הרשימה המלאה נשמרת בקובץ היומן במחשב המשרד.</p>

{notes_html}

<h3 style="color:#2C6E63;">נוסחים מוכנים לשליחה (העתיקי ומלאי שם/זרמים)</h3>
<p><b>ללקוח ישיר המחובר לפורטל:</b><br>
שלום, תוקף הצהרת היצרן שלכם לזרם [זרם] יפוג ב-[חודש]. אפשר לחדש אותה בקלות
ישירות בפורטל הלקוחות: {PORTAL_URL} — נכנסים ולוחצים "למילוי הצהרת יצרן".
ללא הצהרה בתוקף לא נוכל לאשר קליטת פסולת. תודה, לימור</p>
<p><b>ללקוח ישיר שאינו מחובר:</b><br>
שלום, תוקף הצהרת היצרן שלכם לזרם [זרם] יפוג ב-[חודש]. אשלח אליכם את טופס
ההצהרה לחידוש — נא להחזירו חתום לפני תום החודש. ללא הצהרה בתוקף לא נוכל
לאשר קליטת פסולת. תודה, לימור</p>
<p><b>למוביל (על לקוחותיו):</b><br>
שלום, ללקוחות הבאים שלך תפוג הצהרת היצרן ב-[חודש]: [רשימה]. באחריותך
להסדיר הצהרות חתומות עבורם לפני תום החודש — ללא הצהרה בתוקף לא נוכל לקבל
את הפסולת שלהם. תודה, לימור</p>

<p style="color:#777;">נשלח אוטומטית על ידי פורטל אקו-אויל — מנגנון תזכורות ההצהרות (פיילוט; רץ ב-15 לכל חודש).</p></div>"""

    sent = send_office_email(
        subject=f"תזכורות הצהרות יצרן — סבב {window} ({len(direct)} ישירים, {len(via)} מובילים, {len(expired)} שכבר פגו)",
        html=html)
    return jsonify({"sent": sent, "direct": len(direct), "via": len(via),
                    "expired": len(expired), "notes": len(notes)})
