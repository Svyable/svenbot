"""Bounded, local-only document-to-text extraction for explicit file indexing.

Extracted line numbers describe the text snapshot, not original PDF page geometry or
Word display lines. No network, OCR, document macros, embedded files or formulas run.
"""
from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path

DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".csv", ".tsv"}
MAX_DOCUMENT_BYTES = 8_000_000
MAX_EXTRACTED_CHARS = 1_500_000
MAX_PDF_PAGES = 100
MAX_DOCX_XML_BYTES = 3_000_000


class DocumentError(ValueError):
    """A selected document cannot be extracted within our local safety bounds."""


def _bounded(text: str) -> str:
    if len(text) > MAX_EXTRACTED_CHARS:
        raise DocumentError("Extracted text exceeded the 1.5 million character limit")
    if not text.strip():
        raise DocumentError("No selectable text found; scanned documents require separate OCR")
    return text


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.length = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "template", "noscript", "svg"):
            self.skip += 1
        elif not self.skip and tag in ("p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr", "section", "article"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        self.length += len(data)
        if self.length > MAX_EXTRACTED_CHARS:
            raise DocumentError("HTML extracted text exceeded its safety limit")
        self.parts.append(data)


def _html(raw: bytes) -> str:
    try:
        html = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentError("HTML must be UTF-8 encoded") from exc
    parser = _HTMLText()
    parser.feed(html)
    return _bounded("\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip()))


def _csv(raw: bytes, *, delimiter: str) -> str:
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentError("CSV/TSV must be UTF-8 encoded") from exc
    stream = csv.reader(io.StringIO(source, newline=""), delimiter=delimiter, strict=True)
    lines: list[str] = []
    total = 0
    try:
        headers = next(stream, [])
        if len(headers) > 100:
            raise DocumentError("Too many CSV/TSV columns (max 100)")
        for number, row in enumerate(stream, 2):
            if number > 10_001:
                raise DocumentError("Too many CSV/TSV records (max 10,000)")
            if len(row) > 100:
                raise DocumentError("Too many CSV/TSV columns (max 100)")
            cells = []
            for col, value in enumerate(row):
                key = " ".join(headers[col].split()) if col < len(headers) else f"column {col+1}"
                # Escape embedded line separators so citations remain stable by record.
                value = " ".join(value.split())
                cells.append(f"{key}: {value}")
            line = f"Record {number-1}: " + " | ".join(cells)
            total += len(line)
            if total > MAX_EXTRACTED_CHARS:
                raise DocumentError("CSV/TSV extracted text exceeded its safety limit")
            lines.append(line)
    except (csv.Error, UnicodeError) as exc:
        raise DocumentError("Malformed CSV/TSV") from exc
    return _bounded("\n".join(lines))


def _docx(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            try:
                entry = archive.getinfo("word/document.xml")
            except KeyError as exc:
                raise DocumentError("DOCX missing word/document.xml") from exc
            if entry.file_size > MAX_DOCX_XML_BYTES:
                raise DocumentError("DOCX document XML exceeded the extraction limit")
            # Only this inert XML part is read. No macros, linked templates, or media.
            with archive.open(entry) as source:
                xml = source.read(MAX_DOCX_XML_BYTES + 1)
            if len(xml) > MAX_DOCX_XML_BYTES:
                raise DocumentError("DOCX document XML exceeded the extraction limit")
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("Malformed DOCX archive") from exc
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise DocumentError("Malformed DOCX XML") from exc
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines = []
    size = 0
    for paragraph in root.iter(ns + "p"):
        content = "".join(t.text or "" for t in paragraph.iter(ns + "t"))
        if content.strip():
            size += len(content) + 1
            if size > MAX_EXTRACTED_CHARS:
                raise DocumentError("DOCX extracted text exceeded its safety limit")
            lines.append(content)
    return _bounded("\n".join(lines))


def _pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentError('PDF indexing requires the optional local parser: pip install "svenbot[documents]"') from exc
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise DocumentError("Encrypted PDF documents are not supported")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentError(f"PDF exceeds the {MAX_PDF_PAGES}-page extraction limit")
        parts = []
        length = 0
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            length += len(text)
            if length > MAX_EXTRACTED_CHARS:
                raise DocumentError("PDF extracted text exceeded its safety limit")
            if text.strip():
                parts.append(f"[PDF page {page_number}]\n{text.strip()}")
        return _bounded("\n\n".join(parts))
    except DocumentError:
        raise
    except Exception as exc:
        # pypdf has its own PdfReadError classes. Untrusted PDFs should fail
        # closed and never expose parser tracebacks or partial source text.
        raise DocumentError("Could not extract text from PDF") from exc


def extract(filename: str, raw: bytes) -> str:
    """Extract bounded, normalized text from a supported document; never write a file."""
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise DocumentError("Document exceeded the 8 MB input limit")
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _pdf(raw)
    if ext == ".docx":
        return _docx(raw)
    if ext in (".html", ".htm"):
        return _html(raw)
    if ext in (".csv", ".tsv"):
        return _csv(raw, delimiter="\t" if ext == ".tsv" else ",")
    raise DocumentError("Unsupported document extension")
