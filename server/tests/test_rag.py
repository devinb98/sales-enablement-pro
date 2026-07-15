import io

import pytest

from app.extensions import db as _db
from app.models import ActionItem, ActionPlan, Citation, Deal
from app.services.rag import GeneratedActionItem, GeneratedPlan, NextStep

from .conftest import login

MEETING_NOTE = (
    "Discovery call with Acme Corp on July 10.\n\n"
    "Rita Chen (VP Engineering) confirmed the security questionnaire must be "
    "returned by August 1 or procurement will not advance the deal.\n\n"
    "Acme's economic buyer is CFO Dan Ortiz, who has not yet been introduced.\n\n"
    "We committed to sending SOC2 evidence and a revised pricing sheet by Friday."
)

IRRELEVANT = (
    "Banana bread recipe. Preheat oven to 350 degrees. Mash three ripe bananas "
    "with butter and sugar, then fold in flour and baking soda. Bake 60 minutes "
    "until a skewer comes out clean. Let cool before slicing and serving."
)


@pytest.fixture
def deal(user):
    deal = Deal(user_id=user.id, name="Acme Renewal", company="Acme Corp")
    _db.session.add(deal)
    _db.session.commit()
    return deal


@pytest.fixture
def rival_deal(other_user):
    deal = Deal(user_id=other_user.id, name="Rival Deal", company="Rival Inc")
    _db.session.add(deal)
    _db.session.commit()
    return deal


def upload(client, deal_id, content=MEETING_NOTE, filename="notes.txt"):
    return client.post(
        f"/api/deals/{deal_id}/documents",
        data={"file": (io.BytesIO(content.encode()), filename), "doc_type": "meeting_note"},
        content_type="multipart/form-data",
    )


@pytest.fixture
def fake_llm(monkeypatch):
    """Stand in for Gemini. Tests must not call a live model — it costs quota and
    makes assertions non-deterministic. The retrieval, gating, citation, and
    authorization logic under test is all ours, not the model's.

    Note source_id 99: models really do cite sources that don't exist, and the
    pipeline must drop those rather than render a citation that leads nowhere.
    """
    plan = GeneratedPlan(
        summary="Acme is in discovery. A security questionnaire is blocking procurement.",
        next_steps=[
            NextStep(step="Return the security questionnaire by August 1.", source_ids=[1]),
            NextStep(step="Get introduced to CFO Dan Ortiz.", source_ids=[1, 99]),
        ],
        action_items=[
            GeneratedActionItem(
                title="Send SOC2 evidence",
                detail="Committed on the July 10 call; due Friday.",
                priority="high",
                source_ids=[1],
            ),
            GeneratedActionItem(
                title="Invent something unsupported",
                detail="Cites a source that does not exist.",
                priority="low",
                source_ids=[99],
            ),
        ],
    )
    # _generate returns (plan, model_name) so the plan can record which model
    # in the fallback chain actually answered.
    monkeypatch.setattr(
        "app.services.rag._generate", lambda deal, sources: (plan, "fake-model")
    )
    return plan


