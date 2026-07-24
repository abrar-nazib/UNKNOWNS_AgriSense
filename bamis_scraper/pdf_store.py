import os
import re

import pdfplumber
import requests

# Bengali Unicode block (letters + digits ০-৯). Header/table fonts in some PDFs
# garble complex conjuncts on extraction, but Bengali digits in the weekly-data
# rows always survive, so this stays a reliable signal even on messy extractions.
BENGALI_RE = re.compile(r"[ঀ-৿]")


def download_bytes(session: requests.Session, url: str) -> bytes:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content


def extract_text_from_bytes(pdf_bytes: bytes) -> str:
    import io

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_text = [page.extract_text() or "" for page in pdf.pages]
    return "\n\f\n".join(pages_text)


def detect_language(text: str, min_bengali_chars: int = 5) -> str:
    return "bn" if len(BENGALI_RE.findall(text)) >= min_bengali_chars else "en"


def save(pdf_bytes: bytes, text: str, pdf_path: str, text_path: str) -> None:
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)
