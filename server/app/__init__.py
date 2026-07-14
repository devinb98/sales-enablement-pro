from flask import Flask

from .config import Config
from .extensions import bcrypt, cors, db, login_manager, migrate


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

    app.register_blueprint(auth_bp)
    app.register_blueprint(deals_bp)

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