class TestGeneration:
    def test_generates_a_plan_from_uploaded_documents(self, auth_client, deal, fake_llm):
        upload(auth_client, deal.id)
        res = auth_client.post(f"/api/deals/{deal.id}/action-plans")
        assert res.status_code == 201

        body = res.get_json()
        assert "security questionnaire" in body["summary"]
        assert len(body["items"]) == 2
        assert len(body["next_steps"]) == 2

    def test_persists_the_plan_as_a_revisitable_record(self, auth_client, deal, fake_llm, db):
        upload(auth_client, deal.id)
        plan_id = auth_client.post(f"/api/deals/{deal.id}/action-plans").get_json()["id"]

        # The plan is a stored artifact, not a chat message that scrolls away.
        again = auth_client.get(f"/api/action-plans/{plan_id}")
        assert again.status_code == 200
        assert db.session.get(ActionPlan, plan_id) is not None

    def test_every_citation_resolves_to_a_real_document_passage(
        self, auth_client, deal, fake_llm, db
    ):
        upload(auth_client, deal.id)
        body = auth_client.post(f"/api/deals/{deal.id}/action-plans").get_json()

        assert body["citations"], "a source-backed plan must carry citations"
        for citation in body["citations"]:
            # The whole promise of the feature: a number leads back to real text
            # the user can read, in a named document.
            assert citation["quote"].strip()
            assert citation["filename"] == "notes.txt"
            assert citation["quote"] in MEETING_NOTE
            assert db.session.get(Citation, citation["id"]) is not None

    def test_drops_citations_the_model_invented(self, auth_client, deal, fake_llm):
        """The model cited source 99, which does not exist. Rendering it would
        produce a citation chip that leads nowhere — worse than no citation."""
        upload(auth_client, deal.id)
        body = auth_client.post(f"/api/deals/{deal.id}/action-plans").get_json()

        valid = {c["source_number"] for c in body["citations"]}
        assert 99 not in valid

        for step in body["next_steps"]:
            assert all(sid in valid for sid in step["source_ids"])
        for item in body["items"]:
            assert all(sid in valid for sid in item["source_ids"])

        # The item that cited only the invented source keeps its text but loses
        # the bogus citation, rather than being silently dropped.
        unsupported = next(i for i in body["items"] if i["title"].startswith("Invent"))
        assert unsupported["source_ids"] == []


class TestWeakContextGate:
    """Refusing to answer is the feature. A rep cannot act on a step they cannot
    trace to something the customer said, so a fluent guess is worse than an
    honest refusal — it is indistinguishable from a real answer."""

    def test_refuses_when_the_deal_has_no_documents(self, auth_client, deal, fake_llm):
        res = auth_client.post(f"/api/deals/{deal.id}/action-plans")
        assert res.status_code == 422
        assert res.get_json()["error"] == "insufficient_context"
        assert "upload" in res.get_json()["message"].lower()

    def test_refuses_when_documents_are_irrelevant(self, auth_client, deal, fake_llm):
        upload(auth_client, deal.id, content=IRRELEVANT, filename="recipe.txt")
        res = auth_client.post(f"/api/deals/{deal.id}/action-plans")
        assert res.status_code == 422
        assert res.get_json()["error"] == "insufficient_context"

    def test_refusal_persists_nothing(self, auth_client, deal, fake_llm, db):
        auth_client.post(f"/api/deals/{deal.id}/action-plans")
        assert db.session.query(ActionPlan).count() == 0
        assert db.session.query(ActionItem).count() == 0


class TestGenerationTimeout:
    """Generation runs under a hard wall-clock budget, because the Gemini client
    ignores every timeout we can pass it. A stalled call must return a clean
    error, never hang the worker until the platform restarts the service."""

    def test_a_stalled_generation_returns_503_not_a_hang(
        self, auth_client, deal, monkeypatch, app
    ):
        import time

        # Shrink the budget so the test is fast, and make generation overrun it.
        app.config["GENERATION_BUDGET_SECONDS"] = 1

        def slow_generate(deal_arg):
            time.sleep(5)  # longer than the 1s budget

        monkeypatch.setattr(
            "app.blueprints.action_plans.generate_action_plan", slow_generate
        )

        import io

        auth_client.post(
            f"/api/deals/{deal.id}/documents",
            data={"file": (io.BytesIO(b"x" * 200), "n.txt"), "doc_type": "meeting_note"},
            content_type="multipart/form-data",
        )
        res = auth_client.post(f"/api/deals/{deal.id}/action-plans")

        assert res.status_code == 503
        assert res.get_json()["error"] == "ai_timeout"


