"""Upload -> text -> chunks -> embeddings -> SQL + vector index."""

import logging

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..extensions import db
from ..models import Document, DocumentChunk
from . import vectorstore
from .embeddings import embed_texts
from .extraction import extract_text

log = logging.getLogger(__name__)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def _splitter():
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        # Prefer to break on paragraph, then line, then sentence. A chunk that
        # splits mid-sentence retrieves badly and quotes worse — and these chunks
        # are shown to the user verbatim as citations, so readability is not
        # cosmetic here.
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def ingest_document(deal, filename, file_bytes, doc_type):
    """Extract, chunk, embed, and index an uploaded file.

    Raises ExtractionError if the file yields no usable text, or EmbeddingError
    if the model call fails after retries. Either way nothing is committed, so a
    failed upload leaves no half-ingested document behind.
    """
    text = extract_text(filename, file_bytes)

    pieces = _splitter().split_text(text)
    if not pieces:
        from .extraction import ExtractionError

        raise ExtractionError("This file produced no readable content.")

    # Embed before touching the database. If the model call fails we want to
    # have written nothing at all.
    vectors = embed_texts(pieces)

    document = Document(
        deal_id=deal.id,
        user_id=deal.user_id,
        filename=filename,
        doc_type=doc_type,
        raw_text=text,
    )
    db.session.add(document)
    db.session.flush()  # assigns document.id without committing

    chunks = [
        DocumentChunk(
            document_id=document.id,
            chunk_index=index,
            content=piece,
            embedding=vector,
        )
        for index, (piece, vector) in enumerate(zip(pieces, vectors))
    ]
    db.session.add_all(chunks)
    db.session.commit()

    # SQL is the source of truth, so it commits first. If indexing then fails,
    # the chunks are still safe and the next startup rebuild will pick them up.
    try:
        vectorstore.add_chunks(chunks)
    except Exception:  # noqa: BLE001
        log.exception(
            "Document %d committed to SQL but failed to index; "
            "it will be indexed on next startup rebuild.",
            document.id,
        )

    log.info("Ingested %s (%d chunks) for deal %d", filename, len(chunks), deal.id)
    return document
