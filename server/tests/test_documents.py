import io

import pytest
from pypdf import PdfWriter

from app.extensions import db as _db
from app.models import Deal, Document, DocumentChunk
from app.services import vectorstore
from app.services.extraction import ExtractionError, extract_text

from .conftest import login

MEETING_NOTE = (
    "Discovery call with Acme Corp on July 10.\n\n"
    "Rita Chen (VP Engineering) confirmed the security questionnaire must be "
    "returned by August 1 or procurement will not advance the deal.\n\n"
    "Acme's economic buyer is CFO Dan Ortiz, who has not yet been introduced. "
    "Rita agreed to make the introduction once pricing is confirmed.\n\n"
    "We committed to sending SOC2 evidence and a revised pricing sheet by Friday."
)


def upload(client, deal_id, content=MEETING_NOTE, filename="notes.txt", doc_type="meeting_note"):
    return client.post(
        f"/api/deals/{deal_id}/documents",
        data={
            "file": (io.BytesIO(content.encode()), filename),
            "doc_type": doc_type,
        },
        content_type="multipart/form-data",
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


class TestTextExtraction:
    def test_reads_plaintext(self):
        assert "Acme" in extract_text("n.txt", MEETING_NOTE.encode())

    def test_rejects_unsupported_type(self):
        with pytest.raises(ExtractionError, match="Unsupported file type"):
            extract_text("deck.pptx", b"x" * 200)

    def test_rejects_a_pdf_with_no_text_layer(self):
        """A scanned PDF is a valid PDF whose pages are images — it parses fine
        and yields no text. Indexing it would build a knowledge base out of
        nothing, so refuse it and say why.

        The file has to be a *real* PDF for this to test the right branch;
        garbage bytes would fail at open() instead, which is a different error.
        """
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        buffer = io.BytesIO()
        writer.write(buffer)

        with pytest.raises(ExtractionError, match="scanned PDF"):
            extract_text("scan.pdf", buffer.getvalue())

    def test_rejects_bytes_that_are_not_a_pdf(self):
        with pytest.raises(ExtractionError, match="could not be opened"):
            extract_text("broken.pdf", b"this is not a pdf at all")


class TestUpload:
    def test_ingests_and_chunks_a_document(self, auth_client, deal, db):
        res = upload(auth_client, deal.id)
        assert res.status_code == 201
        body = res.get_json()
        assert body["filename"] == "notes.txt"
        assert body["chunk_count"] >= 1

        chunks = db.session.query(DocumentChunk).all()
        assert len(chunks) == body["chunk_count"]
        # Every chunk must carry a vector, or it is invisible to retrieval.
        assert all(len(c.embedding) == 768 for c in chunks)

    def test_indexes_chunks_for_retrieval(self, auth_client, deal, app):
        upload(auth_client, deal.id)
        assert vectorstore.get_collection().count() >= 1

    def test_rejects_unsupported_file_type(self, auth_client, deal):
        res = upload(auth_client, deal.id, filename="deck.pptx")
        assert res.status_code == 422
        assert "Unsupported file type" in res.get_json()["error"]

    def test_rejects_empty_file(self, auth_client, deal):
        res = auth_client.post(
            f"/api/deals/{deal.id}/documents",
            data={"file": (io.BytesIO(b""), "empty.txt")},
            content_type="multipart/form-data",
        )
        assert res.status_code == 400

    def test_rejects_unknown_doc_type(self, auth_client, deal):
        res = upload(auth_client, deal.id, doc_type="invented")
        assert res.status_code == 422

    def test_failed_extraction_leaves_no_partial_document(self, auth_client, deal, db):
        upload(auth_client, deal.id, content="tiny", filename="x.txt")
        assert db.session.query(Document).count() == 0
        assert db.session.query(DocumentChunk).count() == 0


class TestListAndDelete:
    def test_lists_documents_for_a_deal(self, auth_client, deal):
        upload(auth_client, deal.id)
        res = auth_client.get(f"/api/deals/{deal.id}/documents")
        assert res.status_code == 200
        assert len(res.get_json()) == 1

    def test_delete_removes_document_and_its_chunks(self, auth_client, deal, db):
        doc_id = upload(auth_client, deal.id).get_json()["id"]
        assert auth_client.delete(f"/api/documents/{doc_id}").status_code == 204
        assert db.session.get(Document, doc_id) is None
        assert db.session.query(DocumentChunk).count() == 0

    def test_deleting_a_deal_cascades_to_documents_and_chunks(
        self, auth_client, deal, db
    ):
        upload(auth_client, deal.id)
        auth_client.delete(f"/api/deals/{deal.id}")
        assert db.session.query(Document).count() == 0
        assert db.session.query(DocumentChunk).count() == 0


class TestDocumentAuthorization:
    def test_cannot_upload_to_another_users_deal(self, auth_client, rival_deal, db):
        res = upload(auth_client, rival_deal.id)
        assert res.status_code == 404
        assert db.session.query(Document).count() == 0

    def test_cannot_list_another_users_documents(self, auth_client, rival_deal):
        res = auth_client.get(f"/api/deals/{rival_deal.id}/documents")
        assert res.status_code == 404

    def test_cannot_delete_another_users_document(self, client, user, rival_deal, db):
        # The rival uploads a document...
        login(client, email="rival@example.com")
        doc_id = upload(client, rival_deal.id).get_json()["id"]
        client.delete("/api/logout")

        # ...and our user tries to delete it by ID.
        login(client)
        assert client.delete(f"/api/documents/{doc_id}").status_code == 404
        assert db.session.get(Document, doc_id) is not None

    def test_upload_requires_authentication(self, client, deal):
        assert upload(client, deal.id).status_code == 401


class TestVectorIndexIsRebuildable:
    def test_index_can_be_rebuilt_from_sql_after_being_wiped(
        self, auth_client, deal, app
    ):
        """The whole free-tier hosting plan rests on this: Chroma's directory is
        ephemeral, so the index must be reconstructible from Postgres alone."""
        upload(auth_client, deal.id)
        indexed = vectorstore.get_collection().count()
        assert indexed >= 1

        # Simulate a Render redeploy: the vector directory is gone.
        vectorstore.get_collection().delete(where={"user_id": deal.user_id})
        assert vectorstore.get_collection().count() == 0

        rebuilt = vectorstore.rebuild_from_sql(app)
        assert rebuilt == indexed
        assert vectorstore.get_collection().count() == indexed
