from functools import wraps
import hashlib
import secrets
import os
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


def _send_magic_link_email(user: User, raw_token: str) -> None:
    """
    Step 3 placeholder: print the magic link to the server log.
    Step 4 will replace this with real SMTP delivery via Microsoft 365 (portal@eco-oil.co.il).
    """
    division = user.client.division if user.client else "eco_oil"
    link = _build_magic_link_url(raw_token, division)
    current_app.logger.warning(
        "[MAGIC LINK - DEV MODE] To: %s | User: %s | Link: %s",
        user.email, user.username, link,
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
