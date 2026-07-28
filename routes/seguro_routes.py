from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from services.seguro_service import (
    SeguroConfiguracaoError,
    SeguroFonteError,
    SeguroValidacaoError,
    get_seguro_service,
)


seguro_bp = Blueprint("seguro", __name__)


@seguro_bp.get("/status")
def seguro_status():
    response = jsonify({"ok": True, **get_seguro_service().status()})
    response.headers["Cache-Control"] = "no-store"
    return response


@seguro_bp.post("/estimar")
def estimar_seguro():
    payload = request.get_json(silent=True) or {}
    service = get_seguro_service()
    try:
        estimate = service.estimate(payload)
        response = jsonify({"ok": True, "estimativa": estimate.to_dict()})
        status = 200
    except SeguroConfiguracaoError as exc:
        response = jsonify({"ok": False, "configured": False, "error": str(exc)})
        status = 503
    except SeguroValidacaoError as exc:
        response = jsonify({"ok": False, "configured": service.configured, "error": str(exc)})
        status = 400
    except SeguroFonteError as exc:
        current_app.logger.warning("Falha na fonte externa de seguro: %s", exc)
        response = jsonify({
            "ok": False,
            "configured": service.configured,
            "error": "A fonte externa de seguro está indisponível. Tente novamente ou informe a série anual em Ajustar.",
        })
        status = 502
    response.headers["Cache-Control"] = "no-store"
    return response, status
