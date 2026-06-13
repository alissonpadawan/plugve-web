from __future__ import annotations

from flask import Flask

from config import Config
from routes.main_routes import main_bp
from routes.fipe_routes import fipe_bp
from routes.depreciacao_routes import depreciacao_bp
from routes.tco_routes import tco_bp
from routes.utility_routes import utility_bp
from services.persistent_storage import bootstrap_persistent_storage


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

    return app


app = create_app()


if __name__ == "__main__":
    print("Servidor iniciado em http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
