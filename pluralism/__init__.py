from flask import Blueprint, render_template, jsonify

from pluralism.denominations_data import DENOMINATIONS

pluralism_bp = Blueprint(
    "pluralism",
    __name__,
    url_prefix="/Pluralism",
    template_folder="../templates/pluralism",
    static_folder="../static/pluralism",
    static_url_path="/static/pluralism",
)


@pluralism_bp.route("/")
def index():
    return render_template("base.html")


@pluralism_bp.route("/api/denominations")
def get_denominations():
    return jsonify(DENOMINATIONS)
