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
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from .db import db, User, Client, EcoOilUnloadEvent
from .ecooil_bridge import ecooil_bridge_required
from .ecooil_docs import _scoped_query, WITHHELD_STATUSES
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


# ═══════════════════════════════════════════════════════════════════════════
# Weekly Thursday customer reminder — opt-in per user (Laura/Gadot's request
# via Limor, approved 02/08/2026): a short anchor email — "here's what your
# week at Eco-Oil looked like, the documents await you in the portal" — with
# COUNTS ONLY, never attachments. Rules Limor fixed: reminder + numbers;
# SKIP a customer whose week had zero unload events; triggered by the office
# PC's Thursday scheduled task (same pattern as the weekly login digest).
# Nothing is sent to anyone whose weekly_reminder flag Limor hasn't switched
# on in the admin screen.
# ═══════════════════════════════════════════════════════════════════════════

def _week_counts(client, start, end):
    """(events, available certs, available manifests) in the window, using the
    exact same billed-party scoping + sanction withholding as the portal."""
    q, _mode = _scoped_query(client)
    rows = q.filter(EcoOilUnloadEvent.event_date >= start,
                    EcoOilUnloadEvent.event_date <= end).all()
    certs = sum(1 for r in rows if r.pdf_key and r.doc_status not in WITHHELD_STATUSES)
    manifests = sum(1 for r in rows if r.manifest_key and r.doc_status not in WITHHELD_STATUSES)
    return len(rows), certs, manifests


def _weekly_reminder_email(client_name, start, end, events, certs, manifests):
    period = f"{start.strftime('%d/%m/%Y')} — {end.strftime('%d/%m/%Y')}"
    subject = "עדכון שבועי — פורטל הלקוחות של אקו-אויל"
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;font-size:15px;color:#222;line-height:1.7;">
<h2 style="color:#2C6E63;">העדכון השבועי שלכם מאקו-אויל</h2>
<p>שלום רב,</p>
<p>בשבוע שבין <b>{period}</b> נרשמו עבורכם ({client_name}) במערכת אקו-אויל
<b>{events} פעולות פריקה</b>.<br>
בפורטל הלקוחות זמינים כעת עבור השבוע הזה: <b>{certs} אישורי פריקה</b>
ו-<b>{manifests} טופסי מלווה חתומים</b>.</p>
<p style="margin:22px 0;">
<a href="{PORTAL_URL}" style="background:#5B9E96;color:#fff;text-decoration:none;
padding:12px 28px;border-radius:8px;font-weight:bold;">כניסה לפורטל</a></p>
<p style="color:#555;font-size:13.5px;">בפורטל מזינים את כתובת המייל שלכם ומקבלים
קישור כניסה אישי — ללא סיסמה.</p>
<p style="color:#777;font-size:13px;">מייל תזכורת זה נשלח מדי יום חמישי לבקשתכם
ואינו כולל מסמכים מצורפים — כל המסמכים זמינים בפורטל, בכל עת.<br>
להפסקת התזכורת השבועית — השיבו למייל זה או פנו אלינו:
<a href="mailto:office@eco-oil.co.il">office@eco-oil.co.il</a>.</p>
<p>בברכה,<br>אקו-אויל</p></div>"""
    return subject, html


@reminders.route("/admin/weekly-portal-reminder", methods=["POST"])
@ecooil_bridge_required
def weekly_portal_reminder():
    """Thursday morning run: email every opted-in portal user whose company had
    unload events in the closing week (previous Thursday → Wednesday)."""
    today = date.today()
    end = today - timedelta(days=1)
    start = today - timedelta(days=7)

    users = (User.query.filter_by(weekly_reminder=True, is_active=True)
             .filter(User.email.isnot(None)).order_by(User.client_id).all())

    sent, skipped_empty, skipped_other, errors = [], [], [], []
    counts_cache = {}
    for u in users:
        client = db.session.get(Client, u.client_id) if u.client_id else None
        if client is None or client.division != "eco_oil":
            skipped_other.append((u.email, "חשבון ללא חברת אקו-אויל (דיפו עדיין לא נתמך)"))
            continue
        if client.id not in counts_cache:
            counts_cache[client.id] = _week_counts(client, start, end)
        events, certs, manifests = counts_cache[client.id]
        if events == 0:
            skipped_empty.append((u.email, client.name))
            continue
        subject, html = _weekly_reminder_email(client.name, start, end,
                                               events, certs, manifests)
        if send_office_email(subject=subject, html=html, to=u.email):
            sent.append((u.email, client.name, events, certs, manifests))
        else:
            errors.append((u.email, client.name))

    # Office oversight summary — only when the mechanism had anyone to consider,
    # so quiet weeks don't add inbox noise on top of the Sunday digest.
    if users:
        period = f"{start.strftime('%d/%m/%Y')} — {end.strftime('%d/%m/%Y')}"
        rows = ""
        for em, cn, ev, ce, mf in sent:
            rows += (f'<tr><td style="{TD}">{cn}</td><td style="{TD}">{em}</td>'
                     f'<td style="{TD}">נשלח ✓</td><td style="{TD}">{ev} פעולות · {ce} אישורים · {mf} טופסי מלווה</td></tr>')
        for em, cn in skipped_empty:
            rows += (f'<tr><td style="{TD}">{cn}</td><td style="{TD}">{em}</td>'
                     f'<td style="{TD}">דולג — שבוע ללא פעילות</td><td style="{TD}"></td></tr>')
        for em, why in skipped_other:
            rows += (f'<tr><td style="{TD}"></td><td style="{TD}">{em}</td>'
                     f'<td style="{TD}">דולג</td><td style="{TD}">{why}</td></tr>')
        for em, cn in errors:
            rows += (f'<tr><td style="{TD}">{cn}</td><td style="{TD}">{em}</td>'
                     f'<td style="{TD}" ><b style="color:#B45309;">שגיאת שליחה</b></td><td style="{TD}"></td></tr>')
        office_html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;">
<h2 style="color:#2C6E63;">תזכורת חמישי ללקוחות — סיכום ריצה</h2>
<p>שבוע: <b>{period}</b> · נשלחו: <b>{len(sent)}</b> · דולגו (שבוע ריק): <b>{len(skipped_empty)}</b>
· דולגו (אחר): <b>{len(skipped_other)}</b> · שגיאות: <b>{len(errors)}</b></p>
<table style="border-collapse:collapse;">
<tr><th style="{TH}">חברה</th><th style="{TH}">מייל</th><th style="{TH}">סטטוס</th><th style="{TH}">פירוט</th></tr>
{rows}</table>
<p style="color:#777;">נשלח אוטומטית על ידי פורטל אקו-אויל — מנגנון תזכורת יום חמישי.</p></div>"""
        send_office_email(
            subject=f"תזכורת חמישי ללקוחות — נשלחו {len(sent)}, דולגו {len(skipped_empty) + len(skipped_other)}",
            html=office_html)

    return jsonify({"opted_in": len(users), "sent": len(sent),
                    "skipped_empty": len(skipped_empty),
                    "skipped_other": len(skipped_other), "errors": len(errors)})
