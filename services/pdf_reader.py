"""
services/pdf_reader.py - Extracts plain text from uploaded PDF resume files.

WHY A DEDICATED MODULE?
PDF files are complex binary formats. Extraction can fail in several ways:
  - The PDF contains only scanned images (no embedded text layer).
  - The file is empty, password-protected, or corrupted.
  - The layout uses columns or tables that confuse naive parsers.

By isolating all PDF logic here, the rest of the application stays clean.
If we later add OCR support for scanned PDFs, we only modify this one file.
"""

import logging
import pdfplumber

logger = logging.getLogger("ResumeAnalyzer.pdf_reader")


class PDFReadError(Exception):
    """
    Custom exception for PDF-related failures.

    WHY A CUSTOM EXCEPTION?
    Raising a custom exception (instead of a generic Exception) lets the caller
    distinguish between "PDF is unreadable" vs "network error" vs "AI failed".
    This makes error handling and logging much cleaner in analyzer.py and app.py.
    """
    pass


def extract_text_from_pdf(file_source) -> str:
    """
    Extracts and returns plain text from a PDF file.

    Accepts either:
      - A file path string (for CLI testing)
      - A file-like object (e.g., Streamlit's UploadedFile)

    Args:
        file_source: Path string OR a binary file-like object opened for reading.

    Returns:
        A single string containing all text found in the PDF.

    Raises:
        PDFReadError: If the PDF is empty, scanned-only, or unreadable.
    """
    try:
        # pdfplumber.open() accepts both file paths and file-like objects,
        # so we don't need separate handling for CLI vs Streamlit usage.
        with pdfplumber.open(file_source) as pdf:
            if len(pdf.pages) == 0:
                raise PDFReadError("The PDF has no pages. It may be empty or corrupted.")

            extracted_pages = []
            for page_number, page in enumerate(pdf.pages, start=1):
                # extract_text() returns None for image-only (scanned) pages.
                page_text = page.extract_text()
                if page_text:
                    extracted_pages.append(page_text)
                else:
                    # Log a warning but keep processing other pages.
                    # A resume might have a decorative image page followed by text.
                    logger.warning(
                        "Page %d appears to be a scanned image — no text could be extracted.",
                        page_number
                    )

            # Combine all pages into one string, separated by a newline.
            full_text = "\n".join(extracted_pages).strip()

            if not full_text:
                # Every page was image-only — no text layer exists at all.
                raise PDFReadError(
                    "No text could be extracted from this PDF. "
                    "It appears to be a scanned document (image-only). "
                    "Please use a text-based PDF or paste your resume as plain text."
                )

            logger.info(
                "Successfully extracted %d characters from PDF (%d pages).",
                len(full_text),
                len(pdf.pages)
            )
            return full_text

    except PDFReadError:
        # Re-raise our own errors without wrapping them — they're already descriptive.
        raise
    except Exception as e:
        # Catch unexpected errors (corrupted file, password protected, etc.)
        # and wrap them in our custom type so callers only need one except clause.
        logger.error("Failed to read PDF: %s", str(e))
        raise PDFReadError(
            f"Could not read the PDF file. It may be corrupted or password-protected. "
            f"Technical detail: {str(e)}"
        ) from e
