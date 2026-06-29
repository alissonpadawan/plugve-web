from __future__ import annotations

import os
import threading

from flask import Flask

from config import Config
from routes.main_routes import main_bp
from routes.fipe_routes import fipe_bp
from routes.depreciacao_routes import depreciacao_bp
from routes.tco_routes import tco_bp
from routes.utility_routes import utility_bp
from services.persistent_storage import bootstrap_persistent_storage


def _preaquecer_catalogo_fipe_async(app: Flask) -> None:
    if os.environ.get("PLUGVE_PREWARM_FIPE", "1").strip().lower() in {"0", "false", "nao", "não", "no", "off"}:
        return

    def _worker() -> None:
        try:
            with app.app_context():
                from services.fipe_service import FipeService

                service = FipeService()
                for contexto in ("ve", "icev", ""):
                    service.listar_marcas(contexto=contexto)
        except Exception as exc:
            app.logger.debug("Pré-aquecimento FIPE ignorado: %s", exc)

    threading.Thread(target=_worker, name="plugve-fipe-prewarm", daemon=True).start()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    bootstrap_persistent_storage(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(fipe_bp, url_prefix="/api/fipe")
    app.register_blueprint(depreciacao_bp, url_prefix="/api/depreciacao")
    # Rotas utilitárias usadas pelo Simulador TCO.
    # Registradas antes do TCO para garantir que /preco_energia e /preco_combustivel
    # usem a versão modular, mesmo que existam rotas antigas no módulo TCO.
    app.register_blueprint(utility_bp)
    app.register_blueprint(tco_bp)

    _preaquecer_catalogo_fipe_async(app)

    return app


app = create_app()


if __name__ == "__main__":
    print("Servidor iniciado em http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
