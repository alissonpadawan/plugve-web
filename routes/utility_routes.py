from __future__ import annotations

from flask import Blueprint, jsonify, request

from services.combustivel_service import obter_preco_gasolina
from services.energia_service import obter_tarifa_energia, TARIFA_FALLBACK_UF

utility_bp = Blueprint("utility", __name__)


@utility_bp.route("/preco_combustivel")
def preco_combustivel():
    uf = (request.args.get("uf", "") or "").upper()
    municipio = request.args.get("municipio", "") or ""
    if not uf or not municipio:
        return jsonify({"erro": "UF e município são obrigatórios"}), 400
    try:
        preco = obter_preco_gasolina(uf, municipio)
        return jsonify({"preco": preco, "uf": uf, "municipio": municipio})
    except Exception as exc:
        print("[ANP] Erro no endpoint /preco_combustivel:", exc)
        return jsonify({"erro": "Falha ao calcular preço de combustível"}), 500


@utility_bp.route("/preco_energia")
def preco_energia():
    uf = (request.args.get("uf", "") or "").upper()
    municipio = request.args.get("municipio", "") or ""
    if not uf or not municipio:
        return jsonify({
            "tarifa_kwh": None,
            "tarifa_base_kwh": None,
            "distribuidora": None,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "detalhe": None,
            "mensagem": "UF e município são obrigatórios.",
        }), 400
    try:
        return jsonify(obter_tarifa_energia(uf, municipio))
    except Exception as exc:
        print("[ENERGIA] Erro no endpoint /preco_energia:", exc)
        tarifa = TARIFA_FALLBACK_UF.get(uf, 0.80)
        return jsonify({
            "tarifa_kwh": round(float(tarifa), 5),
            "tarifa_base_kwh": round(float(tarifa), 5),
            "distribuidora": None,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "detalhe": {
                "base_tarifaria": "Estimativa local",
                "detalhe_aneel": "Fallback usado porque houve erro na consulta automática",
            },
            "mensagem": f"Tarifa preenchida por estimativa local para {uf}, pois a consulta automática falhou. Ajuste manualmente se necessário.",
        }), 200
