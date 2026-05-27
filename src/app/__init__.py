import os
from datetime import timedelta
from flask import Flask
from flask_jwt_extended import JWTManager
from werkzeug.security import generate_password_hash, check_password_hash
from .routes import main
from .auth import auth
from .db import db

jwt = JWTManager()

def create_app():
    app = Flask(__name__)

    from pathlib import Path

    # Database URL:
    # - In production (Railway), DATABASE_URL is injected automatically by the
    #   Postgres service and points at the managed Postgres instance.
    # - In local development, no DATABASE_URL is set, so we fall back to a
    #   SQLite file under ./data/app.db (auto-created).
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # SQLAlchemy 2.x requires the "postgresql://" scheme; Railway / Heroku
        # still hand out the legacy "postgres://" prefix.
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    else:
        BASE_DIR = Path(__file__).resolve().parents[2]   # eco_oil_platform/
        DATA_DIR = BASE_DIR / "data"
        DATA_DIR.mkdir(exist_ok=True)
        DB_PATH = DATA_DIR / "app.db"
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH.as_posix()}"

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # JWT configuration
    app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-production-32ch")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)

    db.init_app(app)
    jwt.init_app(app)

    # Token blocklist loader
    from .db import TokenBlocklist

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        jti = jwt_payload["jti"]
        return TokenBlocklist.query.filter_by(jti=jti).first() is not None

    with app.app_context():
        # חשוב: לטעון את כל המודלים לפני create_all, אחרת טבלאות לא יווצרו
        from .db import (
            Client, Asset, DepotPreArrival, Compartment, WashCycle,
            WashCertificate, TransportEvent, IsotankWashCycle, RepairEvent,
            ReleaseDocument, PhotoRecord, Carrier, ProducerDeclaration,
            AgreementDocument, DisposalEvent, DisposalCertificate,
            User, TokenBlocklist, MagicLinkToken, LoginAuditLog,
        )
        db.create_all()

        # Migrate: add parent_client_id to existing clients table
        try:
            db.session.execute(db.text(
                "ALTER TABLE clients ADD COLUMN parent_client_id INTEGER REFERENCES clients(id)"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Migrate: add email + last_login_at to users
        for stmt in (
            "ALTER TABLE users ADD COLUMN email VARCHAR(200)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users(email)",
            "ALTER TABLE users ADD COLUMN last_login_at DATETIME",
        ):
            try:
                db.session.execute(db.text(stmt))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Seed/sync admin user. In production, FLASK_ADMIN_USERNAME and
        # FLASK_ADMIN_PASSWORD env vars override the defaults.
        # NEVER ship "changeme123" live — it's a local-dev fallback only.
        admin_username_env = os.environ.get("FLASK_ADMIN_USERNAME")
        admin_password_env = os.environ.get("FLASK_ADMIN_PASSWORD")
        admin = User.query.filter_by(role="admin").first()
        if not admin:
            # First boot — seed the admin row.
            admin = User(
                username=admin_username_env or "admin",
                password_hash=generate_password_hash(admin_password_env or "changeme123"),
                role="admin",
            )
            db.session.add(admin)
            db.session.commit()
        else:
            # Subsequent boots — if env vars are set and differ from the stored
            # values, update. (Empty env vars are ignored so we never accidentally
            # downgrade prod back to the dev default.)
            changed = False
            if admin_username_env and admin.username != admin_username_env:
                admin.username = admin_username_env
                changed = True
            if admin_password_env and not check_password_hash(admin.password_hash, admin_password_env):
                admin.password_hash = generate_password_hash(admin_password_env)
                changed = True
            if changed:
                db.session.commit()

    app.register_blueprint(main)
    app.register_blueprint(auth)

    @app.route("/health")
    def health():
        return {"status": "ok"}, 200

    return app
