import os
import io
import tempfile
from dataclasses import dataclass

import httpx
from pypdf import PdfReader

from src.config import settings
from src.logging import get_logger

logger = get_logger(__name__)


class DocumentFetchError(Exception):
    pass


@dataclass
class FetchedDocument:
    file_path: str          # local temp file path
    media_type: str         # "application/pdf" or "text/plain"
    page_count: int = 0     # only for PDFs
    text_content: str = ""  # fallback plain text


def _validate_pdf(content: bytes) -> int:
    """Validate PDF is parseable. Returns page count or raises."""
    if not content[:5] == b"%PDF-":
        raise DocumentFetchError("File is not a valid PDF (missing PDF header)")
    try:
        reader = PdfReader(io.BytesIO(content))
        page_count = len(reader.pages)
        if page_count == 0:
            raise DocumentFetchError("PDF has zero pages")
        return page_count
    except DocumentFetchError:
        raise
    except Exception as e:
        raise DocumentFetchError(f"Corrupt or unreadable PDF: {e}")


async def fetch_document(url: str) -> FetchedDocument:
    """Download document to a temp file for Gemini File API upload."""
    max_size = settings.max_document_size_mb * 1024 * 1024

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise DocumentFetchError(f"HTTP {e.response.status_code} fetching document: {url}")
    except httpx.RequestError as e:
        raise DocumentFetchError(f"Failed to fetch document: {e}")

    if len(response.content) > max_size:
        raise DocumentFetchError(f"Document exceeds {settings.max_document_size_mb}MB limit")

    content_type = response.headers.get("content-type", "")
    is_pdf = "application/pdf" in content_type or url.lower().endswith(".pdf")

    if is_pdf:
        page_count = _validate_pdf(response.content)
        logger.info("pdf_validated", url=url, pages=page_count)
        # Write to temp file for Gemini upload
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(response.content)
        tmp.close()
        return FetchedDocument(
            file_path=tmp.name,
            media_type="application/pdf",
            page_count=page_count,
        )
    else:
        # Plain text — write to temp file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w")
        tmp.write(response.text)
        tmp.close()
        return FetchedDocument(
            file_path=tmp.name,
            media_type="text/plain",
            text_content=response.text,
        )


def cleanup_document(doc: FetchedDocument):
    """Remove the temp file after processing."""
    try:
        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    except OSError:
        pass
