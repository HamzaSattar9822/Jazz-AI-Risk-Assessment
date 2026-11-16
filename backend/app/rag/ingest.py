"""Build the approved AIRA FTS5 index atomically.

Run from backend/: python -m app.rag.ingest
Only files explicitly listed in knowledge_base/manifest.json with an
approved status are eligible for indexing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "knowledge_base"
SOURCE_DIR = KB_DIR / "source_docs"
MANIFEST_PATH = KB_DIR / "manifest.json"
INDEX_PATH = KB_DIR / "aira_knowledge.sqlite3"
MAX_CHARS = 1200
MAX_FILE_BYTES = 25 * 1024 * 1024
ALLOWED_STATUSES = {"current", "superseded"}
ALLOWED_AUTHORITIES = {"official", "supporting"}
ALLOWED_SUFFIXES = {".docx", ".xlsx", ".html", ".htm", ".pdf", ".md", ".txt"}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        if not self.skip and tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1
        if not self.skip and tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def pack_lines(lines, max_chars=MAX_CHARS):
    chunks, buf, size = [], [], 0
    for text, locator in lines:
        text = clean(text)
        if not text:
            continue
        # Split oversized paragraphs so all indexed passages stay bounded.
        while len(text) > max_chars:
            if buf:
                chunks.append((" ".join(x[0] for x in buf), buf[0][1]))
                buf, size = [], 0
            chunks.append((text[:max_chars], locator))
            text = text[max_chars:]
        if buf and size + len(text) > max_chars:
            chunks.append((" ".join(x[0] for x in buf), buf[0][1]))
            buf, size = [], 0
        buf.append((text, locator))
        size += len(text)
    if buf:
        chunks.append((" ".join(x[0] for x in buf), buf[0][1]))
    return chunks


def extract_docx(path: Path):
    doc = Document(path)
    lines, heading = [], ""
    for i, para in enumerate(doc.paragraphs, 1):
        txt = clean(para.text)
        if not txt:
            continue
        style = (para.style.name or "").lower()
        if "heading" in style or "title" in style:
            heading = txt
        prefix = f"{heading}. " if heading and txt != heading else ""
        lines.append((prefix + txt, f"paragraph {i}" + (f", section: {heading}" if heading else "")))
    for ti, table in enumerate(doc.tables, 1):
        for ri, row in enumerate(table.rows, 1):
            cells = [clean(cell.text) for cell in row.cells]
            if any(cells):
                lines.append((" | ".join(cells), f"table {ti}, row {ri}"))
    return pack_lines(lines)


def extract_xlsx(path: Path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    output = []
    try:
        for sheet in workbook.worksheets:
            lines = []
            for row_no, row in enumerate(sheet.iter_rows(values_only=True), 1):
                values = [clean(value) for value in row]
                while values and not values[-1]:
                    values.pop()
                if any(values):
                    lines.append((" | ".join(value for value in values if value),
                                  f"sheet: {sheet.title}, row {row_no}"))
            output.extend(
                (f"Worksheet: {sheet.title}. {chunk}", locator)
                for chunk, locator in pack_lines(lines)
            )
    finally:
        workbook.close()
    return output


def extract_html(path: Path):
    parser = TextExtractor()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return pack_lines([(part, "HTML content") for part in parser.parts])


def extract_pdf(path: Path):
    reader = PdfReader(str(path), strict=False)
    lines = []
    for page_no, page in enumerate(reader.pages, 1):
        page_text = page.extract_text() or ""
        for paragraph in re.split(r"\n{2,}", page_text):
            if paragraph.strip():
                lines.append((paragraph, f"page {page_no}"))
    return pack_lines(lines)


def extract_file(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx(path)
    if suffix == ".xlsx":
        return extract_xlsx(path)
    if suffix in {".html", ".htm"}:
        return extract_html(path)
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix in {".md", ".txt"}:
        return pack_lines([
            (line, f"line {number}")
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            )
        ])
    return []


def load_approved_manifest(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Required source manifest is missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise RuntimeError("Knowledge manifest must be a non-empty JSON object")
    approved = {}
    for filename, metadata in data.items():
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise RuntimeError(f"Invalid manifest filename: {filename!r}")
        if not isinstance(metadata, dict):
            raise RuntimeError(f"Invalid manifest metadata for {filename}")
        status = metadata.get("status")
        authority = metadata.get("authority")
        if status not in ALLOWED_STATUSES or authority not in ALLOWED_AUTHORITIES:
            continue
        if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        approved[filename] = metadata
    if not approved:
        raise RuntimeError("Manifest contains no approved, supported source documents")
    return approved


def build_index(source_dir: Path, index_path: Path, manifest_path: Path):
    manifest = load_approved_manifest(manifest_path)
    source_dir = source_dir.resolve()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{index_path.name}.", suffix=".tmp", dir=str(index_path.parent)
    )
    os.close(fd)
    temp_path = Path(temp_name)
    total = 0
    try:
        conn = sqlite3.connect(temp_path)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("""
                CREATE TABLE chunks (
                    id TEXT PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    locator TEXT NOT NULL,
                    content TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE chunks_fts USING fts5(
                    id UNINDEXED, source_name, category, content,
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)
            for filename, metadata in sorted(manifest.items()):
                path = source_dir / filename
                if not path.exists() or not path.is_file() or path.is_symlink():
                    print(f"SKIP missing/unsafe source: {filename}")
                    continue
                resolved = path.resolve()
                if source_dir not in resolved.parents:
                    raise RuntimeError(f"Source escaped approved directory: {filename}")
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise RuntimeError(f"Source exceeds {MAX_FILE_BYTES} bytes: {filename}")
                chunks = extract_file(path)
                for number, (content, locator) in enumerate(chunks, 1):
                    digest = hashlib.sha256(
                        f"{filename}:{locator}:{number}:{content}".encode("utf-8")
                    ).hexdigest()[:24]
                    values = (
                        digest, filename, str(metadata.get("category", "general"))[:100],
                        metadata["authority"], metadata["status"],
                        str(locator)[:300], content[:MAX_CHARS],
                    )
                    conn.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)", values)
                    conn.execute(
                        "INSERT INTO chunks_fts VALUES (?, ?, ?, ?)",
                        (digest, filename, values[2], values[6]),
                    )
                    total += 1
                print(f"{filename}: {len(chunks)} chunks [{metadata['authority']}/{metadata['status']}]")
            if total == 0:
                raise RuntimeError("No passages were indexed; existing index was preserved")
            conn.commit()
            # Verify FTS and metadata are readable before promoting the index.
            count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            fts_count = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
            if count != total or fts_count != total:
                raise RuntimeError("Index integrity check failed")
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        finally:
            conn.close()
        os.replace(temp_path, index_path)
        print(f"Indexed {total} passages into {index_path}")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    build_index(args.source_dir, args.index, args.manifest)


if __name__ == "__main__":
    main()
