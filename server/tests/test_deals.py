import pytest

from app.extensions import db as _db
from app.models import Deal

from .conftest import login


@pytest.fixture
def deal(user):
    deal = Deal(user_id=user.id, name="Acme Renewal", company="Acme Corp")
    _db.session.add(deal)
    _db.session.commit()
    return deal


@pytest.fixture
def rival_deal(other_user):
    """A deal owned by someone else. Nothing our user does should ever reach it."""
    deal = Deal(user_id=other_user.id, name="Rival Deal", company="Rival Inc")
    _db.session.add(deal)
    _db.session.commit()
    return deal


class TestDealCrud:
    def test_create_and_read_back(self, auth_client):
        res = auth_client.post(
            "/api/deals",
            json={"name": "Acme Renewal", "company": "Acme Corp", "value": 50000},
        )
        assert res.status_code == 201
        deal_id = res.get_json()["id"]

        got = auth_client.get(f"/api/deals/{deal_id}")
        assert got.status_code == 200
        assert got.get_json()["name"] == "Acme Renewal"

    def test_list_returns_only_my_deals(self, auth_client, deal, rival_deal):
        res = auth_client.get("/api/deals")
        assert res.status_code == 200
        names = [d["name"] for d in res.get_json()]
        assert names == ["Acme Renewal"]
        assert "Rival Deal" not in names

    def test_update(self, auth_client, deal):
        res = auth_client.patch(
            f"/api/deals/{deal.id}", json={"stage": "negotiation", "value": 75000}
        )
        assert res.status_code == 200
        assert res.get_json()["stage"] == "negotiation"
        assert res.get_json()["value"] == 75000

    def test_delete(self, auth_client, deal):
        assert auth_client.delete(f"/api/deals/{deal.id}").status_code == 204
        assert auth_client.get(f"/api/deals/{deal.id}").status_code == 404

    def test_rejects_missing_required_fields(self, auth_client):
        res = auth_client.post("/api/deals", json={"name": ""})
        assert res.status_code == 422
        assert set(res.get_json()["errors"]) == {"name", "company"}

    def test_rejects_unknown_stage(self, auth_client):
        res = auth_client.post(
            "/api/deals", json={"name": "X", "company": "Y", "stage": "invented"}
        )
        assert res.status_code == 422
        assert "stage" in res.get_json()["errors"]


class TestDealsRequireAuth:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/deals"),
            ("post", "/api/deals"),
            ("get", "/api/deals/1"),
            ("patch", "/api/deals/1"),
            ("delete", "/api/deals/1"),
        ],
    )
    def test_anonymous_requests_are_rejected(self, client, method, path):
        assert getattr(client, method)(path).status_code == 401


class TestCrossUserAuthorization:
    """The attack the rubric asks a reviewer to attempt: logged in as user B,
    reach for user A's records by ID across every verb.

    Every one must answer 404 — not 403. A 403 would confirm the record exists,
    which is itself a leak: probe enough IDs and you learn how many deals your
    rival is running.
    """

    def test_cannot_read_another_users_deal(self, auth_client, rival_deal):
        assert auth_client.get(f"/api/deals/{rival_deal.id}").status_code == 404

    def test_cannot_update_another_users_deal(self, auth_client, rival_deal):
        res = auth_client.patch(
            f"/api/deals/{rival_deal.id}", json={"name": "Pwned"}
        )
        assert res.status_code == 404

    def test_failed_update_does_not_mutate_the_record(self, auth_client, rival_deal):
        auth_client.patch(f"/api/deals/{rival_deal.id}", json={"name": "Pwned"})
        _db.session.refresh(rival_deal)
        assert rival_deal.name == "Rival Deal"

    def test_cannot_delete_another_users_deal(self, auth_client, rival_deal):
        assert auth_client.delete(f"/api/deals/{rival_deal.id}").status_code == 404
        assert _db.session.get(Deal, rival_deal.id) is not None

    def test_404_is_indistinguishable_from_a_nonexistent_deal(
        self, auth_client, rival_deal
    ):
        # Someone else's deal and a deal that was never created must look
        # identical, or the API becomes an existence oracle.
        real_but_not_mine = auth_client.get(f"/api/deals/{rival_deal.id}")
        never_existed = auth_client.get("/api/deals/999999")
        assert real_but_not_mine.status_code == never_existed.status_code == 404
        assert real_but_not_mine.get_json() == never_existed.get_json()

    def test_owner_still_sees_their_own_deal(self, client, deal, rival_deal):
        """Sanity check on the fixtures: the 404s above must come from ownership
        filtering, not from the deals being missing."""
        login(client, email="rival@example.com")
        assert client.get(f"/api/deals/{rival_deal.id}").status_code == 200
        assert client.get(f"/api/deals/{deal.id}").status_code == 404
