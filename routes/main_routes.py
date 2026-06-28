from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, render_template, redirect, url_for

main_bp = Blueprint("main", __name__)


def _carregar_noticias_home() -> list[dict]:
    caminho = Path(__file__).resolve().parents[1] / "data" / "noticias_home.json"
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, list) else []
    except Exception:
        return []


@main_bp.route("/")
def index():
    return render_template("index.html", noticias=_carregar_noticias_home())


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
