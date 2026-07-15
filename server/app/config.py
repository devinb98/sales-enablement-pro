import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _normalize_db_url(url: str) -> str:
    """Render exposes DATABASE_URL with the legacy `postgres://` scheme, which
    SQLAlchemy 2.x refuses to parse. Rewrite it to the dialect it expects."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _normalize_origin(value: str) -> str:
    """Turn a bare hostname into a full origin.

    Render's blueprint can inject another service's *host* but not its URL, so
    FRONTEND_ORIGIN arrives as "my-app.onrender.com". CORS compares origins
    literally: a missing scheme means the header never matches and every
    credentialed request fails — the classic "works locally, 401s in
    production" trap.
    """
    if not value:
        return value
    if value.startswith(("http://", "https://")):
        return value.rstrip("/")
    # Bare hostname. localhost is plain HTTP; anything else on Render is HTTPS.
    scheme = "http" if value.startswith("localhost") else "https"
    return f"{scheme}://{value}".rstrip("/")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-for-production")

    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.environ.get("DATABASE_URL", "sqlite:///dev.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # The React origin allowed to send credentialed requests.
    FRONTEND_ORIGIN = _normalize_origin(
        os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
    )

    # Session cookie. In production the frontend and API are on different Render
    # hosts, so the cookie must be SameSite=None to be sent cross-site — and
    # browsers only accept SameSite=None when Secure is also set.
    IS_PRODUCTION = os.environ.get("FLASK_ENV") == "production"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    SESSION_COOKIE_SAMESITE = "None" if IS_PRODUCTION else "Lax"

    # AI services
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    PRESENTON_API_KEY = os.environ.get("PRESENTON_API_KEY")
    PRESENTON_BASE_URL = os.environ.get(
        "PRESENTON_BASE_URL", "https://api.presenton.ai"
    )
    # Presenton is credit-metered per slide. Live calls stay off unless asked for,
    # so development and tests run offline against a fixture.
    PRESENTON_LIVE = os.environ.get("PRESENTON_LIVE") == "1"

    # Retrieval tuning
    CHROMA_DIR = os.environ.get("CHROMA_DIR", "/tmp/chroma")
    RETRIEVAL_TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", "8"))
    # Cosine floor below which a chunk is treated as irrelevant.
    #
    # Calibrated against gemini-embedding-001, whose vectors are not
    # zero-centered: real deal content scores 0.62-0.68 against a planning query
    # while a banana bread recipe still scores 0.51 and gibberish 0.54. The floor
    # sits just under real content. It is deliberately only the *first* of two
    # gates — see app/services/rag.py — because the margin is ~0.03 and no single
    # cosine threshold is trustworthy in a band that tight.
    #
    # This number is specific to this embedding model. Change the model and it
    # must be re-measured.
    RETRIEVAL_MIN_SCORE = float(os.environ.get("RETRIEVAL_MIN_SCORE", "0.60"))

    # Chroma is a derived index on an ephemeral disk; rebuild it from SQL at boot.
    REBUILD_INDEX_ON_STARTUP = True


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # Generation runs in a worker thread. A default in-memory SQLite gives each
    # connection its own separate database, so that thread would see an empty DB.
    # StaticPool shares one connection across threads, and check_same_thread lets
    # SQLite be used from the pool thread. Production is Postgres, where every
    # pooled connection already talks to the same database, so this is test-only.
    from sqlalchemy.pool import StaticPool

    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    # Tests must never spend Presenton credits or call a live model.
    PRESENTON_LIVE = False
    # Tests use an offline bag-of-words embedder (tests/conftest.py), which
    # produces a different similarity scale than Gemini: on-topic ~0.40,
    # unrelated ~0.08. The floor has to be calibrated to whichever embedder is
    # in play, so it is set for the fake one here rather than inherited.
    RETRIEVAL_MIN_SCORE = 0.25
    # Each test gets a fresh in-memory database, so there is nothing to rebuild
    # from — and booting the index on every app fixture would be slow.
    REBUILD_INDEX_ON_STARTUP = False
