from flask import Blueprint

main = Blueprint("main", __name__)

@main.route("/")
def home():
    return "Eco-Oil Platform is running."
