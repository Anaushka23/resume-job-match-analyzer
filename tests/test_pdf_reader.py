"""
tests/test_pdf_reader.py - Unit tests for the PDF text extraction module.

WHY MOCK pdfplumber?
We don't need a real PDF file to test our error handling logic.
Using unittest.mock.patch we can simulate what pdfplumber returns:
  - A page with text
  - A page with no text (image-only / scanned)
  - An empty PDF (no pages)
  - A totally broken file that throws an exception

This makes tests fast (no file I/O), self-contained, and deterministic.

KEY CONCEPT — MOCKING:
When you write `with patch('pdfplumber.open') as mock_open`, Python temporarily
replaces the real pdfplumber.open with a fake object you control. After the 
`with` block, the real function is restored. The code under test never knows 
the difference — it still calls pdfplumber.open(), but gets your fake response.
"""

import pytest
from unittest.mock import patch, MagicMock
from services.pdf_reader import extract_text_from_pdf, PDFReadError


def make_mock_page(text: str | None) -> MagicMock:
    """
    Helper: creates a fake pdfplumber page whose extract_text() returns 
    the given text (or None for a scanned page).
    """
    page = MagicMock()
    page.extract_text.return_value = text
    return page


def make_mock_pdf(pages: list) -> MagicMock:
    """
    Helper: wraps a list of fake pages in a mock PDF context manager.
    The 'with pdfplumber.open(...) as pdf' pattern is what we're simulating.
    """
    mock_pdf = MagicMock()
    mock_pdf.pages = pages
    # __enter__ and __exit__ make MagicMock work as a context manager (with statement)
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_extracts_text_successfully():
    """
    Happy path: a normal PDF with text on every page.
    Should return a single string containing all pages' text.
    """
    pages = [
        make_mock_page("John Smith\nPython Developer"),
        make_mock_page("Skills: Django, PostgreSQL"),
    ]
    mock_pdf = make_mock_pdf(pages)

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_text_from_pdf("fake_resume.pdf")

    assert "John Smith" in result
    assert "Skills: Django, PostgreSQL" in result


def test_raises_error_on_empty_pdf():
    """
    Edge case: PDF with zero pages.
    Should raise PDFReadError with a clear message.
    """
    mock_pdf = make_mock_pdf([])  # no pages at all

    with patch("pdfplumber.open", return_value=mock_pdf):
        with pytest.raises(PDFReadError) as exc_info:
            extract_text_from_pdf("empty.pdf")

    assert "no pages" in str(exc_info.value).lower()


def test_raises_error_on_fully_scanned_pdf():
    """
    Edge case: every page is a scanned image — no text layer anywhere.
    extract_text() returns None for each page.
    Should raise PDFReadError with a friendly message.
    """
    pages = [
        make_mock_page(None),  # scanned page 1
        make_mock_page(None),  # scanned page 2
    ]
    mock_pdf = make_mock_pdf(pages)

    with patch("pdfplumber.open", return_value=mock_pdf):
        with pytest.raises(PDFReadError) as exc_info:
            extract_text_from_pdf("scanned_resume.pdf")

    assert "scanned" in str(exc_info.value).lower()


def test_partial_scanned_pdf_returns_text_from_good_pages():
    """
    Mixed PDF: page 1 is scanned, page 2 has text.
    Should return text from page 2 and NOT raise an error.
    This reflects real-world resumes that start with a decorative cover page.
    """
    pages = [
        make_mock_page(None),              # scanned/decorative page
        make_mock_page("Jane Doe\nB.Tech CS"),  # good text page
    ]
    mock_pdf = make_mock_pdf(pages)

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_text_from_pdf("mixed.pdf")

    assert "Jane Doe" in result
    assert "B.Tech CS" in result


def test_raises_error_on_corrupted_file():
    """
    Edge case: pdfplumber itself throws an exception (corrupted or 
    password-protected PDF). Should be caught and re-raised as PDFReadError.
    """
    with patch("pdfplumber.open", side_effect=Exception("file is damaged")):
        with pytest.raises(PDFReadError) as exc_info:
            extract_text_from_pdf("corrupt.pdf")

    assert "corrupted" in str(exc_info.value).lower()
