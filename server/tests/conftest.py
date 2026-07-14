import hashlib
import math
import re

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db as _db
from app.models import User
from app.services import vectorstore

EMBEDDING_DIM = 768


def fake_embed(text):
    """A deterministic, offline stand-in for Gemini embeddings.

    Tests must not call the live model: it costs quota, needs a key in CI, and
    makes results non-reproducible. But a random vector would make retrieval
    tests meaningless, so this hashes each word into a bucket. Texts sharing
    words end up with genuinely higher cosine similarity, which means the
    relevance floor and the weak-context gate can be tested for real rather
    than merely mocked around.
    """
    vector = [0.0] * EMBEDDING_DIM
    for word in re.findall(r"\w+", text.lower()):
        bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % EMBEDDING_DIM
        vector[bucket] += 1.0

    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [x / norm for x in vector]


@pytest.fixture(autouse=True)
def offline_embeddings(monkeypatch, tmp_path):
    """Point every embedding call at fake_embed, and give each test its own
    Chroma directory so indexes never leak between tests."""
    # Patch the name in each module that *uses* it, not in the module that
    # defines it. Both importers did `from .embeddings import ...`, which binds
    # the function at import time — patching the source module would leave those
    # bindings pointing at the real thing, and tests would quietly hit the live
    # Gemini API (and mismatch the fake vectors' dimensions).
    monkeypatch.setattr(
        "app.services.ingestion.embed_texts",
        lambda texts: [fake_embed(t) for t in texts],
    )
    monkeypatch.setattr("app.services.rag.embed_query", fake_embed)
    # Chroma's client is cached in a module global; reset it so the new
    # per-test directory actually takes effect.
    vectorstore._client = None
    yield
    vectorstore._client = None


@pytest.fixture
def app(tmp_path):
    class IsolatedTestConfig(TestConfig):
        CHROMA_DIR = str(tmp_path / "chroma")

    app = create_app(IsolatedTestConfig)
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
