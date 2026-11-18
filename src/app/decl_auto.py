# -*- coding: utf-8 -*-
"""חסימה ושחרור אוטומטיים לפי תוקף הצהרת היצרן (לימור 11/11/2026).

הרקע: עד היום לימור כתבה בריכוז "לא לפרסם - אין הצהרה" על כל שורה של לקוח
בלי הצהרה בתוקף, והייתה צריכה לזכור להסיר את זה כשההצהרה חודשה. מעכשיו
הענן מחליט לבד, לפי גיליון ח.פ.-היתר-תוקף שהגשר דוחף כל שעה:

  1. רק שורות חומ"ס (מינרלי/אמולסיה/בסיס/חומצה/מי שטיפה/מזוט) מ-01/01/2026.
  2. שם הלקוח בריכוז מקושר לשורה במסד: שם זהה (אחרי נרמול) — לבד; אחרת לפי
     טבלת הקישור (EcoOilDeclLink) שלימור ממלאת פעם אחת לכל שם במסך הניהול.
     שם צבאי מסומן "צבא" — פטור (חוק 74ד).
  3. תאריך תוקף במסד = בתוקף עד סוף אותו חודש (לימור 11/11).
     פריקה אחרי סוף החודש ⇒ 'expired' — נחסם. אין תאריך לזרם ⇒ 'no_decl' —
     נחסם. פריקה בחודש שבו התוקף פג ⇒ 'expiring' — מתפרסם (ובשלב הבא: התראה
     ללקוח "התוקף פג החודש, חשוב לחדש").
  4. ההצהרה חודשה (התאריך במסד זז קדימה) ⇒ בסבב הבא השורה משתחררת לבד —
     גם אם לימור כתבה עליה "אין הצהרה" ידנית.
  5. שם שלא מקושר ⇒ 'unlinked' — מתפרסם (לא מסתירים מלקוח תקין), נרשם
     כ"ממתין" ולימור מקבלת מייל אחד עם כפתור קישור במסך הניהול.

"לא לפרסם" (בלי "הצהרה") ו"ללא אישור מלכתחילה" נשארים בדיוק כמו היום.
"""
import calendar
import json
import re
from datetime import date, datetime

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required

from .db import db, EcoOilUnloadEvent, EcoOilDeclLink, EcoOilValiditySnapshot

decl_auto_bp = Blueprint("decl_auto", __name__, url_prefix="/eco-oil")

CHECKABLE_STREAMS = ("מינרלי", "אמולסיה", "בסיס", "חומצה", "מי שטיפה", "מזוט")
AUTO_FROM = date(2026, 1, 1)
BLOCKING = {"expired", "no_decl"}
RELEASING = {"ok", "expiring", "army"}
WITHHELD = {"awaiting_declaration", "unpublished"}
PORTAL_ADMIN_URL = "https://portal.eco-oil.co.il/admin"


