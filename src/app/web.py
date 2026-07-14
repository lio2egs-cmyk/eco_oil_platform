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

from flask import Blueprint, render_template, request

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


@web.route("/terminal")
def field_terminal():
    """מסופון השטח (טאבלטים) — דף עצמאי; ההרשאה נעשית במפתח מכשיר בתוך הדף."""
    return render_template("terminal.html")
