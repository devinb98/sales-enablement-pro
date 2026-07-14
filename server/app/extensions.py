from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
bcrypt = Bcrypt()
cors = CORS()
login_manager = LoginManager()


@login_manager.unauthorized_handler
def unauthorized():
    """This is a JSON API, so an unauthenticated request gets a 401 payload
    rather than Flask-Login's default redirect to a login page."""
    return {"error": "authentication required"}, 401
