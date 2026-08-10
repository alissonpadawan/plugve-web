from __future__ import annotations

from flask import Blueprint, jsonify, request

from services.seguro_autoseg_service import (
    COBERTURA,
    DATA_BASE,
    FONTE,
    carregar_taxas_uf,
    estimar_seguro_autoseg_referencia,
)

seguro_bp = Blueprint("seguro", __name__)


@seguro_bp.get("/status")
def seguro_status():
    try:
        total_referencias = len(carregar_taxas_uf())
        configured = total_referencias >= 28
    except RuntimeError:
        total_referencias = 0
        configured = False
    response = jsonify({
        "ok": configured,
        "enabled": True,
        "configured": configured,
        "provider": "autoseg_uf_v1",
        "source_label": FONTE,
        "data_base": DATA_BASE,
        "cobertura_referencia": COBERTURA,
        "referencias": total_referencias,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@seguro_bp.post("/estimar")
def estimar_seguro():
    payload = request.get_json(silent=True) or {}
    veiculo = payload.get("veiculo") or {}
    localizacao = payload.get("localizacao") or {}
    try:
        estimativa = estimar_seguro_autoseg_referencia(
            valor_fipe=float(veiculo.get("valor_fipe") or 0.0),
            uf=str(localizacao.get("uf") or ""),
            ano_modelo=veiculo.get("ano_modelo") or "",
        )
    except (TypeError, ValueError) as exc:
        response = jsonify({"ok": False, "error": str(exc)})
        response.headers["Cache-Control"] = "no-store"
        return response, 400
    except RuntimeError as exc:
        response = jsonify({"ok": False, "error": str(exc)})
        response.headers["Cache-Control"] = "no-store"
        return response, 503

    response = jsonify({"ok": True, "estimativa": estimativa.to_dict()})
    response.headers["Cache-Control"] = "no-store"
    return response
