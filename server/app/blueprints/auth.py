import re

from flask import Blueprint, request
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import User
from ..tokens import issue_token

auth_bp = Blueprint("auth", __name__, url_prefix="/api")


def _auth_response(user, status):
    """Return the user plus a bearer token. The token is what makes auth work in
    a cross-origin browser, where the session cookie is blocked; login_user still
    sets the cookie for same-origin dev and tests."""
    payload = user.to_dict()
    payload["token"] = issue_token(user)
    return payload, status

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


@auth_bp.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""

    errors = {}
    if not EMAIL_RE.match(email):
        errors["email"] = "A valid email address is required."
    if not name:
        errors["name"] = "Name is required."
    if len(password) < MIN_PASSWORD_LENGTH:
        errors["password"] = (
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if errors:
        return {"errors": errors}, 422

    if db.session.query(User.id).filter_by(email=email).first():
        # Deliberately vague: confirming which emails are registered would let
        # anyone enumerate our users.
        return {"errors": {"email": "That email is not available."}}, 422

    user = User(email=email, name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    login_user(user)
    return _auth_response(user, 201)


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = db.session.query(User).filter_by(email=email).first()
    if user is None or not user.check_password(password):
        # One message for both "no such user" and "wrong password", so the
        # response cannot be used to discover which emails exist.
        return {"error": "Invalid email or password."}, 401

    login_user(user)
    return _auth_response(user, 200)


@auth_bp.delete("/logout")
@login_required
def logout():
    logout_user()
    return "", 204


@auth_bp.get("/me")
@login_required
def me():
    """Session check. The frontend calls this on load to restore login state."""
    return current_user.to_dict(), 200
