from src.app import create_app


app = create_app()

with app.app_context():
    from src.app.db import db
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