def norm(s):
    """אותו נרמול כמו _norm_name בפורטל: בלי גרשיים/מקפים/בע"מ/פיסוק."""
    if not s:
        return ""
    s = str(s).replace('"', "").replace("'", "").replace("”", "").replace("“", "")
    s = s.replace("׳", "").replace("״", "").replace("_", " ").replace("-", " ")
    s = re.sub(r"בע\s*מ", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ─────────────────────────── מה הלקוח רואה בפועל ───────────────────────────
def effective_doc_status(ev):
    """הסטטוס שהפורטל מציג: ההחלטה הידנית של לימור, ועליה השכבה האוטומטית."""
    st, auto = ev.doc_status, getattr(ev, "decl_auto", None)
    if st in ("unpublished", "no_cert_by_design"):
        return st
    if auto in BLOCKING:
        return "awaiting_declaration"
    if st == "awaiting_declaration" and auto in RELEASING:
        return None          # ההצהרה בתוקף — משתחרר לבד, גם בלי למחוק את ההערה
    return st


def is_withheld(ev):
    return effective_doc_status(ev) in WITHHELD


# ─────────────────────────── החישוב ───────────────────────────
def _parse(d):
    try:
        return datetime.strptime(str(d), "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def _eom(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def validity_index():
    """{שם מנורמל: {"name", "hp", "streams": {זרם: date}}} מתמונת המסד.
    כמה שורות באותו שם (זוהר דליה אגש"ח — שורה לכל היתר) מתאחדות: לכל זרם
    התאריך המאוחר."""
    snap = EcoOilValiditySnapshot.query.first()
    if snap is None or not snap.data:
        return None
    try:
        rows = json.loads(snap.data).get("rows", [])
    except ValueError:
        return None
    idx = {}
    for r in rows:
        k = norm(r.get("name"))
        if not k:
            continue
        e = idx.setdefault(k, {"name": r.get("name"), "hp": r.get("hp") or "", "streams": {}})
        for label, d in (r.get("streams") or {}).items():
            dd = _parse(d)
            if dd and (label not in e["streams"] or dd > e["streams"][label]):
                e["streams"][label] = dd
    # חברה עם כמה אתרים (לימור 18/11, אור ברקן: בריכוז "אור ברקן בע"מ" בלי
    # אתר, במסד שורה לשוהם ושורה לחלמיש — והיא לא יכלה לבחור "את שתיהן"):
    # לכל ח.פ. שיש לו כמה שורות נוספת אפשרות אחת "כל האתרים", שמאחדת אותן —
    # לכל זרם התאריך המאוחר מבין האתרים.
    by_hp = {}
    for e in idx.values():
        hp = re.sub(r"\D", "", e["hp"] or "")
        if hp:
            by_hp.setdefault(hp, []).append(e)
    for hp, sites in by_hp.items():
        if len(sites) < 2:
            continue
        label = _company_label(sorted(s["name"].strip() for s in sites), hp)
        streams = {}
        for s in sites:
            for st, dd in s["streams"].items():
                if st not in streams or dd > streams[st]:
                    streams[st] = dd
        idx[norm(label)] = {"name": label, "hp": hp, "streams": streams, "company": True}
    return idx


ALL_SITES = "כל האתרים"


def _company_label(names, hp):
    """'אור ברקן בע"מ — כל האתרים (ח.פ. 511546392)': החלק המשותף לשמות האתרים."""
    common = names[0]
    for n in names[1:]:
        i = 0
        while i < min(len(common), len(n)) and common[i] == n[i]:
            i += 1
        common = common[:i]
    # לא חותכים באמצע מילה ("דלק ה|שרון" / "דלק ה|צפון")
    if any(len(n) > len(common) and re.match(r"\w", n[len(common)]) for n in names) \
            and re.search(r"\w$", common):
        common = common[:common.rfind(" ") + 1] if " " in common else ""
    common = re.sub(r"[\s,\-–—(\[]*(אתר)?[\s,\-–—(\[]*$", "", common).strip()
    if len(common) < 4:
        common = names[0]
    return f"{common} — {ALL_SITES} (ח.פ. {hp})"


def _company_by_hp(vidx, hp):
    hp = re.sub(r"\D", "", hp or "")
    for e in vidx.values():
        if e.get("company") and e["hp"] == hp:
            return e
    return None


def classify(ev, link, vidx):
    """→ (decl_auto, masad_name)."""
    if (ev.stream_norm or "").strip() not in CHECKABLE_STREAMS:
        return None, None
    if ev.event_date is None or ev.event_date < AUTO_FROM:
        return None, None
    if ev.doc_status in ("no_cert_by_design", "unpublished"):
        return None, None
    if link is not None and link.kind == "army":
        return "army", None
    target = None
    if link is not None and link.kind == "masad":
        target = vidx.get(norm(link.masad_name))
        # קישור ל"כל האתרים" נשען על הח.פ. — נשאר תקף גם אם שם אתר שונה במסד
        if target is None and ALL_SITES in (link.masad_name or ""):
            target = _company_by_hp(vidx, link.hp)
    if target is None:
        target = vidx.get(norm(ev.customer))
    if target is None:
        return "unlinked", None
    vu = target["streams"].get(ev.stream_norm.strip())
    if vu is None:
        return "no_decl", target["name"]
    end = _eom(vu)
    if end < ev.event_date:
        return "expired", target["name"]
    if (vu.year, vu.month) == (ev.event_date.year, ev.event_date.month):
        return "expiring", target["name"]
    return "ok", target["name"]


def recompute(alert=True):
    """מחשב מחדש את decl_auto לכל השורות מ-2026. נקרא אחרי כל דחיפה של
    הגשר (שורות או תמונת מסד) ואחרי כל קישור במסך. לעולם לא מפיל את הקורא."""
    try:
        vidx = validity_index()
        if not vidx:
            current_app.logger.warning("decl_auto: no validity snapshot — skipped")
            return {"skipped": "no snapshot"}
        links = {l.name_norm: l for l in EcoOilDeclLink.query.all()}
        evs = EcoOilUnloadEvent.query.filter(EcoOilUnloadEvent.event_date >= AUTO_FROM).all()
        changed, counts, unlinked_names = 0, {}, {}
        for ev in evs:
            k = norm(ev.customer)
            res, _m = classify(ev, links.get(k), vidx)
            counts[res] = counts.get(res, 0) + 1
            if res == "unlinked" and k:
                unlinked_names.setdefault(k, ev.customer)
            if ev.decl_auto != res:
                ev.decl_auto = res
                changed += 1
        new_pending = []
        for k, name in unlinked_names.items():
            if k not in links:
                l = EcoOilDeclLink(name_norm=k[:200], name=(name or k)[:200], kind="pending")
                db.session.add(l)
                links[k] = l
                new_pending.append(l)
        db.session.commit()
        sent = _alert_pending() if alert else False
        return {"changed": changed, "counts": {str(k): v for k, v in counts.items()},
                "new_pending": len(new_pending), "alerted": sent}
    except Exception as exc:  # noqa: BLE001 — הסנכרון חייב להמשיך
        db.session.rollback()
        current_app.logger.error("decl_auto recompute failed: %s", exc)
        return {"error": str(exc)[:200]}


def _alert_pending():
    """מייל אחד ל-office על שמות חדשים שמחכים לקישור. שם שכבר דווח — לא שוב."""
    from .mailer import send_office_email
    todo = (EcoOilDeclLink.query.filter_by(kind="pending")
            .filter(EcoOilDeclLink.alerted_at.is_(None)).all())
    if not todo:
        return False
    stats = _pending_stats()
    td = "border:1px solid #999;padding:6px 10px;text-align:right;vertical-align:top;"
    th = td + "background:#e8f0ee;"
    trs = "".join(
        f'<tr><td style="{td}">{_h(l.name)}</td>'
        f'<td style="{td}">{stats.get(l.name_norm, {}).get("count", 0)}</td>'
        f'<td style="{td}">{_h(stats.get(l.name_norm, {}).get("latest", ""))}</td></tr>'
        for l in todo)
    n = len(todo)
    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;color:#222;">
<p><b>מה קרה:</b> {'שם לקוח אחד' if n == 1 else f'{n} שמות לקוח'} בריכוז (זרמי חומ"ס) לא
{'מקושר' if n == 1 else 'מקושרים'} לשורה בגיליון התוקפים במסד, ולכן המערכת לא יודעת אם יש
{'לו' if n == 1 else 'להם'} הצהרה בתוקף. בינתיים האישורים <b>מתפרסמים</b> כרגיל.</p>
<p><b>מה לעשות:</b> במסך הניהול של הפורטל, בבלוק "קישור שמות לקוח למסד ההצהרות" —
לבחור לכל שם את השורה שלו במסד, או לסמן "צבא". פעם אחת לכל שם.</p>
<table dir="rtl" style="border-collapse:collapse;"><tr><td style="{th}"><b>השם בריכוז</b></td>
<td style="{th}"><b>שורות מ-2026</b></td><td style="{th}"><b>פריקה אחרונה</b></td></tr>{trs}</table>
<p><a href="{PORTAL_ADMIN_URL}">למסך הניהול</a></p></div>"""
    subject = ("שם לקוח לא מקושר למסד ההצהרות" if n == 1
               else f"{n} שמות לקוח לא מקושרים למסד ההצהרות")
    try:
        ok = send_office_email(subject=subject, html=html)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("decl_auto alert failed: %s", exc)
        return False
    if ok:
        now = datetime.utcnow()
        for l in todo:
            l.alerted_at = now
        db.session.commit()
    return bool(ok)


def _h(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _pending_stats():
    out = {}
    q = (EcoOilUnloadEvent.query.filter(EcoOilUnloadEvent.decl_auto == "unlinked")
         .order_by(EcoOilUnloadEvent.event_date.desc()))
    for ev in q:
        k = norm(ev.customer)
        e = out.setdefault(k, {"count": 0, "latest": ev.event_date.strftime("%d/%m/%Y"),
                               "streams": set()})
        e["count"] += 1
        e["streams"].add(ev.stream_norm)
    return out


# ─────────────────────────── מסך הניהול ───────────────────────────
def _admin():
    return get_jwt().get("role") == "admin"


_GENERIC = {"שותפות", "מוגבלת", "תעשיות", "ישראל", "אתר", "חברת", "חברה", "מפעל",
            "בעמ", "ושירותים", "שירותים", "בע", "מ", "ltd", "האתרים"}


def _words(n):
    return {w for w in n.split() if len(w) >= 3 and w not in _GENERIC}


def _suggest(name_n, vidx):
    """עד 5 הצעות לשורה במסד: מכיל/מוכל (≥ 6 תווים) קודם, ואחריו לפי מספר
    המילים המבדילות המשותפות (גדות "מיכל 1209 ב-09, גדות אחסון ושינוע" →
    שורות "גדות אחסון ושינוע" ולא כל מי שחולק מילה אחת)."""
    words = _words(name_n)
    out = []
    for k, e in vidx.items():
        shorter, longer = sorted((name_n, k), key=len)
        shared = len(words & _words(k))
        score = shared + (5 if len(shorter) >= 6 and shorter in longer else 0)
        if score:
            out.append((score, e["name"], bool(e.get("company"))))
    if not out:
        return []
    top = max(x[0] for x in out)
    out = [x for x in out if x[0] >= max(1, top - 1)]
    # "כל האתרים" של החברה מוצגת ראשונה — היא התשובה כשבריכוז אין שם אתר
    out.sort(key=lambda x: (not x[2], -x[0], x[1]))
    return [x[1] for x in out[:5]]


@decl_auto_bp.route("/admin/decl-links", methods=["GET"])
@jwt_required()
def list_links():
    if not _admin():
        return jsonify({"error": "admin only"}), 403
    vidx = validity_index() or {}
    stats = _pending_stats()
    pending, linked = [], []
    for l in EcoOilDeclLink.query.order_by(EcoOilDeclLink.name).all():
        if l.kind == "pending":
            s = stats.get(l.name_norm)
            if not s:
                continue          # כבר אין שורות לא-מקושרות בשם הזה
            pending.append({"name": l.name, "count": s["count"], "latest": s["latest"],
                            "streams": sorted(x for x in s["streams"] if x),
                            "suggest": _suggest(l.name_norm, vidx)})
        else:
            linked.append({"name": l.name, "kind": l.kind, "masad_name": l.masad_name,
                           "hp": l.hp, "decided_at": l.decided_at.strftime("%d/%m/%Y")
                           if l.decided_at else ""})
    pending.sort(key=lambda p: -p["count"])
    # מה חסום עכשיו אוטומטית — לשקיפות (לפי לקוח+זרם)
    blocked = {}
    for ev in EcoOilUnloadEvent.query.filter(EcoOilUnloadEvent.decl_auto.in_(BLOCKING)):
        if ev.doc_status in ("unpublished", "no_cert_by_design"):
            continue
        key = (ev.customer or "", ev.stream_norm or "", ev.decl_auto)
        b = blocked.setdefault(key, {"customer": key[0], "stream": key[1], "why": key[2],
                                     "count": 0, "latest": None})
        b["count"] += 1
        d = ev.event_date.strftime("%d/%m/%Y")
        if b["latest"] is None or ev.event_date > datetime.strptime(b["latest"], "%d/%m/%Y").date():
            b["latest"] = d
    return jsonify({"pending": pending, "linked": linked,
                    "blocked": sorted(blocked.values(), key=lambda b: b["customer"]),
                    "masad_names": sorted(e["name"] for e in vidx.values())})


@decl_auto_bp.route("/admin/decl-links", methods=["POST", "DELETE"])
@jwt_required()
def save_link():
    if not _admin():
        return jsonify({"error": "admin only"}), 403
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()
    k = norm(name)
    if not k:
        return jsonify({"error": "name required"}), 400
    l = EcoOilDeclLink.query.filter_by(name_norm=k).first()
    if request.method == "DELETE":
        if l is not None:
            l.kind, l.masad_name, l.hp, l.decided_at = "pending", None, None, None
            l.alerted_at = datetime.utcnow()   # כבר ידוע ללימור — בלי מייל חוזר
            db.session.commit()
        return jsonify({"ok": True, "result": recompute(alert=False)})
    kind = body.get("kind")
    if kind not in ("masad", "army"):
        return jsonify({"error": "bad kind"}), 400
    target = None
    if kind == "masad":
        target = (validity_index() or {}).get(norm(body.get("masad_name")))
        if target is None:
            return jsonify({"error": "השורה לא נמצאה בגיליון התוקפים"}), 404
    if l is None:
        l = EcoOilDeclLink(name_norm=k[:200], name=name[:200])
        db.session.add(l)
    l.kind = kind
    l.masad_name, l.hp = None, None
    if target is not None:
        l.masad_name, l.hp = target["name"][:200], (target["hp"] or "")[:20]
    l.decided_at = datetime.utcnow()
    l.actor = "מנהלת"
    db.session.commit()
    return jsonify({"ok": True, "result": recompute(alert=False)})
