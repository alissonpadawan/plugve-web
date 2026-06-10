from __future__ import annotations

from flask import Blueprint, jsonify, request

from services.depreciacao_service import DepreciacaoService
from services.coorte_diagnostico_service import CoorteDiagnosticoService

depreciacao_bp = Blueprint("depreciacao", __name__)
depreciacao_service = DepreciacaoService()
coorte_diagnostico_service = CoorteDiagnosticoService()


@depreciacao_bp.route("/status")
def status():
    return jsonify(depreciacao_service.status_bases())


@depreciacao_bp.route("/painel")
def painel():
    try:
        return jsonify(depreciacao_service.painel_dados())
    except Exception as exc:
        return jsonify({"erro": str(exc)}), 500


@depreciacao_bp.route("/resumo", methods=["POST"])
def resumo():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = depreciacao_service.obter_resumo(payload)
        return jsonify(resultado)
    except Exception as exc:
        return jsonify({"encontrado": False, "erro": str(exc)}), 500


@depreciacao_bp.route("/calcular", methods=["POST"])
def calcular():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = depreciacao_service.preparar_calculo_sob_demanda(payload)
        return jsonify(resultado)
    except Exception as exc:
        return jsonify({"ok": False, "status": "erro_controlado", "mensagem": str(exc)}), 200


@depreciacao_bp.route("/apagar_curva", methods=["POST"])
def apagar_curva():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = depreciacao_service.apagar_curva_manual(payload)
        return jsonify(resultado)
    except Exception as exc:
        return jsonify({"ok": False, "mensagem": str(exc)}), 200


@depreciacao_bp.route("/diagnostico_coorte", methods=["POST"])
def diagnostico_coorte():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = coorte_diagnostico_service.diagnosticar(payload)
        return jsonify(resultado)
    except Exception as exc:
        return jsonify({"ok": False, "status": "erro_diagnostico", "mensagem": str(exc)}), 200