class TestActionItems:
    @pytest.fixture
    def plan(self, auth_client, deal, fake_llm):
        upload(auth_client, deal.id)
        return auth_client.post(f"/api/deals/{deal.id}/action-plans").get_json()

    def test_check_an_item_off(self, auth_client, plan):
        item_id = plan["items"][0]["id"]
        res = auth_client.patch(f"/api/action-items/{item_id}", json={"status": "done"})
        assert res.status_code == 200
        assert res.get_json()["status"] == "done"

    def test_edit_an_items_text(self, auth_client, plan):
        item_id = plan["items"][0]["id"]
        res = auth_client.patch(
            f"/api/action-items/{item_id}", json={"title": "Send SOC2 report to Rita"}
        )
        assert res.get_json()["title"] == "Send SOC2 report to Rita"

    def test_add_the_reps_own_item(self, auth_client, plan):
        res = auth_client.post(
            f"/api/action-plans/{plan['id']}/items",
            json={"title": "Call Rita on Monday", "priority": "high"},
        )
        assert res.status_code == 201
        # Flagged as the rep's, so the UI can distinguish it from AI output.
        assert res.get_json()["is_user_created"] is True

    def test_delete_an_item(self, auth_client, plan, db):
        item_id = plan["items"][0]["id"]
        assert auth_client.delete(f"/api/action-items/{item_id}").status_code == 204
        assert db.session.get(ActionItem, item_id) is None

    def test_rejects_invalid_status(self, auth_client, plan):
        item_id = plan["items"][0]["id"]
        res = auth_client.patch(f"/api/action-items/{item_id}", json={"status": "maybe"})
        assert res.status_code == 422


class TestPlanAuthorization:
    @pytest.fixture
    def rival_plan(self, client, user, rival_deal, fake_llm):
        """A plan owned by someone else, created through the real pipeline."""
        login(client, email="rival@example.com")
        upload(client, rival_deal.id)
        plan = client.post(f"/api/deals/{rival_deal.id}/action-plans").get_json()
        client.delete("/api/logout")
        login(client)  # back to our user
        return plan

    def test_cannot_read_another_users_plan(self, client, rival_plan):
        assert client.get(f"/api/action-plans/{rival_plan['id']}").status_code == 404

    def test_cannot_delete_another_users_plan(self, client, rival_plan, db):
        assert client.delete(f"/api/action-plans/{rival_plan['id']}").status_code == 404
        assert db.session.get(ActionPlan, rival_plan["id"]) is not None

    def test_cannot_generate_a_plan_on_another_users_deal(
        self, auth_client, rival_deal, fake_llm
    ):
        res = auth_client.post(f"/api/deals/{rival_deal.id}/action-plans")
        assert res.status_code == 404

    def test_cannot_check_off_another_users_action_item(self, client, rival_plan, db):
        item_id = rival_plan["items"][0]["id"]
        res = client.patch(f"/api/action-items/{item_id}", json={"status": "done"})
        assert res.status_code == 404
        assert db.session.get(ActionItem, item_id).status == "open"

    def test_cannot_delete_another_users_action_item(self, client, rival_plan, db):
        item_id = rival_plan["items"][0]["id"]
        assert client.delete(f"/api/action-items/{item_id}").status_code == 404
        assert db.session.get(ActionItem, item_id) is not None

    def test_cannot_add_an_item_to_another_users_plan(self, client, rival_plan):
        res = client.post(
            f"/api/action-plans/{rival_plan['id']}/items", json={"title": "Injected"}
        )
        assert res.status_code == 404

    def test_generation_requires_authentication(self, client, deal):
        assert client.post(f"/api/deals/{deal.id}/action-plans").status_code == 401


class TestRetrievalIsScopedToTheDeal:
    def test_another_deals_documents_never_reach_the_prompt(
        self, auth_client, deal, user, fake_llm, monkeypatch
    ):
        """Retrieval must be scoped to one deal, not just one user. A rep's Acme
        plan must not be grounded in their Globex notes."""
        other = Deal(user_id=user.id, name="Globex Expansion", company="Globex")
        _db.session.add(other)
        _db.session.commit()

        upload(auth_client, deal.id, content=MEETING_NOTE, filename="acme.txt")
        upload(auth_client, other.id, content=MEETING_NOTE, filename="globex.txt")

        captured = {}

        def spy(deal_arg, sources):
            captured["sources"] = sources
            return fake_llm, "fake-model"

        monkeypatch.setattr("app.services.rag._generate", spy)

        auth_client.post(f"/api/deals/{deal.id}/action-plans")

        assert captured["sources"], "expected sources to reach the model"
        filenames = {s["filename"] for s in captured["sources"]}
        assert filenames == {"acme.txt"}
        assert "globex.txt" not in filenames
