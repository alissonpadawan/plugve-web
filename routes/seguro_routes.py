from __future__ import annotations

from flask import Blueprint, jsonify, request

from services.seguro_v2_service import (
    COBERTURA_V2,
    DATA_BASE_V2,
    FONTE_V2,
    estimar_seguro_v2,
    status_seguro_v2,
)

seguro_bp = Blueprint("seguro", __name__)


@seguro_bp.get("/status")
def seguro_status():
    try:
        st = status_seguro_v2()
        configured = bool(st.get("configured"))
    except RuntimeError as exc:
        st = {"configured": False, "autoseg": False, "error": str(exc)}
        configured = False
    response = jsonify({
        "ok": configured,
        "enabled": True,
        "configured": configured,
        "provider": "curve_seguro_v2_ipsa_autoseg",
        "source_label": FONTE_V2,
        "data_base": DATA_BASE_V2,
        "cobertura_referencia": COBERTURA_V2,
        **st,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@seguro_bp.post("/estimar")
def estimar_seguro():
    payload = request.get_json(silent=True) or {}
    veiculo = payload.get("veiculo") or {}
    localizacao = payload.get("localizacao") or {}
    try:
        estimativa = estimar_seguro_v2(
            valor_fipe=float(veiculo.get("valor_fipe") or 0.0),
            uf=str(localizacao.get("uf") or ""),
            municipio=str(localizacao.get("municipio") or ""),
            ano_modelo=veiculo.get("ano_modelo") or "",
            tecnologia=veiculo.get("tecnologia") or "gasolina",
            codigo_fipe=veiculo.get("codigo_fipe") or "",
        )
    except (TypeError, ValueError) as exc:
        response = jsonify({"ok": False, "error": str(exc)})
        response.headers["Cache-Control"] = "no-store"
        return response, 400
    except RuntimeError as exc:
        response = jsonify({"ok": False, "error": str(exc)})
        response.headers["Cache-Control"] = "no-store"
        return response, 503

    response = jsonify({"ok": True, "estimativa": estimativa})
    response.headers["Cache-Control"] = "no-store"
    return response
