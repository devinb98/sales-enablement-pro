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


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-for-production")

    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.environ.get("DATABASE_URL", "sqlite:///dev.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # The React origin allowed to send credentialed requests.
    FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")

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
    # Below this cosine similarity we treat retrieval as having found nothing
    # useful and refuse to generate rather than inventing a plan.
    RETRIEVAL_MIN_SCORE = float(os.environ.get("RETRIEVAL_MIN_SCORE", "0.25"))
