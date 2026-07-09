from functools import wraps
import hashlib
import secrets
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from email.header import Header
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    get_jwt,
)
from werkzeug.security import generate_password_hash, check_password_hash
from .db import db, User, Client, TokenBlocklist, MagicLinkToken, LoginAuditLog


# --------------------------------------------------------------------------
# Simple in-memory rate limiting for the PUBLIC endpoints (login / magic-link
# request). Guards against password brute-force and email-flooding a customer.
# Per-process (each gunicorn worker counts separately) and resets on restart —
# good enough as a brake; the audit log remains the forensic source.
# --------------------------------------------------------------------------
_rate_buckets = {}


def _rate_limited(bucket, limit, window_seconds):
    """True if this client IP exceeded `limit` calls in the last window."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    key = (bucket, ip)
    now = datetime.utcnow().timestamp()
    hits = [t for t in _rate_buckets.get(key, []) if now - t < window_seconds]
    if len(hits) >= limit:
        _rate_buckets[key] = hits
        return True
    hits.append(now)
    _rate_buckets[key] = hits
    if len(_rate_buckets) > 10000:  # unbounded-growth guard
        _rate_buckets.clear()
    return False

auth = Blueprint("auth", __name__, url_prefix="/auth")

VALID_ROLES = {"admin", "eco_oil_client", "eco_depot_client", "transport_company"}
PORTAL_ROLES = {"eco_oil_client", "eco_depot_client", "transport_company"}
MAGIC_LINK_TTL_MINUTES = 60


def _hash_magic_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _build_magic_link_url(raw_token: str, division: str) -> str:
    base = os.environ.get("PORTAL_BASE_URL")
    if not base:
        subdomain = "depot" if division == "eco_depot" else "portal"
        base = f"https://{subdomain}.eco-oil.co.il"
    return f"{base.rstrip('/')}/verify?token={raw_token}"


def _brand_name_for_division(division: str) -> str:
    """Return the Hebrew brand name shown to the customer for each portal."""
    return "אקו-דיפו" if division == "eco_depot" else "אקו-אויל"


def _build_magic_link_email_content(brand: str, link: str) -> tuple[str, str, str]:
    """
    Build (subject, plain_text_body, html_body) for the magic-link email.
    Content was agreed with Limor — do not change wording without asking her.
    """
    subject = f"קישור התחברות לפורטל {brand}"

    plain_body = (
        f"לקוח/ה יקר/ה,\n\n"
        f"לבקשתך להתחבר לפורטל הלקוחות של {brand}, "
        f"לחצ/י על הקישור למטה כדי להיכנס:\n\n"
        f"{link}\n\n"
        f"הקישור תקף לשעה אחת בלבד וניתן לשימוש פעם אחת.\n"
        f"אם לא ביקשת להתחבר, ניתן להתעלם מהמייל הזה.\n\n"
        f"בברכה,\n"
        f"צוות אקו-אויל"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, 'Segoe UI', sans-serif; background:#f5f5f5; margin:0; padding:24px; direction:rtl;">
  <div style="max-width:560px; margin:0 auto; background:#ffffff; border-radius:8px; padding:32px; box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <p style="font-size:16px; color:#333; margin:0 0 16px;">לקוח/ה יקר/ה,</p>
    <p style="font-size:16px; color:#333; line-height:1.6; margin:0 0 24px;">
      לבקשתך להתחבר לפורטל הלקוחות של <strong>{brand}</strong>,<br>
      לחצ/י על הכפתור למטה כדי להיכנס.
    </p>
    <p style="text-align:center; margin:32px 0;">
      <a href="{link}"
         style="display:inline-block; background:#5B9E96; color:#ffffff; text-decoration:none;
                padding:14px 32px; border-radius:6px; font-size:16px; font-weight:bold;">
        התחברות לפורטל
      </a>
    </p>
    <p style="font-size:13px; color:#888; line-height:1.6; margin:0 0 8px;">
      הקישור תקף לשעה אחת בלבד וניתן לשימוש פעם אחת.
    </p>
    <p style="font-size:13px; color:#888; line-height:1.6; margin:0 0 24px;">
      אם לא ביקשת להתחבר, ניתן להתעלם מהמייל הזה.
    </p>
    <hr style="border:none; border-top:1px solid #eee; margin:16px 0;">
    <p style="font-size:14px; color:#555; margin:0;">
      בברכה,<br>צוות אקו-אויל
    </p>
  </div>
</body>
</html>"""

    return subject, plain_body, html_body


