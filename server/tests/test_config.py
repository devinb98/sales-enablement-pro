"""Production configuration, tested because it is the part that cannot be
exercised locally and fails silently when it is wrong.

The classic deployment bug for a split frontend/backend is a cookie the browser
quietly refuses to send: everything works on localhost, and every request 401s in
production. These assertions pin down the settings that prevent it.
"""

import importlib

import pytest

from app.config import _normalize_db_url, _normalize_origin


class TestDatabaseUrl:
    def test_rewrites_renders_legacy_postgres_scheme(self):
        # Render hands out postgres://, which SQLAlchemy 2.x refuses to parse.
        assert _normalize_db_url("postgres://u:p@host/db") == "postgresql://u:p@host/db"

    def test_leaves_a_correct_url_alone(self):
        assert _normalize_db_url("postgresql://u:p@host/db") == "postgresql://u:p@host/db"
        assert _normalize_db_url("sqlite:///dev.db") == "sqlite:///dev.db"

    def test_only_rewrites_the_scheme_not_the_body(self):
        url = _normalize_db_url("postgres://user:postgres://@host/db")
        assert url.startswith("postgresql://")
        # The password happens to contain the scheme string; it must survive.
        assert "postgres://@host" in url


class TestOriginNormalization:
    """Render's blueprint can inject another service's host but not its URL, so
    FRONTEND_ORIGIN arrives as a bare hostname. CORS compares origins literally —
    a missing scheme means the header never matches and every credentialed
    request fails."""

    def test_adds_https_to_a_bare_render_hostname(self):
        assert _normalize_origin("my-app.onrender.com") == "https://my-app.onrender.com"

    def test_leaves_a_full_origin_alone(self):
        assert _normalize_origin("https://my-app.onrender.com") == "https://my-app.onrender.com"

    def test_uses_http_for_localhost(self):
        assert _normalize_origin("localhost:5173") == "http://localhost:5173"

    def test_strips_a_trailing_slash(self):
        # "https://x.com/" never equals the Origin header "https://x.com".
        assert _normalize_origin("https://my-app.onrender.com/") == "https://my-app.onrender.com"

    def test_handles_an_empty_value(self):
        assert _normalize_origin("") == ""


class TestSessionCookie:
    def test_production_cookie_is_cross_site_capable(self, monkeypatch):
        """Frontend and API are different Render hosts, so the session cookie is
        sent cross-site. Browsers only accept SameSite=None when Secure is set —
        get either wrong and the cookie is silently dropped."""
        monkeypatch.setenv("FLASK_ENV", "production")

        import app.config

        importlib.reload(app.config)
        config = app.config.Config

        assert config.IS_PRODUCTION is True
        assert config.SESSION_COOKIE_SAMESITE == "None"
        assert config.SESSION_COOKIE_SECURE is True
        assert config.SESSION_COOKIE_HTTPONLY is True  # not readable by JS

        monkeypatch.delenv("FLASK_ENV")
        importlib.reload(app.config)

    def test_development_cookie_does_not_require_https(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "development")

        import app.config

        importlib.reload(app.config)
        config = app.config.Config

        # Secure=True would stop the cookie working on plain-HTTP localhost.
        assert config.SESSION_COOKIE_SECURE is False
        assert config.SESSION_COOKIE_SAMESITE == "Lax"

        monkeypatch.delenv("FLASK_ENV")
        importlib.reload(app.config)


class TestCorsAllowsCredentials:
    def test_preflight_permits_the_frontend_origin_with_credentials(self, app, client):
        origin = app.config["FRONTEND_ORIGIN"]
        res = client.options(
            "/api/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert res.status_code in (200, 204)
        # Must echo the exact origin: "*" is rejected by browsers when
        # credentials are involved, so a wildcard here would break login.
        assert res.headers.get("Access-Control-Allow-Origin") == origin
        assert res.headers.get("Access-Control-Allow-Credentials") == "true"

    def test_an_unknown_origin_is_not_granted_access(self, client):
        res = client.options(
            "/api/login",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert res.headers.get("Access-Control-Allow-Origin") != "https://evil.example.com"