import logging

from flask import Blueprint, request
from flask_login import current_user, login_required

from ..authz import owned_or_404
from ..extensions import db
from ..models import Deal, Document
from ..services import vectorstore
from ..services.embeddings import EmbeddingError
from ..services.extraction import ExtractionError
from ..services.ingestion import ingest_document

log = logging.getLogger(__name__)

documents_bp = Blueprint("documents", __name__, url_prefix="/api")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@documents_bp.get("/deals/<int:deal_id>/documents")
@login_required
def list_documents(deal_id):
    deal = owned_or_404(Deal, deal_id)
    return [d.to_dict() for d in deal.documents], 200


@documents_bp.post("/deals/<int:deal_id>/documents")
@login_required
def upload_document(deal_id):
    deal = owned_or_404(Deal, deal_id)

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return {"error": "No file was uploaded."}, 400

    doc_type = request.form.get("doc_type", "meeting_note")
    if doc_type not in Document.DOC_TYPES:
        return {
            "error": f"doc_type must be one of: {', '.join(Document.DOC_TYPES)}."
        }, 422

    file_bytes = upload.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return {"error": "File is larger than the 10 MB limit."}, 413
    if not file_bytes:
        return {"error": "That file is empty."}, 400

    try:
        document = ingest_document(deal, upload.filename, file_bytes, doc_type)
    except ExtractionError as err:
        # The message is written for the user — it tells them what to do next.
        return {"error": str(err)}, 422
    except EmbeddingError as err:
        log.exception("Embedding failed for upload to deal %d", deal_id)
        return {
            "error": "The AI service is unavailable right now, so this document "
            "could not be indexed. Please try again in a moment."
        }, 503
    except Exception:  # noqa: BLE001
        db.session.rollback()
        log.exception("Unexpected failure ingesting upload to deal %d", deal_id)
        return {"error": "This file could not be processed."}, 500

    return document.to_dict(), 201


@documents_bp.delete("/documents/<int:document_id>")
@login_required
def delete_document(document_id):
    # Document carries its own user_id, so ownership is a WHERE clause here too
    # rather than a walk up through the deal.
    document = owned_or_404(Document, document_id)

    db.session.delete(document)  # cascades to its chunks
    db.session.commit()

    try:
        vectorstore.remove_document(document_id)
    except Exception:  # noqa: BLE001
        # The rows are gone from SQL, which is authoritative. A stale vector
        # would be dropped on the next rebuild anyway, and retrieval re-checks
        # ownership against SQL before anything reaches a prompt.
        log.exception("Failed to remove document %d from vector index", document_id)

    return "", 204
