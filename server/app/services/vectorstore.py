"""Chroma index over document chunks.

Chroma is a *derived* index here, not a database. Postgres holds every chunk and
its embedding vector; this index is rebuilt from those rows at startup. Render's
free tier has an ephemeral filesystem, so a Chroma directory on local disk is
wiped on every restart and redeploy — treating it as authoritative would mean
losing the knowledge base on each deploy and paying to re-embed every document.
Losing this index costs boot time and nothing else.

Every vector carries `user_id` and `deal_id` metadata, and every search filters
on both. Callers must still re-check ownership in SQL against what comes back:
one bug in a metadata filter should not be enough to leak another rep's
documents into an LLM prompt.
"""

import logging

import chromadb
from flask import current_app

log = logging.getLogger(__name__)

COLLECTION_NAME = "document_chunks"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=current_app.config["CHROMA_DIR"])
    return _client


def get_collection():
    return _get_client().get_or_create_collection(
        name=COLLECTION_NAME,
        # Chroma defaults to L2 distance. We store unit-normalized vectors and
        # want cosine, so ask for it explicitly rather than relying on the fact
        # that the two rank identically for normalized vectors.
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(chunks):
    """Index chunks that are already persisted in SQL.

    `chunks` are DocumentChunk rows; their embeddings were computed at ingest.
    """
    if not chunks:
        return

    collection = get_collection()
    collection.upsert(
        ids=[str(c.id) for c in chunks],
        embeddings=[c.embedding for c in chunks],
        documents=[c.content for c in chunks],
        metadatas=[
            {
                "chunk_id": c.id,
                "document_id": c.document_id,
                "deal_id": c.document.deal_id,
                "user_id": c.document.user_id,
            }
            for c in chunks
        ],
    )


def remove_document(document_id):
    get_collection().delete(where={"document_id": document_id})


def search(query_embedding, user_id, deal_id, top_k):
    """Return the most similar chunks belonging to this user's deal.

    Chroma reports cosine *distance*; we convert to similarity so a bigger
    number means a better match, which is what the relevance floor expects.
    """
    collection = get_collection()
    if collection.count() == 0:
        return []

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        # Both conditions, always. A deal filter alone would still be scoped by
        # ownership upstream, but defense in depth is the whole point here.
        where={"$and": [{"user_id": user_id}, {"deal_id": deal_id}]},
        include=["documents", "metadatas", "distances"],
    )

    ids = result.get("ids", [[]])[0]
    if not ids:
        return []

    hits = []
    for chunk_id, content, metadata, distance in zip(
        ids,
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):
        hits.append(
            {
                "chunk_id": int(chunk_id),
                "content": content,
                "metadata": metadata,
                "similarity": 1.0 - float(distance),
            }
        )
    return hits


def rebuild_from_sql(app):
    """Repopulate the index from Postgres. Safe to call on every boot."""
    from ..models import DocumentChunk

    with app.app_context():
        chunks = DocumentChunk.query.all()
        if not chunks:
            log.info("Vector index: no chunks in database, nothing to rebuild.")
            return 0
        add_chunks(chunks)
        log.info("Vector index: rebuilt %d chunks from database.", len(chunks))
        return len(chunks)
