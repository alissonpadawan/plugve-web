from __future__ import annotations

from flask import Blueprint, render_template, redirect, url_for

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template("index.html")


@main_bp.route("/depreciacao")
def depreciacao():
    return render_template("depreciacao.html")


@main_bp.route("/metodologia")
def metodologia():
    return render_template("metodologia.html")
