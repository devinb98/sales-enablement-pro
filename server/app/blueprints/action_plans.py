import logging
from datetime import date

from flask import Blueprint, request
from flask_login import current_user, login_required

from ..authz import owned_or_404
from ..extensions import db
from ..models import ActionItem, ActionPlan, Deal
from ..services.embeddings import EmbeddingError
from ..services.rag import GenerationError, InsufficientContext, generate_action_plan

log = logging.getLogger(__name__)

plans_bp = Blueprint("action_plans", __name__, url_prefix="/api")


def _owned_item_or_404(item_id):
    """ActionItem has no user_id of its own — it belongs to a plan, which belongs
    to a user. Enforce that in the join rather than loading the item and hoping
    someone remembers to check."""
    from flask import abort

    item = (
        db.session.query(ActionItem)
        .join(ActionPlan)
        .filter(ActionItem.id == item_id, ActionPlan.user_id == current_user.id)
        .one_or_none()
    )
    if item is None:
        abort(404, description="ActionItem not found")
    return item


@plans_bp.post("/deals/<int:deal_id>/action-plans")
@login_required
def create_action_plan(deal_id):
    deal = owned_or_404(Deal, deal_id)

    try:
        plan = generate_action_plan(deal)
    except InsufficientContext as err:
        # Not an error the user did wrong — it is the app declining to invent a
        # plan it cannot support. Give it a distinct code so the UI can show a
        # "needs more context" state rather than a generic failure.
        return {
            "error": "insufficient_context",
            "message": err.message,
            "retrieved": err.retrieved,
        }, 422
    except EmbeddingError:
        log.exception("Embedding failed generating a plan for deal %d", deal_id)
        return {
            "error": "ai_unavailable",
            "message": "The AI service is unavailable right now. Try again shortly.",
        }, 503
    except GenerationError:
        log.exception("Generation failed for deal %d", deal_id)
        return {
            "error": "ai_unavailable",
            "message": "The AI service could not generate a plan. Try again shortly.",
        }, 503

    return plan.to_dict(include_children=True), 201


@plans_bp.get("/deals/<int:deal_id>/action-plans")
@login_required
def list_action_plans(deal_id):
    deal = owned_or_404(Deal, deal_id)
    return [p.to_dict() for p in deal.action_plans], 200


@plans_bp.get("/action-plans/<int:plan_id>")
@login_required
def get_action_plan(plan_id):
    plan = owned_or_404(ActionPlan, plan_id)
    return plan.to_dict(include_children=True), 200


@plans_bp.delete("/action-plans/<int:plan_id>")
@login_required
def delete_action_plan(plan_id):
    plan = owned_or_404(ActionPlan, plan_id)
    db.session.delete(plan)
    db.session.commit()
    return "", 204


# --- Action items: the AI's output, once the user takes ownership of it -----


@plans_bp.post("/action-plans/<int:plan_id>/items")
@login_required
def create_action_item(plan_id):
    plan = owned_or_404(ActionPlan, plan_id)
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    if not title:
        return {"errors": {"title": "Title is required."}}, 422
    if data.get("priority") and data["priority"] not in ActionItem.PRIORITIES:
        return {"errors": {"priority": "Invalid priority."}}, 422

    item = ActionItem(
        action_plan_id=plan.id,
        title=title,
        detail=(data.get("detail") or "").strip() or None,
        priority=data.get("priority", "medium"),
        due_date=_parse_date(data.get("due_date")),
        is_user_created=True,  # distinguishes the rep's own items from the AI's
        source_ids=[],
    )
    db.session.add(item)
    db.session.commit()
    return item.to_dict(), 201


@plans_bp.patch("/action-items/<int:item_id>")
@login_required
def update_action_item(item_id):
    item = _owned_item_or_404(item_id)
    data = request.get_json(silent=True) or {}

    if "status" in data:
        if data["status"] not in ActionItem.STATUSES:
            return {"errors": {"status": "Invalid status."}}, 422
        item.status = data["status"]
    if "priority" in data:
        if data["priority"] not in ActionItem.PRIORITIES:
            return {"errors": {"priority": "Invalid priority."}}, 422
        item.priority = data["priority"]
    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            return {"errors": {"title": "Title cannot be empty."}}, 422
        item.title = title
    if "detail" in data:
        item.detail = (data["detail"] or "").strip() or None
    if "due_date" in data:
        item.due_date = _parse_date(data["due_date"])

    db.session.commit()
    return item.to_dict(), 200


@plans_bp.delete("/action-items/<int:item_id>")
@login_required
def delete_action_item(item_id):
    item = _owned_item_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return "", 204


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None
