"""Application factory de NoticIA EC.

TODOS los blueprints se registran aqui de una vez, aunque alguno empiece vacio.
Es a proposito: asi cada issue solo toca su propio archivo de rutas y este
archivo no genera conflictos de merge.

    /api/tendencias/top-temas        -> Annabella  (issue #1)
    /api/medios/*                    -> Valentina  (issue #2)
    /api/tendencias/series-semanales -> Cristian   (issue #3)
    /api/asistente/*                 -> Cristian   (issue #3)
    /  y  /static-dashboard/*        -> Annabella  (issue #6, dashboard web)
    /api/noticias                    -> Cristian   (issue #8, buscador)
    /api/temas                       -> catalogo compartido por las vistas
"""

from flask import Flask, jsonify

from backend import db
from backend.config import obtener_config
from backend.routes.asistente import asistente_bp
from backend.routes.dashboard import dashboard_bp
from backend.routes.medios import medios_bp
from backend.routes.noticias import noticias_bp
from backend.routes.series import series_bp
from backend.routes.temas import temas_bp
from backend.routes.tendencias import tendencias_bp


def crear_app(testing: bool = False, database_url: str | None = None) -> Flask:
    app = Flask(__name__)

    config = obtener_config(testing=testing)
    app.config["DATABASE_URL"] = database_url or config.DATABASE_URL
    app.config["SCHEMA_PATH"] = config.SCHEMA_PATH
    app.config["TESTING"] = config.TESTING
    # Se resuelve al arrancar, no en cada peticion: si falta API_KEY queremos
    # enterarnos al levantar la app y no con un 500 en medio de una consulta.
    app.config["API_KEY"] = config.api_key

    app.register_blueprint(tendencias_bp, url_prefix="/api/tendencias")
    app.register_blueprint(medios_bp, url_prefix="/api/medios")
    app.register_blueprint(series_bp, url_prefix="/api/tendencias")
    app.register_blueprint(asistente_bp, url_prefix="/api/asistente")
    app.register_blueprint(noticias_bp, url_prefix="/api/noticias")
    app.register_blueprint(temas_bp, url_prefix="/api/temas")
    # Sin prefijo: el dashboard vive en la raiz para compartir origen con la API.
    app.register_blueprint(dashboard_bp)

    app.teardown_appcontext(db.cerrar_conexion)

    _registrar_errores(app)

    @app.get("/health")
    def health():
        """Sonda sin autenticacion, util para verificar que la app levanta."""
        return jsonify({"estado": "ok"})

    return app


def _registrar_errores(app: Flask) -> None:
    """La API siempre responde JSON, nunca las paginas HTML por defecto."""

    @app.errorhandler(400)
    def _400(error):
        return jsonify({"error": getattr(error, "description", "Peticion invalida")}), 400

    @app.errorhandler(401)
    def _401(_error):
        return jsonify({"error": "API key invalida o ausente"}), 401

    @app.errorhandler(404)
    def _404(_error):
        return jsonify({"error": "Recurso no encontrado"}), 404

    @app.errorhandler(405)
    def _405(_error):
        return jsonify({"error": "Metodo no permitido"}), 405

    @app.errorhandler(500)
    def _500(_error):
        # No se filtra el detalle interno al cliente; queda en el log del server.
        return jsonify({"error": "Error interno del servidor"}), 500


if __name__ == "__main__":
    crear_app().run(debug=True, port=5000)
