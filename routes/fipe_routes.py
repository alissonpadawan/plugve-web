from __future__ import annotations

from flask import Blueprint, jsonify, request

from services.fipe_service import FipeService

fipe_bp = Blueprint("fipe", __name__)
fipe_service = FipeService()


@fipe_bp.route("/marcas")
def marcas():
    try:
        return jsonify(fipe_service.listar_marcas())
    except Exception as exc:
        return jsonify({"erro": str(exc)}), 500


@fipe_bp.route("/modelos")
def modelos():
    codigo_marca = request.args.get("codigo_marca", "").strip()
    if not codigo_marca:
        return jsonify({"modelos": []})
    try:
        return jsonify(fipe_service.listar_modelos(codigo_marca))
    except Exception as exc:
        return jsonify({"erro": str(exc), "modelos": []}), 500


@fipe_bp.route("/anos")
def anos():
    codigo_marca = request.args.get("codigo_marca", "").strip()
    codigo_modelo = request.args.get("codigo_modelo", "").strip()
    if not codigo_marca or not codigo_modelo:
        return jsonify([])
    try:
        return jsonify(fipe_service.listar_anos(codigo_marca, codigo_modelo))
    except Exception as exc:
        return jsonify({"erro": str(exc)}), 500


@fipe_bp.route("/bloquear_modelo", methods=["POST"])
def bloquear_modelo():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    codigo_modelo = str(payload.get("codigo_modelo", "")).strip()
    if not codigo_marca or not codigo_modelo:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.bloquear_modelo_antigo(
            codigo_marca=codigo_marca,
            codigo_modelo=codigo_modelo,
            nome_marca=str(payload.get("marca", "")).strip(),
            nome_modelo=str(payload.get("modelo", "")).strip(),
            motivo=str(payload.get("motivo", "sem_ano_2012_ou_zero_km")).strip(),
        ))
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500


@fipe_bp.route("/marcar_zero_km", methods=["POST"])
def marcar_zero_km():
    payload = request.get_json(silent=True) or {}
    codigo_marca = str(payload.get("codigo_marca", "")).strip()
    codigo_modelo = str(payload.get("codigo_modelo", "")).strip()
    if not codigo_marca or not codigo_modelo:
        return jsonify({"ok": False, "erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.marcar_modelo_zero_km(
            codigo_marca=codigo_marca,
            codigo_modelo=codigo_modelo,
            nome_marca=str(payload.get("marca", "")).strip(),
            nome_modelo=str(payload.get("modelo", "")).strip(),
        ))
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500


@fipe_bp.route("/preco")
def preco():
    codigo_marca = request.args.get("codigo_marca", "").strip()
    codigo_modelo = request.args.get("codigo_modelo", "").strip()
    codigo_ano = request.args.get("codigo_ano", "").strip()
    if not codigo_marca or not codigo_modelo or not codigo_ano:
        return jsonify({"erro": "Parâmetros incompletos."}), 400
    try:
        return jsonify(fipe_service.consultar_preco(codigo_marca, codigo_modelo, codigo_ano))
    except Exception as exc:
        return jsonify({"erro": str(exc)}), 500
