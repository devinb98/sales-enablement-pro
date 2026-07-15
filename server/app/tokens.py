"""Signed auth tokens for cross-origin browser sessions.

The frontend and API are on different Render subdomains, and onrender.com is a
public suffix — so the two are cross-site and the session cookie is a
third-party cookie that modern browsers block. A token sent in an Authorization
header has no such problem: nothing about it is tied to the browser's cookie
policy.

The token is a signed (not encrypted) statement of "user N, issued at time T".
It carries no secret — it only needs to be unforgeable, which the SECRET_KEY
signature provides. Verified server-side on every request via Flask-Login's
request_loader.
"""

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "auth-token"
# Tokens are good for 7 days. A browser refresh re-validates against /api/me, so
# an expired token simply logs the user out and they sign in again.
MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SALT)


def issue_token(user):
    return _serializer().dumps({"user_id": user.id})


def user_id_from_token(token):
    """Return the user id a valid token names, or None if it is missing,
    malformed, tampered with, or expired."""
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")
