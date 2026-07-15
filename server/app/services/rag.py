"""The RAG pipeline: retrieve the rep's own deal documents, ground a plan in
them, and refuse to answer when the documents do not support one.

The refusal is the feature. A sales rep cannot act on a next step they cannot
trace to something the customer actually said, so a fluent guess is worse than
an honest "I don't have enough to go on" — it looks exactly like a real answer.
"""

import logging
from typing import List, Literal

from flask import current_app
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from ..extensions import db
from ..models import ActionItem, ActionPlan, Citation, DocumentChunk
from . import vectorstore
from .embeddings import embed_query

log = logging.getLogger(__name__)

# Tried in order. Verified against the live API rather than taken from
# ListModels, which lies: it advertises gemini-2.5-flash, but calling it returns
# "no longer available to new users." The 2.0-flash line has no free-tier quota
# on a new key at all. Falling through to the lite model keeps a demo alive when
# the preview model is rate-limited or overloaded, which is the failure most
# likely to happen in front of a reviewer.
CHAT_MODELS = ["gemini-3-flash-preview", "gemini-3.1-flash-lite"]

# Errors that mean "try the next model" rather than "give up". Includes timeout
# and deadline signals, so a model that is merely slow yields to the next one
# instead of failing the whole request.
FALLBACK_SIGNALS = (
    "429",
    "resource_exhausted",
    "503",
    "unavailable",
    "overloaded",
    "404",
    "timeout",
    "timed out",
    "deadline",
)

# How much of a chunk we quote back to the user in a citation card.
QUOTE_MAX_CHARS = 400


class InsufficientContext(Exception):
    """Retrieval found nothing that could support a plan. Carries a
    user-facing explanation of what to upload."""

    def __init__(self, message, retrieved=0):
        super().__init__(message)
        self.message = message
        self.retrieved = retrieved


class GenerationError(RuntimeError):
    """The model call failed."""


# --- What we force the model to return ------------------------------------


class NextStep(BaseModel):
    step: str = Field(description="One concrete next action to advance the deal.")
    source_ids: List[int] = Field(
        default_factory=list,
        description="Numbers of the sources that support this step, e.g. [1, 3].",
    )


class GeneratedActionItem(BaseModel):
    title: str = Field(description="Short imperative title, e.g. 'Send SOC2 report'.")
    detail: str = Field(description="What exactly to do and why, per the sources.")
    priority: Literal["high", "medium", "low"] = "medium"
    source_ids: List[int] = Field(default_factory=list)


class GeneratedPlan(BaseModel):
    summary: str = Field(description="2-4 sentences on where this deal stands.")
    next_steps: List[NextStep]
    action_items: List[GeneratedActionItem]


SYSTEM_PROMPT = """You are a sales-enablement assistant helping a B2B sales rep \
decide what to do next on a specific deal.

You will be given numbered sources taken from the rep's own documents for this \
deal: meeting notes, company information, and RFPs.

Rules:
- Ground every claim in the numbered sources. Cite them by number in source_ids.
- Do NOT invent commitments, dates, names, or requirements. If the sources do \
not state something, do not assert it.
- Prefer concrete, dated, assignable actions over generic sales advice. \
"Answer the security questionnaire by August 1" is useful; "build rapport with \
the client" is not.
- If the sources genuinely do not support any next step, return an empty \
action_items list rather than padding it with generic filler.
"""


def _build_prompt(deal, sources):
    blocks = []
    for source in sources:
        blocks.append(
            f"[{source['source_number']}] (from {source['filename']}, "
            f"{source['doc_type']})\n{source['content']}"
        )
    context = "\n\n".join(blocks)

    return f"""Deal: {deal.name}
Company: {deal.company}
Stage: {deal.stage}

Sources from this deal's documents:

{context}

Produce a situation summary, the sequenced next steps to advance this deal, and \
a checklist of concrete action items. Cite the source numbers that support each \
one."""


