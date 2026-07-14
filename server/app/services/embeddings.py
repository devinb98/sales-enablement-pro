"""Gemini embeddings, wrapped so the rest of the app never sees a transient failure.

Two things here are not incidental:

*Retry.* The Gemini endpoint intermittently answers PERMISSION_DENIED (403) even
for a valid key. Retrying with backoff turns a coin-flip API into a dependable
one. 403 is normally a permanent error you would never retry — we retry it here
precisely because, empirically, it is not permanent on this endpoint.

*Normalization.* gemini-embedding-001 returns 3072-dimensional vectors by
default. We truncate to 768, which cuts JSON storage per chunk from ~60 KB to
~10 KB and shrinks the startup index rebuild proportionally. Truncated vectors
come back un-normalized (L2 norm ~0.59), so cosine similarity would be wrong
unless we normalize them ourselves.
"""

import logging
import math
import time

from flask import current_app
from langchain_google_genai import GoogleGenerativeAIEmbeddings

log = logging.getLogger(__name__)

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 768

MAX_ATTEMPTS = 5
BASE_DELAY_SECONDS = 0.5
RETRYABLE = ("permission_denied", "403", "429", "resource_exhausted", "500", "503")


class EmbeddingError(RuntimeError):
    """Raised when embedding fails after exhausting retries."""


def _normalize(vector):
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        return vector
    return [x / norm for x in vector]


def _client():
    api_key = current_app.config.get("GOOGLE_API_KEY")
    if not api_key:
        raise EmbeddingError("GOOGLE_API_KEY is not configured.")
    return GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=api_key,
        output_dimensionality=EMBEDDING_DIM,
    )


def _with_retry(operation, description):
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as err:  # noqa: BLE001 - provider raises a wide range
            message = str(err).lower()
            if not any(token in message for token in RETRYABLE):
                raise EmbeddingError(f"{description} failed: {err}") from err
            last_error = err
            if attempt < MAX_ATTEMPTS:
                delay = BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                log.warning(
                    "%s failed (attempt %d/%d), retrying in %.1fs: %s",
                    description,
                    attempt,
                    MAX_ATTEMPTS,
                    delay,
                    err,
                )
                time.sleep(delay)
    raise EmbeddingError(
        f"{description} failed after {MAX_ATTEMPTS} attempts: {last_error}"
    )


def embed_texts(texts):
    """Embed a list of passages for storage. Returns one unit vector per text."""
    if not texts:
        return []
    vectors = _with_retry(
        lambda: _client().embed_documents(list(texts)), "Embedding documents"
    )
    return [_normalize(v) for v in vectors]


def embed_query(text):
    """Embed a search query. Must use the same model and normalization as the
    stored vectors, or cosine similarity compares incompatible spaces."""
    vector = _with_retry(lambda: _client().embed_query(text), "Embedding query")
    return _normalize(vector)
