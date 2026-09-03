import os
from datetime import timedelta
from flask import Flask
from flask_jwt_extended import JWTManager
from werkzeug.security import generate_password_hash, check_password_hash
from .routes import main
from .auth import auth
from .web import web
from .field import field
from .ecooil_bridge import ecooil_bridge
from .ecooil_docs import ecooil_docs
from .digest import digest
from .reminders import reminders
from .depot_admin import depot_admin
from .depot_portal import depot_portal
from .depot_certs import depot_certs
from .depot_assets import depot_assets
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

    # Cap request size (field terminals send up to 12 photos x 8MB; anything
    # bigger is abuse). Without this Flask accepts unbounded request bodies.
    app.config["MAX_CONTENT_LENGTH"] = 120 * 1024 * 1024

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
        # תיקון עוגן הנכסים (02/09/2026): הגרסה הראשונה של depot_asset_snapshots
        # נוצרה עם ייחודיות על מס' הביקור לבדו — אבל בקובץ יש מספרים כפולים
        # מלפני הקפאת המספרים (מכלים שונים חולקים מספר). אם הטבלה הישנה קיימת,
        # מוחקים אותה לפני create_all והיא נבנית מחדש עם ייחודיות (ביקור, מכל).
        # בטוח: התוכן = תמונת-מצב שעתית שנדחפת מחדש בכל סבב. רץ פעם אחת בלבד.
        try:
            insp = db.inspect(db.engine)
            if "depot_asset_snapshots" in insp.get_table_names():
                # מזהים את הסכמה החדשה לפי שם האילוץ; ב-SQLite אילוצים לא
                # נראים ב-inspector — קוראים את ה-DDL ישירות.
                if db.engine.dialect.name == "sqlite":
                    ddl = db.session.execute(db.text(
                        "SELECT sql FROM sqlite_master WHERE type='table' "
                        "AND name='depot_asset_snapshots'")).scalar() or ""
                    has_new = "uq_depot_asset_visit_tank" in ddl
                else:
                    has_new = any(
                        u.get("name") == "uq_depot_asset_visit_tank"
                        for u in insp.get_unique_constraints("depot_asset_snapshots"))
                if not has_new:
                    db.session.execute(db.text("DROP TABLE depot_asset_snapshots"))
                    db.session.commit()
        except Exception:
            db.session.rollback()
        db.create_all()

        # Migrate: add parent_client_id to existing clients table
        try:
            db.session.execute(db.text(
                "ALTER TABLE clients ADD COLUMN parent_client_id INTEGER REFERENCES clients(id)"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Migrate: additional billed-name aliases per client (additive, idempotent)
        try:
            db.session.execute(db.text("ALTER TABLE clients ADD COLUMN billing_aliases TEXT"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Migrate: add email + last_login_at to users
        for stmt in (
            "ALTER TABLE users ADD COLUMN email VARCHAR(200)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users(email)",
            "ALTER TABLE users ADD COLUMN last_login_at DATETIME",
            "ALTER TABLE users ADD COLUMN weekly_reminder BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN extra_client_ids VARCHAR(200)",
            "ALTER TABLE users ADD COLUMN invited_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN contact_name VARCHAR(120)",
            # תשובת "שייך לחברה אחרת" בסתירות התיוק (לימור 03/09 ערב)
            "ALTER TABLE ecooil_filing_rulings ADD COLUMN client_id INTEGER REFERENCES clients(id)",
        ):
            try:
                db.session.execute(db.text(stmt))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Migrate: portal-submitted producer declarations (additive, idempotent)
        for stmt in (
            "ALTER TABLE producer_declarations ADD COLUMN producer_name VARCHAR(200)",
            "ALTER TABLE producer_declarations ADD COLUMN status VARCHAR(30)",
            "ALTER TABLE producer_declarations ADD COLUMN submitted_by_user_id INTEGER REFERENCES users(id)",
            "ALTER TABLE producer_declarations ADD COLUMN fix_note TEXT",
            # הסריקה החתומה + האישור הסופי (לימור 09/08). BYTEA תקין גם ב-SQLite
            # (שם סוג חופשי) וגם ב-Postgres.
            "ALTER TABLE producer_declarations ADD COLUMN signed_scan_data BYTEA",
            "ALTER TABLE producer_declarations ADD COLUMN signed_scan_filename VARCHAR(200)",
            "ALTER TABLE producer_declarations ADD COLUMN signed_scan_mime VARCHAR(60)",
            "ALTER TABLE producer_declarations ADD COLUMN signed_scan_at TIMESTAMP",
            "ALTER TABLE producer_declarations ADD COLUMN signed_scan_source VARCHAR(20)",
            "ALTER TABLE producer_declarations ADD COLUMN approved_at TIMESTAMP",
            # הזנה אוטומטית למסד (10/08)
            "ALTER TABLE producer_declarations ADD COLUMN masad_log_at TIMESTAMP",
            "ALTER TABLE producer_declarations ADD COLUMN masad_summary_at TIMESTAMP",
            "ALTER TABLE producer_declarations ADD COLUMN masad_note TEXT",
            # "כבר X ימים ממתינה לחתימה" (12/08)
            "ALTER TABLE producer_declarations ADD COLUMN released_at TIMESTAMP",
            # מספר הסכמה קבוע — סדרה מ-1001 (לימור 12/08)
            "ALTER TABLE agreement_documents ADD COLUMN number INTEGER",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_agreement_documents_number ON agreement_documents(number)",
            # תיוק אוטומטי לתיקיות הלקוחות (12/08)
            "ALTER TABLE producer_declarations ADD COLUMN scan_filed_at TIMESTAMP",
            "ALTER TABLE producer_declarations ADD COLUMN scan_file_note TEXT",
            "ALTER TABLE agreement_documents ADD COLUMN filed_at TIMESTAMP",
            "ALTER TABLE agreement_documents ADD COLUMN file_note TEXT",
            # חסימת מסמכים ברמת החברה (17/08)
            "ALTER TABLE clients ADD COLUMN docs_blocked BOOLEAN DEFAULT FALSE",
            "ALTER TABLE clients ADD COLUMN docs_blocked_at TIMESTAMP",
            "ALTER TABLE clients ADD COLUMN docs_blocked_by VARCHAR(120)",
            "ALTER TABLE clients ADD COLUMN docs_blocked_reason TEXT",
            # שם קצר לשמות קבצים (18/08)
            "ALTER TABLE clients ADD COLUMN file_short_name VARCHAR(80)",
            # גורם מחוייב לפי הצהרת הלקוח בטופס המקדים (לימור 24/08)
            "ALTER TABLE depot_prearrivals ADD COLUMN payer_storage VARCHAR(120)",
            "ALTER TABLE depot_prearrivals ADD COLUMN payer_wash VARCHAR(120)",
            "ALTER TABLE depot_prearrivals ADD COLUMN payer_extras VARCHAR(120)",
            "ALTER TABLE depot_prearrivals ADD COLUMN payer_repairs VARCHAR(120)",
        ):
            try:
                db.session.execute(db.text(stmt))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Migrate: B2 object key + normalized stream on Eco-Oil unload events
        for stmt in (
            "ALTER TABLE ecooil_unload_events ADD COLUMN pdf_key VARCHAR(500)",
            "ALTER TABLE ecooil_unload_events ADD COLUMN stream_norm VARCHAR(30)",
            "ALTER TABLE ecooil_unload_events ADD COLUMN doc_status VARCHAR(30)",
            "ALTER TABLE ecooil_unload_events ADD COLUMN manifest_path VARCHAR(400)",
            "ALTER TABLE ecooil_unload_events ADD COLUMN manifest_key VARCHAR(500)",
            "ALTER TABLE ecooil_unload_events ADD COLUMN filed_owner VARCHAR(200)",
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
    app.register_blueprint(web)
    app.register_blueprint(field)
    app.register_blueprint(ecooil_bridge)
    app.register_blueprint(ecooil_docs)
    app.register_blueprint(digest)
    app.register_blueprint(reminders)
    app.register_blueprint(depot_admin)
    app.register_blueprint(depot_portal)
    app.register_blueprint(depot_certs)
    app.register_blueprint(depot_assets)

    @app.route("/health")
    def health():
        return {"status": "ok"}, 200

    # Security headers on every response. HSTS only when the request actually
    # arrived over HTTPS (Railway's proxy sets X-Forwarded-Proto) — locally we
    # serve plain HTTP and HSTS would break it.
    from flask import request as _request

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # SAMEORIGIN ולא DENY (24/08): תיבת "הטופס שהלקוח ממלא" במסך ניהול
        # הדיפו מטמיעה את הטופס בתוך הדף — הטמעה מאתרים זרים עדיין חסומה.
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if _request.headers.get("X-Forwarded-Proto", "").lower() == "https" or _request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    return app
