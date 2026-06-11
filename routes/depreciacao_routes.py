from __future__ import annotations

from flask import Blueprint, jsonify, request
import traceback

from services.depreciacao_service import DepreciacaoService
from services.coorte_diagnostico_service import CoorteDiagnosticoService
from services.depreciacao_motor_v1917_adapter import DepreciacaoMotorV1917Adapter

depreciacao_bp = Blueprint("depreciacao", __name__)
depreciacao_service = DepreciacaoService()
coorte_diagnostico_service = CoorteDiagnosticoService()
motor_v1917_adapter = DepreciacaoMotorV1917Adapter()


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



@depreciacao_bp.route("/diagnostico_v1917", methods=["POST"])
def diagnostico_v1917():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = motor_v1917_adapter.diagnosticar(payload)
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "status": "erro_diagnostico_v1917",
            "mensagem": f"Erro interno no diagnóstico V19.17: {type(exc).__name__}: {exc}",
            "traceback_resumo": traceback.format_exc(limit=4),
        }), 200


@depreciacao_bp.route("/diagnostico_v1917/continuar", methods=["POST"])
def diagnostico_v1917_continuar():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = motor_v1917_adapter.continuar(payload)
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "status": "erro_diagnostico_v1917",
            "mensagem": f"Erro interno ao continuar diagnóstico V19.17: {type(exc).__name__}: {exc}",
            "traceback_resumo": traceback.format_exc(limit=4),
        }), 200


@depreciacao_bp.route("/diagnostico_v1917/status/<job_id>", methods=["GET"])
def diagnostico_v1917_status(job_id):
    try:
        resultado = motor_v1917_adapter.status(job_id)
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "status": "erro_status_v1917",
            "mensagem": f"Erro interno ao consultar status V19.17: {type(exc).__name__}: {exc}",
        }), 200

@depreciacao_bp.route("/diagnostico_coorte", methods=["POST"])
def diagnostico_coorte():
    payload = request.get_json(silent=True) or {}
    try:
        resultado = coorte_diagnostico_service.diagnosticar(payload)
        return jsonify(resultado), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "status": "erro_diagnostico",
            "mensagem": f"Erro interno no diagnóstico: {type(exc).__name__}: {exc}",
            "traceback_resumo": traceback.format_exc(limit=4),
        }), 200

@depreciacao_bp.route("/diagnostico", methods=["POST"])
def diagnostico_coorte_alias():
    return diagnostico_coorte()