def _send_magic_link_email(user: User, raw_token: str) -> None:
    """
    Send the magic-link email. Two delivery channels, tried in order:

    1. HTTPS email API (Resend) when RESEND_API_KEY is set — this is what
       PRODUCTION uses, because Railway blocks outbound SMTP ports entirely.
    2. SMTP (smtp.gmail.com STARTTLS) when MAIL_* are set and reachable —
       used for LOCAL development from the office network.

    If neither is available or the send fails, the link is logged (dev fallback)
    so nothing is lost and local testing still works.
    """
    division = user.client.division if user.client else "eco_oil"
    brand = _brand_name_for_division(division)
    link = _build_magic_link_url(raw_token, division)

    subject, plain_body, html_body = _build_magic_link_email_content(brand, link)
    from_addr = os.environ.get("MAIL_FROM_ADDRESS", os.environ.get("MAIL_USERNAME", ""))
    from_name = os.environ.get("MAIL_FROM_NAME", "")

    # ── Channel 1: Resend HTTPS API (production) ──
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key and from_addr:
        sender = formataddr((from_name, from_addr)) if from_name else from_addr
        try:
            import requests
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": "Bearer " + resend_key},
                json={
                    "from": sender,
                    "to": [user.email],
                    "subject": subject,
                    "html": html_body,
                    "text": plain_body,
                },
                timeout=20,
            )
            if r.status_code < 300:
                current_app.logger.info("Magic link email sent (Resend) to %s", user.email)
                return
            current_app.logger.error(
                "[MAGIC LINK - Resend failed %s: %s] To: %s | Link: %s",
                r.status_code, r.text[:300], user.email, link,
            )
            return
        except Exception as exc:
            current_app.logger.error(
                "[MAGIC LINK - Resend error: %s] To: %s | Link: %s", exc, user.email, link,
            )
            return

    # ── Channel 2: SMTP (local dev on the office network) ──
    smtp_host = os.environ.get("MAIL_HOST")
    smtp_port = int(os.environ.get("MAIL_PORT", "587"))
    smtp_user = os.environ.get("MAIL_USERNAME")
    smtp_pass = os.environ.get("MAIL_PASSWORD")

    if not (smtp_host and smtp_user and smtp_pass and from_addr):
        current_app.logger.warning(
            "[MAGIC LINK - DEV MODE / no email channel configured] To: %s | Link: %s",
            user.email, link,
        )
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr)) if from_name else from_addr
    msg["To"] = user.email
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        current_app.logger.info("Magic link email sent (SMTP) to %s", user.email)
    except Exception as exc:
        # Log the failure AND the link, so we can debug without losing the user.
        current_app.logger.error(
            "[MAGIC LINK - SMTP send failed: %s] To: %s | Link: %s",
            exc, user.email, link,
        )


