import os
from flask import Flask
from .routes import main
from .db import db

def create_app():
    app = Flask(__name__)

    from pathlib import Path

    BASE_DIR = Path(__file__).resolve().parents[2]   # eco_oil_platform/
    DATA_DIR = BASE_DIR / "data"
    DATA_DIR.mkdir(exist_ok=True)

    DB_PATH = DATA_DIR / "app.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH.as_posix()}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    with app.app_context():
    # חשוב: לטעון את כל המודלים לפני create_all, אחרת טבלאות לא יווצרו
        from .db import Client, Asset, DepotPreArrival, Compartment, WashCycle
        db.create_all()

    app.register_blueprint(main)

    @app.route("/health")
    def health():
        return {"status": "ok"}, 200

    return app
