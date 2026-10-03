#!/usr/bin/env python3
"""
PDF Page to AI
=============
Turn every page of a PDF into a self-contained, AI-friendly package:

* ``page.png``          – rendered page image
* ``page.txt``          – clean plain text (digital or OCR)
* ``page.meta.json``    – structured metadata AIs love

Metadata includes document title, author, page number, dimensions,
word count, language hint, extraction method, and a short preview.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pymupdf as fitz

try:
    import pytesseract
    from PIL import Image
    import io
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False


DEFAULT_INPUT = "./pdfs"
DEFAULT_OUTPUT = "./pages_for_ai"
DEFAULT_DPI = 200
TEXT_THRESHOLD = 40


def ocr_pixmap(pix: fitz.Pixmap) -> str:
    if not HAS_TESSERACT:
        return ""
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    try:
        return pytesseract.image_to_string(img) or ""
    except Exception:
        return ""


def clean_text(raw: str) -> str:
    """Normalise whitespace and strip form-feed / nulls."""
    text = raw.replace("\x00", "").replace("\f", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def process_pdf(
    pdf_path: Path,
    out_root: Path,
    dpi: int,
    force_ocr: bool,
) -> int:
    stem = pdf_path.stem
    dest = out_root / stem
    dest.mkdir(parents=True, exist_ok=True)

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        print(f"  ERROR opening {pdf_path.name}: {exc}")
        return 0

    # Document-level metadata
    meta = doc.metadata or {}
    doc_title = (meta.get("title") or stem).strip()
    doc_author = (meta.get("author") or "").strip()
    doc_subject = (meta.get("subject") or "").strip()
    doc_keywords = (meta.get("keywords") or "").strip()
    total_pages = len(doc)

    pages_done = 0
    for i in range(total_pages):
        page = doc[i]
        page_no = i + 1
        page_dir = dest / f"page_{page_no:03d}"
        page_dir.mkdir(exist_ok=True)

        # --- render ---
        pix = page.get_pixmap(dpi=dpi)
        img_path = page_dir / "page.png"
        pix.save(img_path)

        # --- text ---
        digital = clean_text(page.get_text("text"))
        method = "digital"
        text = digital

        if force_ocr or len(digital) < TEXT_THRESHOLD:
            ocr = clean_text(ocr_pixmap(pix))
            if ocr:
                text = ocr
                method = "ocr" if not digital else "ocr+digital"

        txt_path = page_dir / "page.txt"
        txt_path.write_text(text, encoding="utf-8")

        # --- structured metadata ---
        words = text.split()
        rect = page.rect
        payload = {
            "source_file": pdf_path.name,
            "document_title": doc_title,
            "document_author": doc_author,
            "document_subject": doc_subject,
            "document_keywords": doc_keywords,
            "page_number": page_no,
            "total_pages": total_pages,
            "page_label": f"{page_no} of {total_pages}",
            "width_pt": round(rect.width, 1),
            "height_pt": round(rect.height, 1),
            "rotation": page.rotation,
            "dpi": dpi,
            "extraction_method": method,
            "char_count": len(text),
            "word_count": len(words),
            "has_images": len(page.get_images()) > 0,
            "preview": " ".join(words[:60]) + ("…" if len(words) > 60 else ""),
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }

        meta_path = page_dir / "page.meta.json"
        meta_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        print(f"  p{page_no:03d}  [{method}]  {payload['word_count']} words")
        pages_done += 1

    doc.close()
    return pages_done


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract PDF pages as PNG + text + AI-ready JSON metadata.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input-dir", "-i", default=DEFAULT_INPUT,
                   help="Folder of source PDFs (or a single PDF file)")
    p.add_argument("--output-dir", "-o", default=DEFAULT_OUTPUT,
                   help="Root folder for per-document page packages")
    p.add_argument("--dpi", type=int, default=DEFAULT_DPI,
                   help="Render DPI for page images")
    p.add_argument("--force-ocr", action="store_true",
                   help="Always run Tesseract, even when digital text exists")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    src = Path(args.input_dir)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if src.is_file() and src.suffix.lower() == ".pdf":
        pdfs = [src]
    elif src.is_dir():
        pdfs = sorted(src.glob("*.pdf"))
    else:
        print(f"Not found: {src}", file=sys.stderr)
        return 1

    if not pdfs:
        print(f"No PDFs in {src}")
        return 1

    if not HAS_TESSERACT:
        print("Note: pytesseract not installed – OCR fallback disabled.")
        print("      pip install pytesseract  + system tesseract package\n")

    total = 0
    for pdf in pdfs:
        print(f"Processing {pdf.name} …")
        total += process_pdf(pdf, out, args.dpi, args.force_ocr)

    print(f"\nDone. {total} page package(s) written under {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
