import logging

from flask import Blueprint, abort, send_file
from flask_login import current_user, login_required

from ..authz import owned_or_404
from ..extensions import db
from ..models import ActionPlan, Deck
from ..services.decks import (
    DeckError,
    PPTX_MIME,
    deck_filename,
    generate_deck_bytes,
)
import io

log = logging.getLogger(__name__)

decks_bp = Blueprint("decks", __name__, url_prefix="/api")


@decks_bp.post("/action-plans/<int:plan_id>/deck")
@login_required
def generate_deck(plan_id):
    plan = owned_or_404(ActionPlan, plan_id)

    try:
        data, slide_count, source = generate_deck_bytes(plan)
    except DeckError as err:
        log.exception("Deck generation failed for plan %d", plan_id)
        return {"error": str(err)}, 502
    except Exception:  # noqa: BLE001
        log.exception("Unexpected deck failure for plan %d", plan_id)
        return {"error": "The deck could not be generated."}, 500

    deck = Deck(
        action_plan_id=plan.id,
        user_id=current_user.id,
        filename=deck_filename(plan),
        data=data,
        slide_count=slide_count,
        source=source,
    )
    db.session.add(deck)
    db.session.commit()
    return deck.to_dict(), 201


@decks_bp.get("/action-plans/<int:plan_id>/decks")
@login_required
def list_decks(plan_id):
    plan = owned_or_404(ActionPlan, plan_id)
    return [d.to_dict() for d in plan.decks], 200


@decks_bp.get("/decks/<int:deck_id>/download")
@login_required
def download_deck(deck_id):
    # Ownership in the query: the .pptx never leaves this route without it.
    deck = owned_or_404(Deck, deck_id)
    return send_file(
        io.BytesIO(deck.data),
        mimetype=PPTX_MIME,
        as_attachment=True,
        download_name=deck.filename,
    )


@decks_bp.delete("/decks/<int:deck_id>")
@login_required
def delete_deck(deck_id):
    deck = owned_or_404(Deck, deck_id)
    db.session.delete(deck)
    db.session.commit()
    return "", 204
