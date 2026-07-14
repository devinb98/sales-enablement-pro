from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import JSON

from .extensions import bcrypt, db, login_manager


def utcnow():
    return datetime.now(timezone.utc)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    deals = db.relationship(
        "Deal", back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def to_dict(self):
        # password_hash is deliberately absent — this dict is API-facing.
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Deal(db.Model):
    """The protected, user-owned resource. Everything else hangs off a Deal, so
    scoping a query to `user_id` is what keeps one rep's pipeline invisible to
    another."""

    __tablename__ = "deals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    name = db.Column(db.String(200), nullable=False)
    company = db.Column(db.String(200), nullable=False)
    stage = db.Column(db.String(50), default="discovery")
    value = db.Column(db.Integer)
    close_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    user = db.relationship("User", back_populates="deals")
    documents = db.relationship(
        "Document", back_populates="deal", cascade="all, delete-orphan"
    )
    action_plans = db.relationship(
        "ActionPlan",
        back_populates="deal",
        cascade="all, delete-orphan",
        order_by="ActionPlan.generated_at.desc()",
    )

    def to_dict(self, include_counts=False):
        data = {
            "id": self.id,
            "name": self.name,
            "company": self.company,
            "stage": self.stage,
            "value": self.value,
            "close_date": self.close_date.isoformat() if self.close_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_counts:
            data["document_count"] = len(self.documents)
            data["action_plan_count"] = len(self.action_plans)
        return data


class Document(db.Model):
    """A source artifact uploaded by the rep. `raw_text` is the extracted text;
    the chunks derived from it are what retrieval actually searches."""

    __tablename__ = "documents"

    DOC_TYPES = ("meeting_note", "company_info", "rfp")

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(
        db.Integer, db.ForeignKey("deals.id"), nullable=False, index=True
    )
    # Denormalized from Deal so ownership can be enforced in the retrieval filter
    # and in chunk queries without a join.
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    filename = db.Column(db.String(255), nullable=False)
    doc_type = db.Column(db.String(30), nullable=False)
    raw_text = db.Column(db.Text, nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    deal = db.relationship("Deal", back_populates="documents")
    chunks = db.relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "deal_id": self.deal_id,
            "filename": self.filename,
            "doc_type": self.doc_type,
            "chunk_count": len(self.chunks),
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class DocumentChunk(db.Model):
    """One retrievable passage, stored alongside its embedding vector.

    Postgres is the source of truth for embeddings, not Chroma. Render's free
    tier has an ephemeral filesystem, so a Chroma directory on local disk is
    wiped on every restart and redeploy. Keeping the vectors here means the
    index is rebuildable from the database at startup and losing it costs only
    boot time — never data, and never a re-embedding bill.
    """

    __tablename__ = "document_chunks"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(
        db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True
    )
    chunk_index = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    embedding = db.Column(JSON, nullable=False)

    document = db.relationship("Document", back_populates="chunks")

    def to_dict(self):
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
        }


class ActionPlan(db.Model):
    """The persistent AI artifact: a stored, revisitable plan rather than a chat
    message that scrolls away."""

    __tablename__ = "action_plans"

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(
        db.Integer, db.ForeignKey("deals.id"), nullable=False, index=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    summary = db.Column(db.Text, nullable=False)
    next_steps = db.Column(JSON, nullable=False, default=list)
    model_used = db.Column(db.String(80))
    generated_at = db.Column(db.DateTime(timezone=True), default=utcnow)

    deal = db.relationship("Deal", back_populates="action_plans")
    items = db.relationship(
        "ActionItem", back_populates="action_plan", cascade="all, delete-orphan"
    )
    citations = db.relationship(
        "Citation", back_populates="action_plan", cascade="all, delete-orphan"
    )

    def to_dict(self, include_children=False):
        data = {
            "id": self.id,
            "deal_id": self.deal_id,
            "summary": self.summary,
            "next_steps": self.next_steps,
            "model_used": self.model_used,
            "generated_at": (
                self.generated_at.isoformat() if self.generated_at else None
            ),
        }
        if include_children:
            data["items"] = [item.to_dict() for item in self.items]
            data["citations"] = [c.to_dict() for c in self.citations]
        return data


class ActionItem(db.Model):
    """AI output the user takes ownership of — editable, checkable, and
    extendable with their own items."""

    __tablename__ = "action_items"

    STATUSES = ("open", "done")
    PRIORITIES = ("high", "medium", "low")

    id = db.Column(db.Integer, primary_key=True)
    action_plan_id = db.Column(
        db.Integer, db.ForeignKey("action_plans.id"), nullable=False, index=True
    )
    title = db.Column(db.String(300), nullable=False)
    detail = db.Column(db.Text)
    priority = db.Column(db.String(10), default="medium")
    due_date = db.Column(db.Date)
    status = db.Column(db.String(10), default="open")
    is_user_created = db.Column(db.Boolean, default=False)
    # Which numbered sources the model cited for this item, e.g. [1, 3].
    source_ids = db.Column(JSON, default=list)

    action_plan = db.relationship("ActionPlan", back_populates="items")

    def to_dict(self):
        return {
            "id": self.id,
            "action_plan_id": self.action_plan_id,
            "title": self.title,
            "detail": self.detail,
            "priority": self.priority,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status,
            "is_user_created": self.is_user_created,
            "source_ids": self.source_ids or [],
        }


class Citation(db.Model):
    """The join that makes the AI output source-backed: it ties a generated plan
    back to the exact passage in the exact document that justifies it."""

    __tablename__ = "citations"

    id = db.Column(db.Integer, primary_key=True)
    action_plan_id = db.Column(
        db.Integer, db.ForeignKey("action_plans.id"), nullable=False, index=True
    )
    chunk_id = db.Column(
        db.Integer, db.ForeignKey("document_chunks.id"), nullable=False
    )
    # The position this chunk occupied in the prompt ([1], [2], ...), which is
    # how the model refers to it in `source_ids`.
    source_number = db.Column(db.Integer, nullable=False)
    quote = db.Column(db.Text, nullable=False)
    relevance_score = db.Column(db.Float)

    action_plan = db.relationship("ActionPlan", back_populates="citations")
    chunk = db.relationship("DocumentChunk")

    def to_dict(self):
        chunk = self.chunk
        document = chunk.document if chunk else None
        return {
            "id": self.id,
            "source_number": self.source_number,
            "quote": self.quote,
            "relevance_score": self.relevance_score,
            "chunk_id": self.chunk_id,
            "document_id": document.id if document else None,
            "filename": document.filename if document else None,
            "doc_type": document.doc_type if document else None,
        }
