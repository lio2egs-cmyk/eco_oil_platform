from flask import Flask
from .routes import main

def create_app():
    app = Flask(__name__)

    app.register_blueprint(main)

    @app.route("/health")
    def health():
        return {"status": "ok"}, 200

    return app
