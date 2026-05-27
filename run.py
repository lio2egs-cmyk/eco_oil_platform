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
    app.run(debug=True, use_reloader=False)
