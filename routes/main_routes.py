from __future__ import annotations

from flask import Blueprint, render_template, redirect, url_for

from services.noticias_service import carregar_noticias_home

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template("index.html", noticias=carregar_noticias_home())


@main_bp.route("/consulta-fipe")
@main_bp.route("/fipe")
def consulta_fipe():
    return render_template("consulta_fipe.html")


@main_bp.route("/depreciacao")
def depreciacao():
    return render_template("depreciacao.html")


@main_bp.route("/depreciacao/auditoria")
def depreciacao_auditoria():
    return render_template("auditoria_depreciacao.html")


@main_bp.route("/metodologia")
def metodologia():
    return redirect(url_for("tco.simular"))


@main_bp.route("/financiamento")
def financiamento():
    return render_template("financiamento.html")
