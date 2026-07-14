from datetime import date

from flask import Blueprint, request
from flask_login import current_user, login_required

from ..authz import owned_or_404
from ..extensions import db
from ..models import Deal

deals_bp = Blueprint("deals", __name__, url_prefix="/api/deals")

STAGES = ("discovery", "qualification", "proposal", "negotiation", "closed")


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _validate(data, partial=False):
    errors = {}

    if not partial or "name" in data:
        if not (data.get("name") or "").strip():
            errors["name"] = "Deal name is required."
    if not partial or "company" in data:
        if not (data.get("company") or "").strip():
            errors["company"] = "Company is required."
    if "stage" in data and data["stage"] not in STAGES:
        errors["stage"] = f"Stage must be one of: {', '.join(STAGES)}."
    if "value" in data and data["value"] is not None:
        try:
            int(data["value"])
        except (ValueError, TypeError):
            errors["value"] = "Value must be a whole number."
    if data.get("close_date") and _parse_date(data["close_date"]) is None:
        errors["close_date"] = "Close date must be in YYYY-MM-DD format."

    return errors


@deals_bp.get("")
@login_required
def list_deals():
    deals = (
        db.session.query(Deal)
        .filter_by(user_id=current_user.id)
        .order_by(Deal.created_at.desc())
        .all()
    )
    return [d.to_dict(include_counts=True) for d in deals], 200


@deals_bp.post("")
@login_required
def create_deal():
    data = request.get_json(silent=True) or {}
    errors = _validate(data)
    if errors:
        return {"errors": errors}, 422

    deal = Deal(
        user_id=current_user.id,
        name=data["name"].strip(),
        company=data["company"].strip(),
        stage=data.get("stage", "discovery"),
        value=int(data["value"]) if data.get("value") is not None else None,
        close_date=_parse_date(data.get("close_date")),
    )
    db.session.add(deal)
    db.session.commit()
    return deal.to_dict(include_counts=True), 201


@deals_bp.get("/<int:deal_id>")
@login_required
def get_deal(deal_id):
    deal = owned_or_404(Deal, deal_id)
    return deal.to_dict(include_counts=True), 200


@deals_bp.patch("/<int:deal_id>")
@login_required
def update_deal(deal_id):
    deal = owned_or_404(Deal, deal_id)
    data = request.get_json(silent=True) or {}
    errors = _validate(data, partial=True)
    if errors:
        return {"errors": errors}, 422

    if "name" in data:
        deal.name = data["name"].strip()
    if "company" in data:
        deal.company = data["company"].strip()
    if "stage" in data:
        deal.stage = data["stage"]
    if "value" in data:
        deal.value = int(data["value"]) if data["value"] is not None else None
    if "close_date" in data:
        deal.close_date = _parse_date(data["close_date"])

    db.session.commit()
    return deal.to_dict(include_counts=True), 200


@deals_bp.delete("/<int:deal_id>")
@login_required
def delete_deal(deal_id):
    deal = owned_or_404(Deal, deal_id)
    # Cascades take the deal's documents, chunks, plans, items, and citations
    # with it — no orphaned rows, and no orphaned vectors once the index is
    # rebuilt from SQL.
    db.session.delete(deal)
    db.session.commit()
    return "", 204
