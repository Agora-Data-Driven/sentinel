"""Upload a PDF into the growth journal — and the contract that makes it worth doing.

An uploaded PDF becomes an ENTRY (title + the PDF's text as detail). That is the whole feature: it
is the only shape the AI coach can read, because the journal's index carries every title on every
turn and the body is fetched whole on demand (test_growth_notes.py pins that half). These tests pin
the import side: the text really arrives, the entry really reaches the coach's index, and a cut is
DECLARED in the text rather than silently applied.
"""
from __future__ import annotations

import io

import pytest

from app.models import GrowthItem
from app.services import development as dev_svc
from app.services import pdf_text


def _pdf(pages: list[str], *, title: str | None = None) -> bytes:
    """A real, minimal PDF with one line of text per page (pypdf writes it, pypdf reads it back)."""
    from pypdf import PdfWriter

    w = PdfWriter()
    for text in pages:
        page = w.add_blank_page(width=300, height=300)
        # A tiny content stream: set a font, move, show text. Enough for extract_text().
        stream = f"BT /F1 12 Tf 20 150 Td ({text}) Tj ET".encode("latin-1")
        from pypdf.generic import DictionaryObject, NameObject, StreamObject

        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)}),
        })
        content = StreamObject()
        content._data = stream
        page[NameObject("/Contents")] = w._add_object(content)
    if title:
        w.add_metadata({"/Title": title})
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


# --- the extractor ---------------------------------------------------------------------------
def test_extracts_every_page_with_markers():
    got = pdf_text.extract_pdf_text(_pdf(["alpha one", "beta two", "gamma three"]))
    assert got.pages == 3 and got.pages_imported == 3 and not got.truncated
    assert "[page 1]" in got.text and "alpha one" in got.text
    assert "[page 3]" in got.text and "gamma three" in got.text


def test_reads_the_documents_own_title():
    assert pdf_text.extract_pdf_text(_pdf(["x"], title="Employee Handbook")).title == "Employee Handbook"


def test_truncation_is_declared_in_the_text():
    """Name the gap. A cut PDF must say how much is missing, in words the coach will read."""
    got = pdf_text.extract_pdf_text(_pdf([f"page {i} " + "w" * 40 for i in range(20)]), max_chars=300)
    assert got.truncated
    assert got.pages_imported < got.pages
    assert "NOT imported" in got.text
    assert f"{got.pages - got.pages_imported} more page" in got.text


def test_garbage_is_a_user_facing_error():
    with pytest.raises(pdf_text.PdfError):
        pdf_text.extract_pdf_text(b"this is not a pdf at all")


def test_blank_pdf_is_a_user_facing_error():
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(pdf_text.PdfError, match="No readable text"):
        pdf_text.extract_pdf_text(buf.getvalue())


# --- the endpoint ----------------------------------------------------------------------------
def _upload(client, data: bytes, *, name="handbook.pdf", ctype="application/pdf", **fields):
    return client.post("/api/development/growth/upload",
                       files={"file": (name, data, ctype)}, data=fields)


def test_upload_makes_an_entry_the_coach_can_see(client, db, make_user, auth):
    user = auth(make_user())
    r = _upload(client, _pdf(["first page words", "second page words"]),
                dimension="professional", title="Team handbook")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Team handbook"
    assert body["dimension"] == "professional"
    assert body["import"]["pages"] == 2 and body["import"]["truncated"] is False
    assert "second page words" in body["detail"]
    assert body["detail"].startswith("[Imported from PDF \"handbook.pdf\"")

    # ...and it is in the coach's index like any typed entry, body fetched whole.
    index = dev_svc.holistic_digest(db, user)["growth"]["index"]
    assert [e["title"] for e in index] == ["Team handbook"]
    assert index[0]["chars"] == len(body["detail"])
    detail = dev_svc.growth_details(db, user.id, [body["id"]])
    assert detail[0]["detail"] == body["detail"]


def test_title_falls_back_to_metadata_then_filename(client, make_user, auth):
    auth(make_user())
    r = _upload(client, _pdf(["x"], title="Metadata Title"), name="my_notes-2026.pdf")
    assert r.status_code == 200 and r.json()["title"] == "Metadata Title"
    r = _upload(client, _pdf(["x"]), name="my_notes-2026.pdf")
    assert r.status_code == 200 and r.json()["title"] == "my notes 2026"


def test_upload_is_the_callers_own_entry(client, db, make_user, auth):
    me = auth(make_user())
    other = make_user()
    assert _upload(client, _pdf(["x"])).status_code == 200
    rows = db.query(GrowthItem).all()
    assert len(rows) == 1 and rows[0].user_id == me.id and rows[0].user_id != other.id


def test_rejects_non_pdf_and_unknown_dimension(client, make_user, auth):
    auth(make_user())
    assert _upload(client, b"hello", name="notes.txt", ctype="text/plain").status_code == 400
    assert _upload(client, b"not really", name="fake.pdf").status_code == 400
    assert _upload(client, _pdf(["x"]), dimension="astral").status_code == 400


def test_requires_login(client):
    assert _upload(client, _pdf(["x"])).status_code in (401, 403)