def _log_event(event_type: str, success: bool, user_id=None, email=None, notes=None):
    try:
        entry = LoginAuditLog(
            user_id=user_id,
            email_attempted=email,
            event_type=event_type,
            success=success,
            ip_address=request.remote_addr,
            user_agent=(request.headers.get("User-Agent") or "")[:300],
            notes=notes,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()


# --------------- helpers ---------------

def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("role") != "admin":
            return jsonify(error="Admin access required"), 403
        return fn(*args, **kwargs)
    return wrapper


def get_allowed_client_ids():
    """Return list of client IDs the current user may access, or None for admin (no filter)."""
    claims = get_jwt()
    role = claims.get("role")
    client_id = claims.get("client_id")

    if role == "admin":
        return None

    if role == "transport_company" and client_id:
        sub_ids = [c.id for c in Client.query.filter_by(parent_client_id=client_id).all()]
        return [client_id] + sub_ids

    return [client_id] if client_id else []


# --------------- endpoints ---------------

@auth.route("/login", methods=["POST"])
def login():
    if _rate_limited("login", limit=10, window_seconds=600):
        return jsonify(error="Too many attempts, try again later"), 429

    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify(error="Username and password required"), 400

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify(error="Invalid credentials"), 401

    if not user.is_active:
        return jsonify(error="Account disabled"), 403

    additional_claims = {
        "role": user.role,
        "client_id": user.client_id,
    }
    access_token = create_access_token(identity=str(user.id), additional_claims=additional_claims)
    refresh_token = create_refresh_token(identity=str(user.id), additional_claims=additional_claims)

    return jsonify(
        access_token=access_token,
        refresh_token=refresh_token,
        user=dict(
            id=user.id,
            username=user.username,
            role=user.role,
            client_id=user.client_id,
        ),
    ), 200


@auth.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    if not user or not user.is_active:
        return jsonify(error="Invalid user"), 401

    additional_claims = {
        "role": user.role,
        "client_id": user.client_id,
    }
    access_token = create_access_token(identity=str(user.id), additional_claims=additional_claims)
    return jsonify(access_token=access_token), 200


@auth.route("/register", methods=["POST"])
@admin_required
def register():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", "").strip()
    client_id = data.get("client_id")

    if not username or not password or not role:
        return jsonify(error="username, password, and role are required"), 400

    if role not in VALID_ROLES:
        return jsonify(error=f"role must be one of: {', '.join(sorted(VALID_ROLES))}"), 400

    if len(password) < 8:
        return jsonify(error="Password must be at least 8 characters"), 400

    if role != "admin" and not client_id:
        return jsonify(error="client_id is required for non-admin users"), 400

    if client_id:
        client = Client.query.get(client_id)
        if not client:
            return jsonify(error="Client not found"), 404

    if User.query.filter_by(username=username).first():
        return jsonify(error="Username already exists"), 409

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role=role,
        client_id=client_id if role != "admin" else None,
    )
    db.session.add(user)
    db.session.commit()

    return jsonify(
        id=user.id,
        username=user.username,
        role=user.role,
        client_id=user.client_id,
    ), 201


@auth.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    jti = get_jwt()["jti"]
    db.session.add(TokenBlocklist(jti=jti))
    db.session.commit()
    return jsonify(msg="Token revoked"), 200


@auth.route("/change-password", methods=["POST"])
@jwt_required()
def change_password():
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not current_password or not new_password:
        return jsonify(error="current_password and new_password required"), 400

    if len(new_password) < 8:
        return jsonify(error="New password must be at least 8 characters"), 400

    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))

    if not check_password_hash(user.password_hash, current_password):
        return jsonify(error="Current password is incorrect"), 401

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return jsonify(msg="Password updated"), 200


@auth.route("/portal-users", methods=["POST"])
@admin_required
def create_portal_user():
    """Admin-only: create a passwordless portal user that logs in via magic link only."""
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    role = data.get("role", "").strip()
    client_id = data.get("client_id")

    if not email or "@" not in email:
        return jsonify(error="Valid email is required"), 400

    if role not in PORTAL_ROLES:
        return jsonify(error=f"role must be one of: {', '.join(sorted(PORTAL_ROLES))}"), 400

    if not client_id:
        return jsonify(error="client_id is required"), 400

    client = Client.query.get(client_id)
    if not client:
        return jsonify(error="Client not found"), 404

    if User.query.filter_by(email=email).first():
        return jsonify(error="A user with this email already exists"), 409

    if User.query.filter_by(username=email).first():
        return jsonify(error="Username collision with existing user"), 409

    user = User(
        username=email,
        email=email,
        password_hash=generate_password_hash(secrets.token_hex(32)),  # unguessable, blocks password login
        role=role,
        client_id=client_id,
    )
    db.session.add(user)
    db.session.commit()

    return jsonify(
        id=user.id,
        email=user.email,
        role=user.role,
        client_id=user.client_id,
        client_name=client.name,
    ), 201


