# NOTE: authored on branch rahi-test (RaihanulHaque); produced backend/app/data/kb_corpus/frg2024.md (pages 10-239, embedded text + tesseract OCR for image-only pages).
import pypdfium2 as pdfium
import pytesseract
from tqdm import tqdm

TEXT_LAYER_MIN_CHARS = 20  # pages with less text than this are treated as image-only
RENDER_SCALE = 2.0  # ~144 DPI - enough for tesseract, keeps OCR pages fast


def extract_page_text(page) -> tuple[str, str]:
    """Prefer the PDF's own selectable text layer; only OCR when it's missing (scanned/image
    pages). Most pages in these documents already have selectable text, so running a heavy
    OCR model on every page - as the previous LightOnOCR-2-1B pipeline did - redoes work the
    PDF already has for free and is why it was slow."""
    embedded = page.get_textpage().get_text_range().strip()
    if len(embedded) >= TEXT_LAYER_MIN_CHARS:
        return embedded, "embedded"

    image = page.render(scale=RENDER_SCALE).to_pil()
    return pytesseract.image_to_string(image).strip(), "ocr"


def convert_pdf_to_markdown(pdf_path: str, output_md_path: str):
    pdf = pdfium.PdfDocument(pdf_path)
    num_pages = len(pdf)
    print(f"Processing {num_pages} pages from '{pdf_path}'...")

    parts = []
    ocr_count = 0
    for i in tqdm(range(num_pages), desc="Converting Pages"):
        text, source = extract_page_text(pdf[i])
        ocr_count += source == "ocr"
        parts.append(f"<!-- Page {i + 1} ({source}) -->\n\n{text}\n\n")

    with open(output_md_path, "w", encoding="utf-8") as f:
        f.writelines(parts)

    print(f"\nDone. {ocr_count}/{num_pages} pages needed OCR. Saved to '{output_md_path}'")


if __name__ == "__main__":
    convert_pdf_to_markdown("FRG English 30.10.2024.pdf", "output_document.md")
