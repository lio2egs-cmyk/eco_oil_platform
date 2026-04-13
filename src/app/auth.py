from functools import wraps
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    get_jwt,
)
from werkzeug.security import generate_password_hash, check_password_hash
from .db import db, User, Client, TokenBlocklist

auth = Blueprint("auth", __name__, url_prefix="/auth")

VALID_ROLES = {"admin", "eco_oil_client", "eco_depot_client", "transport_company"}


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
