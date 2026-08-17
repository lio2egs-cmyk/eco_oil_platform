from dotenv import load_dotenv

# Load environment variables from .env (gitignored) before creating the app.
# .env holds SMTP credentials and other local-dev settings; production deploys
# inject env vars directly so .env is not needed there.
load_dotenv()

from src.app import create_app


app = create_app()

with app.app_context():
    from src.app.db import db
    db.create_all()


if __name__ == "__main__":
    # PORT lets a second local instance run alongside the usual one on 5000
    # (production uses gunicorn, not this block).
    import os

    app.run(debug=True, use_reloader=False, port=int(os.environ.get("PORT", 5000)))
