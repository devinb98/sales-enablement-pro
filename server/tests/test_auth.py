from app.models import User

from .conftest import login


class TestSignup:
    def test_creates_user_and_logs_them_in(self, client, db):
        res = client.post(
            "/api/signup",
            json={"email": "New@Example.com", "password": "password123", "name": "New"},
        )
        assert res.status_code == 201
        assert res.get_json()["email"] == "new@example.com"  # normalized

        # The signup response should log the user in, so /api/me works straight away.
        assert client.get("/api/me").status_code == 200

    def test_never_returns_the_password_hash(self, client):
        res = client.post(
            "/api/signup",
            json={"email": "a@b.co", "password": "password123", "name": "A"},
        )
        assert "password_hash" not in res.get_json()
        assert "password" not in res.get_json()

    def test_stores_password_hashed_not_plaintext(self, client, db):
        client.post(
            "/api/signup",
            json={"email": "a@b.co", "password": "password123", "name": "A"},
        )
        user = db.session.query(User).filter_by(email="a@b.co").one()
        assert user.password_hash != "password123"
        assert user.check_password("password123")
        assert not user.check_password("wrong")

    def test_rejects_short_password(self, client):
        res = client.post(
            "/api/signup", json={"email": "a@b.co", "password": "short", "name": "A"}
        )
        assert res.status_code == 422
        assert "password" in res.get_json()["errors"]

    def test_rejects_invalid_email(self, client):
        res = client.post(
            "/api/signup",
            json={"email": "not-an-email", "password": "password123", "name": "A"},
        )
        assert res.status_code == 422
        assert "email" in res.get_json()["errors"]

    def test_rejects_duplicate_email_without_confirming_it_exists(self, client, user):
        res = client.post(
            "/api/signup",
            json={"email": "rep@example.com", "password": "password123", "name": "X"},
        )
        assert res.status_code == 422
        # Must not reveal that this email is already registered.
        assert "not available" in res.get_json()["errors"]["email"]


class TestLogin:
    def test_succeeds_with_correct_credentials(self, client, user):
        res = login(client)
        assert res.status_code == 200
        assert res.get_json()["email"] == "rep@example.com"

    def test_rejects_wrong_password(self, client, user):
        res = login(client, password="wrong-password")
        assert res.status_code == 401

    def test_gives_same_error_for_unknown_email_and_wrong_password(self, client, user):
        unknown = login(client, email="nobody@example.com")
        wrong_pw = login(client, password="wrong-password")
        # Identical responses, so login cannot be used to enumerate accounts.
        assert unknown.status_code == wrong_pw.status_code == 401
        assert unknown.get_json() == wrong_pw.get_json()


class TestSessionAndLogout:
    def test_me_requires_authentication(self, client):
        assert client.get("/api/me").status_code == 401

    def test_me_returns_current_user_when_logged_in(self, auth_client):
        res = auth_client.get("/api/me")
        assert res.status_code == 200
        assert res.get_json()["email"] == "rep@example.com"

    def test_session_persists_across_requests(self, auth_client):
        assert auth_client.get("/api/me").status_code == 200
        assert auth_client.get("/api/me").status_code == 200

    def test_logout_ends_the_session(self, auth_client):
        assert auth_client.delete("/api/logout").status_code == 204
        assert auth_client.get("/api/me").status_code == 401

    def test_logout_requires_authentication(self, client):
        assert client.delete("/api/logout").status_code == 401