@auth.route("/request-magic-link", methods=["POST"])
def request_magic_link():
    """Public: customer enters their email; if it matches a portal user, a magic link is sent."""
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()

    neutral_response = jsonify(
        msg="If this email is registered for portal access, a login link has been sent."
    ), 200

    # Rate limit BEFORE any DB lookup; return the same neutral response so the
    # limiter itself cannot be used to probe which emails exist.
    if _rate_limited("magic", limit=5, window_seconds=600):
        return neutral_response

    if not email or "@" not in email:
        return neutral_response

    user = User.query.filter_by(email=email).first()
    if not user or not user.is_active or user.role not in PORTAL_ROLES:
        _log_event("magic_link_requested", success=False, email=email, notes="email not found / inactive")
        return neutral_response

    # Invalidate any previous unused tokens for this user (single active link at a time)
    MagicLinkToken.query.filter_by(user_id=user.id, used_at=None).update({"used_at": datetime.utcnow()})

    raw_token = secrets.token_urlsafe(32)
    token = MagicLinkToken(
        user_id=user.id,
        token_hash=_hash_magic_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(minutes=MAGIC_LINK_TTL_MINUTES),
        requested_from_ip=request.remote_addr,
    )
    db.session.add(token)
    db.session.commit()

    _send_magic_link_email(user, raw_token)
    _log_event("magic_link_requested", success=True, user_id=user.id, email=email)

    return neutral_response


@auth.route("/verify-magic-link", methods=["POST"])
def verify_magic_link():
    """Public: customer clicks magic link, frontend POSTs the token here, gets JWT pair."""
    data = request.get_json(silent=True) or {}
    raw_token = data.get("token", "").strip()

    if not raw_token:
        return jsonify(error="Token is required"), 400

    token_hash = _hash_magic_token(raw_token)
    token = MagicLinkToken.query.filter_by(token_hash=token_hash).first()

    if not token:
        _log_event("magic_link_verified", success=False, notes="token not found")
        return jsonify(error="Invalid or expired link"), 401

    if token.used_at is not None:
        _log_event("magic_link_verified", success=False, user_id=token.user_id, notes="token already used")
        return jsonify(error="This link has already been used"), 401

    if token.expires_at < datetime.utcnow():
        _log_event("magic_link_verified", success=False, user_id=token.user_id, notes="token expired")
        return jsonify(error="This link has expired"), 401

    user = token.user
    if not user or not user.is_active:
        _log_event("magic_link_verified", success=False, user_id=token.user_id, notes="user inactive")
        return jsonify(error="Account is no longer active"), 403

    token.used_at = datetime.utcnow()
    user.last_login_at = datetime.utcnow()
    db.session.commit()

    additional_claims = {"role": user.role, "client_id": user.client_id}
    access_token = create_access_token(identity=str(user.id), additional_claims=additional_claims)
    refresh_token = create_refresh_token(identity=str(user.id), additional_claims=additional_claims)

    _log_event("magic_link_verified", success=True, user_id=user.id, email=user.email)

    return jsonify(
        access_token=access_token,
        refresh_token=refresh_token,
        user=dict(
            id=user.id,
            email=user.email,
            role=user.role,
            client_id=user.client_id,
            client_name=user.client.name if user.client else None,
        ),
    ), 200


