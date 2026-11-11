"""Document extraction and section-aware chunking.

Extraction turns PDF / DOCX / TXT / MD files into *segments* that remember the page
and section heading they came from. Chunking then splits each segment with
LangChain's RecursiveCharacterTextSplitter, so a chunk never straddles two sections
and every chunk can be cited as "document, section, page".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}
# "3 Risk-based approach", "4.2 Wire transfers", "SECTION 5 ..." style headings
HEADING_RE = re.compile(r"^(?:section\s+)?\d+(?:\.\d+)*\.?\s+\S.{0,120}$", re.IGNORECASE)


@dataclass
class Segment:
    text: str
    section: str | None
    page: int | None


@dataclass
class Chunk:
    chunk_index: int
    text: str
    section: str | None
    page: int | None


def _is_heading(line: str) -> bool:
    line = line.strip()
    return bool(line) and len(line) <= 120 and bool(HEADING_RE.match(line)) and not line.endswith(".")


def _split_by_headings(lines: list[str], page: int | None, current: str | None) -> tuple[list[Segment], str | None]:
    segs: list[Segment] = []
    buf: list[str] = []

    def flush():
        txt = " ".join(x.strip() for x in buf if x.strip())
        if txt:
            segs.append(Segment(txt, current, page))
        buf.clear()

    for line in lines:
        if _is_heading(line):
            flush()
            current = line.strip().title() if line.isupper() else line.strip()
        else:
            buf.append(line)
    flush()
    return segs, current


def extract(path: Path) -> tuple[list[Segment], int | None]:
    """Return (segments, page_count). Page numbers are 1-based for PDFs, None otherwise."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        segs, current = [], None
        for pno, page in enumerate(reader.pages, start=1):
            page_segs, current = _split_by_headings((page.extract_text() or "").splitlines(), pno, current)
            segs += page_segs
        return segs, len(reader.pages)
    if ext == ".docx":
        import docx

        d = docx.Document(str(path))
        segs, current, buf = [], None, []
        for p in d.paragraphs:
            if p.style.name.lower().startswith(("heading", "title")):
                if buf:
                    segs.append(Segment(" ".join(buf), current, None))
                    buf = []
                if not p.style.name.lower().startswith("title"):
                    current = p.text.strip()
            elif p.text.strip():
                buf.append(p.text.strip())
        if buf:
            segs.append(Segment(" ".join(buf), current, None))
        return segs, None
    if ext == ".md":
        segs, current, buf = [], None, []
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^(#{1,6})\s+(.*)", line)
            if m:
                if buf:
                    segs.append(Segment(" ".join(buf), current, None))
                    buf = []
                if len(m.group(1)) > 1:            # '# Title' is the document title, not a section
                    current = m.group(2).strip()
            elif line.strip():
                buf.append(line.strip().strip("_"))
        if buf:
            segs.append(Segment(" ".join(buf), current, None))
        return segs, None
    if ext == ".txt":
        segs, _ = _split_by_headings(path.read_text(encoding="utf-8").splitlines(), None, None)
        return segs, None
    raise ValueError(f"Unsupported file type: {path.suffix}")


def chunk_segments(segments: list[Segment], chunk_size: int = 900, overlap: int = 150) -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap,
                                              separators=["\n\n", "\n", ". ", "; ", ", ", " "])
    chunks: list[Chunk] = []
    for seg in segments:
        for piece in splitter.split_text(seg.text):
            chunks.append(Chunk(len(chunks), piece.strip(), seg.section, seg.page))
    return chunks
