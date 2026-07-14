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

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app
