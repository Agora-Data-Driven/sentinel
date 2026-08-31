"""Turn an uploaded PDF into the plain text a growth-journal entry can hold.

Why text, and why the journal: the AI coach reads nothing it is not handed. A PDF sitting in a
bucket would be invisible to it, whereas a journal entry is already wired end to end — its TITLE
ships in the coach's complete index on every turn and its body is fetched whole when a conversation
bears on it (services/development.holistic_digest + growth_details, AGENTS.md §5 "growth-journal
INDEX"). So "upload a PDF" is really "make an entry whose detail is the PDF's text", and no new
table, bucket, or migration is needed (prod does not run alembic — a schema change here would be a
silent no-op).

Two rules carried over from that section, because they apply to imported text exactly as they do
to typed text:

  * A gap must be DECLARED, never silent. A PDF longer than `MAX_CHARS` is cut, and the cut is
    written into the text itself in words the coach will read ("N more pages were not imported"),
    so a miss reads as "I don't have that part" rather than "that part doesn't exist".
  * Page markers stay in. `[page 12]` lines let the coach say where in the document something is,
    and cost almost nothing.

`pypdf` is imported lazily so an image built without it still boots and only this feature reports
itself unavailable — the same pattern as google-auth in services/report_doc.py.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

# Upper bound on the text one entry may hold, in characters. Generous on purpose: the coach's own
# hydrate budget is ~24k chars per turn, but the top-ranked entry is always loaded WHOLE even when
# it alone exceeds that (mastery-engine server.js growthGroundingFor), so a 100-page handbook still
# reaches the model when the conversation is about it. Past this, the text is cut AND says so.
MAX_CHARS = 200_000

# Upload ceiling. Text-heavy PDFs are small; anything bigger is almost certainly scanned images,
# which yield no text anyway.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


class PdfUnavailable(RuntimeError):
    """The PDF library is not installed in this image."""


class PdfError(ValueError):
    """The file could not be read as a text PDF. The message is user-facing."""


@dataclass
class PdfText:
    text: str
    pages: int            # pages in the document
    pages_imported: int   # pages whose text made it into `text`
    truncated: bool
    title: str | None     # the document's own title, when its metadata carries one


def extract_pdf_text(data: bytes, *, max_chars: int = MAX_CHARS) -> PdfText:
    """Extract page-marked text from PDF bytes. Raises PdfError for unreadable/empty/encrypted
    input, PdfUnavailable when pypdf is missing."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as e:  # pragma: no cover - depends on the image
        raise PdfUnavailable("PDF import is not available on this server") from e

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # Many "encrypted" PDFs only restrict printing and open with an empty password.
            try:
                if not reader.decrypt(""):
                    raise PdfError("That PDF is password-protected — remove the password and try again")
            except PdfError:
                raise
            except Exception as e:  # noqa: BLE001 - pypdf raises a mix of types here
                raise PdfError("That PDF is password-protected — remove the password and try again") from e
        total_pages = len(reader.pages)
    except PdfError:
        raise
    except (PdfReadError, ValueError, TypeError, OSError) as e:
        raise PdfError("That file doesn't look like a readable PDF") from e

    meta_title = None
    try:
        raw = reader.metadata.title if reader.metadata else None
        meta_title = (str(raw).strip() or None) if raw else None
    except Exception:  # noqa: BLE001 - metadata is best-effort
        meta_title = None

    parts: list[str] = []
    used = 0
    imported = 0
    truncated = False
    for i in range(total_pages):
        try:
            page_text = (reader.pages[i].extract_text() or "").strip()
        except Exception:  # noqa: BLE001 - one bad page must not sink the document
            page_text = ""
        if not page_text:
            continue
        chunk = f"[page {i + 1}]\n{page_text}"
        if used + len(chunk) > max_chars and parts:
            truncated = True
            break
        if len(chunk) > max_chars:
            # A single page bigger than the whole budget: keep what fits and say so.
            chunk = chunk[:max_chars]
            truncated = True
        parts.append(chunk)
        used += len(chunk) + 2
        imported += 1
        if truncated:
            break

    if not parts:
        raise PdfError("No readable text in that PDF — if it is a scan, it has no text layer to import")

    text = "\n\n".join(parts)
    if truncated:
        left = total_pages - imported
        text += (f"\n\n[Import note: this PDF was cut here to fit — {left} more page{'s' if left != 1 else ''} "
                 f"({total_pages} in total) were NOT imported. Anything past this point is unknown, not absent.]")
    return PdfText(text=text, pages=total_pages, pages_imported=imported, truncated=truncated, title=meta_title)
