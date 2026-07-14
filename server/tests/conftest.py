import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db as _db
from app.models import User


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


def make_user(email="rep@example.com", name="Rep One", password="password123"):
    user = User(email=email, name=name)
    user.set_password(password)
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture
def user(app):
    return make_user()


@pytest.fixture
def other_user(app):
    """A second account, used to prove one rep cannot reach another's data."""
    return make_user(email="rival@example.com", name="Rep Two")


def login(client, email="rep@example.com", password="password123"):
    return client.post("/api/login", json={"email": email, "password": password})


@pytest.fixture
def auth_client(client, user):
    login(client)
    return client
