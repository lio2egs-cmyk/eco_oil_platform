"""
Customer-facing portal frontend pages (login / verify / portal home).

These are the HTML pages the customer actually sees. They are thin: the login
page POSTs the email to /auth/request-magic-link, and the verify page POSTs the
token to /auth/verify-magic-link — all the security logic lives in auth.py.

Branding (logo + name) is chosen per subdomain:
  depot.eco-oil.co.il  -> Eco-Depot (English logo)
  portal.eco-oil.co.il -> Eco-Oil   (Hebrew logo)
"""
import json

from flask import Blueprint, current_app, redirect, render_template, request

from .declaration_data import STREAMS

web = Blueprint("web", __name__)


def _brand_for_host():
    host = (request.host or "").lower()
    if host.startswith("depot.") or host.startswith("depot"):
        return dict(division="eco_depot", brand="אקו-דיפו", logo="logo_eco_depot.png")
    # default (portal. / localhost / Railway URL) = Eco-Oil, Hebrew logo
    return dict(division="eco_oil", brand="אקו-אויל", logo="logo_eco_oil.png")


@web.route("/login")
def login_page():
    return render_template("login.html", **_brand_for_host())


@web.route("/verify")
def verify_page():
    return render_template("verify.html", **_brand_for_host())


@web.route("/portal")
def portal_home():
    return render_template("portal_placeholder.html", **_brand_for_host())


@web.route("/documents")
def my_documents_page():
    """"המסמכים שלי" — אישורי הפריקה של הלקוח המחובר, מהנתונים החיים."""
    return render_template("my_documents.html", **_brand_for_host())


@web.route("/declaration")
def declaration_page():
    """טופס הצהרת יצרן (אקו-אויל) — הרשימות מוזרקות מהשרת, מקור אמת אחד."""
    return render_template(
        "declaration.html",
        streams_json=json.dumps(STREAMS, ensure_ascii=False),
        **_brand_for_host(),
    )


@web.route("/declaration-doc")
def declaration_doc_page():
    """מסמך הצהרת יצרן לחתימה (?id=N) — העיצוב המאושר של נספח 3, ממולא
    מהנתונים שהוגשו; אזור החתימה ריק — נשלח ליצרן לחתימה וחותמת.
    ההרשאה בצד ה-API (המסך שואב דרך נקודת הקצה של המנהלת)."""
    return render_template("declaration_doc.html")


@web.route("/admin")
def admin_page():
    """מסך הניהול של לימור — יצירת חברות ומשתמשי פורטל (אקו-אויל; שלב 5).
    ההרשאה בצד השרת: כל ה-API שהמסך קורא דורש תפקיד admin."""
    return render_template("admin.html", **_brand_for_host())


@web.route("/depot-admin")
def depot_admin_page():
    """מסך ניהול הדיפו (לימור 06/08/2026, אפשרות א) — מסך נפרד מהמסך של
    אקו-אויל; עובדים בו לימור, "משרד דיפו" ויואב בכניסות אישיות.
    המיתוג תמיד דיפו, גם אם נפתח מכתובת אחרת; ההרשאה בצד ה-API."""
    return render_template(
        "depot_admin.html",
        division="eco_depot", brand="אקו-דיפו", logo="logo_eco_depot.png")


@web.route("/sw.js")
def field_sw():
    """ה-service worker חייב להיות מוגש משורש האתר כדי לכסות את /terminal."""
    resp = current_app.send_static_file("field/sw.js")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@web.route("/terminal-admin")
def terminal_admin_page():
    return render_template("terminal_admin.html")


@web.route("/terminal")
@web.route("/terminal/<flow>")
def field_terminal(flow=None):
    """מסופון השטח (טאבלטים) — דף עצמאי; ההרשאה נעשית במפתח מכשיר בתוך הדף.
    לכל פעולה נתיב משלה (/terminal/entry|wash|exit) עם scope נפרד במניפסט —
    אחרת כרום מחשיב את שלוש הפעולות כאפליקציה מותקנת אחת וחוסם את השאר."""
    flows = ("entry", "wash", "exit", "repairs", "board", "board-release", "board-care", "board-expected")
    if flow is None and request.args.get("flow") in flows:
        return redirect("/terminal/" + request.args["flow"])
    if flow not in flows:
        flow = "main"
    return render_template("terminal.html", flow=flow)