def _retrieve(deal):
    """Find the chunks from this deal that best speak to 'what do we do next'."""
    query = (
        f"Next steps, commitments, deadlines, blockers, and open questions for "
        f"the {deal.company} deal ({deal.name}), currently at the {deal.stage} stage."
    )
    query_vector = embed_query(query)

    hits = vectorstore.search(
        query_embedding=query_vector,
        user_id=deal.user_id,
        deal_id=deal.id,
        top_k=current_app.config["RETRIEVAL_TOP_K"],
    )
    if not hits:
        raise InsufficientContext(
            "This deal has no indexed documents yet. Upload a meeting note, "
            "company profile, or RFP and try again."
        )

    # The weak-context gate: reject sources that are not similar enough to the
    # planning query, and refuse to generate rather than inventing a plan.
    #
    # The threshold is empirical, not arbitrary. gemini-embedding-001 vectors are
    # not zero-centered, so cosine similarity sits in a high, compressed band.
    # Measured against this query:
    #
    #     on-topic deal content    0.621 - 0.684
    #     generic sales advice     0.589
    #     "npm install ..."        0.573
    #     random gibberish         0.539
    #     a banana bread recipe    0.510
    #
    # Hence the 0.60 floor. Note the margin between the worst real source and the
    # best irrelevant one is only ~0.03: content that is off-topic but *close* to
    # the band (generic sales advice, say) can still slip through. Widening that
    # margin would mean a second, semantic check — see README's known limitations.
    floor = current_app.config["RETRIEVAL_MIN_SCORE"]
    relevant = [h for h in hits if h["similarity"] >= floor]
    if not relevant:
        raise InsufficientContext(
            "The documents on this deal do not contain enough relevant detail to "
            "build a reliable plan. Upload a meeting note or RFP that covers the "
            "current state of the deal.",
            retrieved=len(hits),
        )

    # Defense in depth. Chroma already filtered on user_id and deal_id, but a bug
    # in a metadata filter must not be sufficient to put another rep's documents
    # into a prompt. SQL has the final say on who owns what.
    chunk_ids = [h["chunk_id"] for h in relevant]
    owned = {
        chunk.id: chunk
        for chunk in db.session.query(DocumentChunk)
        .filter(DocumentChunk.id.in_(chunk_ids))
        .all()
        if chunk.document.user_id == deal.user_id
        and chunk.document.deal_id == deal.id
    }
    if len(owned) != len(relevant):
        log.error(
            "Retrieval returned %d chunks but only %d passed SQL ownership checks "
            "for deal %d — dropping the rest.",
            len(relevant),
            len(owned),
            deal.id,
        )

    sources = []
    for hit in relevant:
        chunk = owned.get(hit["chunk_id"])
        if chunk is None:
            continue
        sources.append(
            {
                "source_number": len(sources) + 1,
                "chunk_id": chunk.id,
                "content": chunk.content,
                "filename": chunk.document.filename,
                "doc_type": chunk.document.doc_type,
                "similarity": hit["similarity"],
            }
        )

    if not sources:
        raise InsufficientContext(
            "No usable source content was found for this deal."
        )
    return sources


def _generate(deal, sources):
    """Call Gemini with structured output, falling back down the model list if a
    model is rate-limited or unavailable. Returns (plan, model_name)."""
    api_key = current_app.config.get("GOOGLE_API_KEY")
    if not api_key:
        raise GenerationError("GOOGLE_API_KEY is not configured.")

    messages = [
        ("system", SYSTEM_PROMPT),
        ("human", _build_prompt(deal, sources)),
    ]

    last_error = None
    for model_name in CHAT_MODELS:
        model = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0.2,  # a planning task, not a creative one
            # Bound every call. This endpoint is a synchronous request behind
            # Render's proxy, which returns 502 (killing the worker mid-request)
            # if the app takes too long — observed at ~55s. Left unbounded,
            # LangChain retries a transient error up to 6 times with backoff, and
            # the two-model fallback below multiplies that, so one network hiccup
            # on the free instance stacks into a 55s+ hang. No internal retries
            # (our model fallback is the resilience) and a 20s cap per model keep
            # the worst case — both models timing out — near 40s, safely under
            # the proxy limit. When healthy the first model answers in seconds.
            timeout=20,
            max_retries=0,
        )
        # Structured output means typed JSON back — never parsing prose.
        structured = model.with_structured_output(GeneratedPlan)
        try:
            return structured.invoke(messages), model_name
        except Exception as err:  # noqa: BLE001
            last_error = err
            if any(signal in str(err).lower() for signal in FALLBACK_SIGNALS):
                log.warning("Model %s unavailable, trying next: %s", model_name, err)
                continue
            raise GenerationError(
                f"The AI service failed to generate a plan: {err}"
            ) from err

    raise GenerationError(
        f"Every model was unavailable. Last error: {last_error}"
    ) from last_error


def _valid_sources(source_ids, sources):
    """Drop citations the model made up.

    Models sometimes cite [9] when only 8 sources exist. An invalid citation is
    worse than none: the whole promise of this feature is that a number leads
    back to real text the user can read.
    """
    valid = {s["source_number"] for s in sources}
    return sorted({sid for sid in (source_ids or []) if sid in valid})


def generate_action_plan(deal):
    """Retrieve, gate, generate, and persist. Raises InsufficientContext when
    the deal's documents cannot support a plan."""
    sources = _retrieve(deal)
    generated, model_used = _generate(deal, sources)

    plan = ActionPlan(
        deal_id=deal.id,
        user_id=deal.user_id,
        summary=generated.summary,
        next_steps=[
            {
                "step": step.step,
                "source_ids": _valid_sources(step.source_ids, sources),
            }
            for step in generated.next_steps
        ],
        # Record which model actually answered — with a fallback chain, that is
        # not knowable from config alone.
        model_used=model_used,
    )
    db.session.add(plan)
    db.session.flush()

    for item in generated.action_items:
        db.session.add(
            ActionItem(
                action_plan_id=plan.id,
                title=item.title,
                detail=item.detail,
                priority=item.priority,
                source_ids=_valid_sources(item.source_ids, sources),
                is_user_created=False,
            )
        )

    # Every source that grounded the answer is persisted, so the citation the
    # user clicks resolves to the exact passage the model was shown — not to a
    # re-retrieval that might return something different later.
    for source in sources:
        db.session.add(
            Citation(
                action_plan_id=plan.id,
                chunk_id=source["chunk_id"],
                source_number=source["source_number"],
                quote=source["content"][:QUOTE_MAX_CHARS],
                relevance_score=source["similarity"],
            )
        )

    db.session.commit()
    log.info(
        "Generated plan %d for deal %d from %d sources", plan.id, deal.id, len(sources)
    )
    return plan