@auth.route("/me", methods=["GET"])
@jwt_required()
def me():
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))
    if not user:
        return jsonify(error="User not found"), 404

    result = dict(
        id=user.id,
        username=user.username,
        role=user.role,
        client_id=user.client_id,
        is_active=user.is_active,
    )

    if user.client:
        result["client_name"] = user.client.name
        result["division"] = user.client.division

    if user.role == "transport_company" and user.client_id:
        sub_clients = Client.query.filter_by(parent_client_id=user.client_id).all()
        result["sub_clients"] = [dict(id=c.id, name=c.name) for c in sub_clients]

    return jsonify(result), 200


@auth.route("/_smtp-diagnose", methods=["POST"])
@admin_required
def _smtp_diagnose():
    """TEMPORARY admin-only diagnostic — connects to the SMTP server and reports
    the real error, without exposing any secret value. Remove after debugging."""
    import smtplib
    host = os.environ.get("MAIL_HOST")
    port = int(os.environ.get("MAIL_PORT", "587"))
    smtp_user = os.environ.get("MAIL_USERNAME")
    smtp_pass = os.environ.get("MAIL_PASSWORD")
    from_addr = os.environ.get("MAIL_FROM_ADDRESS", "")
    from_name = os.environ.get("MAIL_FROM_NAME", "")

    report = {
        "vars_present": {
            "MAIL_HOST": bool(host), "MAIL_PORT": os.environ.get("MAIL_PORT"),
            "MAIL_USERNAME": bool(smtp_user), "MAIL_PASSWORD": bool(smtp_pass),
            "MAIL_PASSWORD_len": len(smtp_pass) if smtp_pass else 0,
            "MAIL_FROM_ADDRESS": from_addr,
            "MAIL_FROM_NAME_repr": repr(from_name),  # detect mojibake, not a secret
        },
        "connect": None, "starttls": None, "login": None, "error": None,
    }
    if not (host and smtp_user and smtp_pass):
        report["error"] = "SMTP vars missing — app is in DEV fallback (no email sent, link only logged)"
        return jsonify(report), 200

    return jsonify(report), 200


@auth.route("/_resend-diagnose", methods=["POST"])
@admin_required
def _resend_diagnose():
    """TEMPORARY admin-only diagnostic — checks the Resend HTTPS channel and,
    if ?send=1 with a JSON {"to": "..."} body, sends a real test email and
    returns Resend's exact response. Remove after debugging. No secret exposed."""
    key = os.environ.get("RESEND_API_KEY")
    from_addr = os.environ.get("MAIL_FROM_ADDRESS", "")
    from_name = os.environ.get("MAIL_FROM_NAME", "")
    report = {
        "RESEND_API_KEY_present": bool(key),
        "RESEND_API_KEY_len": len(key) if key else 0,
        "from_addr": from_addr,
        "from_name_repr": repr(from_name),
        "send_result": None,
    }
    if not key:
        report["send_result"] = "RESEND_API_KEY missing — add it in Railway variables"
        return jsonify(report), 200

    data = request.get_json(silent=True) or {}
    to = (data.get("to") or "").strip()
    if not to:
        report["send_result"] = "no 'to' provided — key present, ready to test"
        return jsonify(report), 200

    sender = formataddr((from_name, from_addr)) if from_name else from_addr
    try:
        import requests
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": "Bearer " + key},
            json={"from": sender, "to": [to], "subject": "בדיקת פורטל אקו-אויל",
                  "html": "<p dir=rtl>בדיקת שליחה מהפורטל — אם קיבלת מייל זה, הערוץ עובד.</p>",
                  "text": "בדיקת שליחה מהפורטל."},
            timeout=20,
        )
        report["send_result"] = {"status": r.status_code, "body": r.text[:400]}
    except Exception as exc:
        report["send_result"] = "%s: %s" % (type(exc).__name__, exc)
    return jsonify(report), 200
