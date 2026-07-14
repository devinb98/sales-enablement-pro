"""Turn an uploaded file into plain text, or refuse it with a reason."""

import io

from pypdf import PdfReader

ALLOWED_EXTENSIONS = {"pdf", "txt", "md"}

# A PDF that yields almost no text is almost always a scan — an image of a page
# with no text layer. Indexing it would silently produce an empty knowledge base
# and, worse, an AI answer built on nothing. Better to reject the upload and say
# why. OCR is a stretch goal.
MIN_EXTRACTED_CHARS = 50


class ExtractionError(ValueError):
    """The file cannot be turned into usable text. The message is user-facing."""


def extension_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def extract_text(filename, data: bytes) -> str:
    ext = extension_of(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ExtractionError(
            f"Unsupported file type '.{ext}'. Upload a PDF, TXT, or MD file."
        )

    if ext == "pdf":
        text = _extract_pdf(data)
    else:
        text = _extract_plaintext(data)

    text = text.strip()
    if len(text) < MIN_EXTRACTED_CHARS:
        raise ExtractionError(
            "Could not read any text from this file. If it is a scanned PDF, "
            "it has no text layer — upload a text-based PDF or paste the "
            "content as a .txt or .md file instead."
        )
    return text


def _extract_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as err:  # noqa: BLE001 - pypdf raises several types
        raise ExtractionError(f"This PDF could not be opened: {err}") from err

    if reader.is_encrypted:
        raise ExtractionError(
            "This PDF is password-protected. Remove the password and re-upload."
        )

    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page shouldn't lose the file
            continue
    return "\n\n".join(pages)


def _extract_plaintext(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("This file's text encoding could not be read.")
