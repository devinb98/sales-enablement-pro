import logging

from flask import Flask

from .config import Config
from .extensions import bcrypt, cors, db, login_manager, migrate

log = logging.getLogger(__name__)


def _rebuild_vector_index(app):
    """Repopulate Chroma from SQL at boot.

    The index lives on an ephemeral filesystem, so on Render it starts empty
    after every deploy and restart. Rebuilding here is what makes that a
    non-event. A failure is logged rather than raised: the app should still come
    up and serve auth and CRUD even if retrieval is temporarily degraded.
    """
    from .services import vectorstore

    try:
        count = vectorstore.rebuild_from_sql(app)
        log.info("Vector index ready (%d chunks).", count)
    except Exception:  # noqa: BLE001
        log.exception("Vector index rebuild failed; retrieval will be degraded.")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    login_manager.init_app(app)

    # Credentialed CORS requires an explicit origin — "*" is rejected by browsers
    # when cookies are in play.
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": [app.config["FRONTEND_ORIGIN"]]}},
        supports_credentials=True,
    )

    # Imported for their side effect of registering with SQLAlchemy's metadata,
    # which Flask-Migrate needs in order to autogenerate migrations.
    from . import models  # noqa: F401
    from .blueprints.auth import auth_bp
    from .blueprints.deals import deals_bp
    from .blueprints.documents import documents_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(deals_bp)
    app.register_blueprint(documents_bp)

    if app.config.get("REBUILD_INDEX_ON_STARTUP"):
        _rebuild_vector_index(app)

    # Flask's default error pages are HTML. This is a JSON API, so every error a
    # client can provoke must come back as JSON or the frontend chokes trying to
    # parse it.
    @app.errorhandler(404)
    def not_found(err):
        return {"error": getattr(err, "description", "Not found")}, 404

    @app.errorhandler(405)
    def method_not_allowed(err):
        return {"error": "Method not allowed"}, 405

    @app.errorhandler(500)
    def server_error(err):
        return {"error": "Internal server error"}, 500

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
