import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm

from .catalog import fetch_crops, fetch_regions
from .client import build_session
from .pdf_links import fetch_pdf_links
from .pdf_store import detect_language, download_bytes, extract_text_from_bytes, save

DEFAULT_LANGS = {"en"}


class IncrementalJsonlWriter:
    """Append-only JSONL writer shared across worker threads. One JSON object per line -
    the format is meant for streaming straight into a DB (e.g. mongoimport, line-by-line
    ingestion), not for loading the whole file as one JSON document."""

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def append_rows(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self.lock, open(self.path, "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def write_rows(self, rows: list[dict]) -> None:
        """Overwrite the file from scratch (used for the cheap, always-rebuilt catalog)."""
        with self.lock, open(self.path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_catalog(session, out_dir: str, resume: bool) -> pd.DataFrame:
    """Crop list -> region list per crop. Cheap (~35 requests), always rebuilt unless resuming."""
    crops_jsonl = os.path.join(out_dir, "crops.jsonl")
    regions_jsonl = os.path.join(out_dir, "regions.jsonl")

    if resume and os.path.exists(crops_jsonl) and os.path.exists(regions_jsonl):
        crops = read_jsonl(crops_jsonl)
        regions = read_jsonl(regions_jsonl)
    else:
        print("Fetching crop list...")
        crops = fetch_crops(session)
        IncrementalJsonlWriter(crops_jsonl).write_rows(crops)

        print(f"Fetching regions for {len(crops)} crops...")
        regions = []
        for crop in tqdm(crops):
            regions.extend(fetch_regions(session, crop["crop_id"]))
        IncrementalJsonlWriter(regions_jsonl).write_rows(regions)

    print(f"{len(crops)} crops, {len(regions)} crop-region pairs -> {crops_jsonl}, {regions_jsonl}")
    return pd.DataFrame(crops).merge(pd.DataFrame(regions), on="crop_id")


def collect_region_pdfs(
    session, out_dir: str, crop_id: str, crop_name: str, region_id: str, region_name: str, langs: set[str]
) -> list[dict]:
    pdf_urls = fetch_pdf_links(session, crop_id, region_id)
    rows = []
    seen_langs = set()
    for pdf_url in pdf_urls:
        pdf_bytes = download_bytes(session, pdf_url)
        text = extract_text_from_bytes(pdf_bytes)
        lang = detect_language(text)
        if lang in seen_langs:
            # Both buttons pointed at the same language's PDF (rare edge case) - skip the dupe.
            continue
        seen_langs.add(lang)
        if lang not in langs:
            continue

        stem = f"{crop_id}_{region_id}_{lang}"
        pdf_path = os.path.join(out_dir, "pdfs", f"{stem}.pdf")
        text_path = os.path.join(out_dir, "text", f"{stem}.txt")
        save(pdf_bytes, text, pdf_path, text_path)

        rows.append(
            {
                "crop_id": crop_id,
                "crop_name": crop_name,
                "region_id": region_id,
                "region_name": region_name,
                "lang": lang,
                "pdf_url": pdf_url,
                "pdf_path": pdf_path,
                "text": text,
            }
        )
    return rows


def load_done_pairs(jsonl_path: str) -> set[tuple[str, str]]:
    return {(row["crop_id"], row["region_id"]) for row in read_jsonl(jsonl_path)}


def run(out_dir: str, workers: int, resume: bool, langs: set[str]) -> None:
    os.makedirs(os.path.join(out_dir, "pdfs"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "text"), exist_ok=True)

    session = build_session(pool_size=workers)
    catalog_df = build_catalog(session, out_dir, resume)

    calendars_jsonl = os.path.join(out_dir, "calendars.jsonl")
    already_done = load_done_pairs(calendars_jsonl) if resume else set()
    pending = [
        row
        for row in catalog_df.to_dict("records")
        if (row["crop_id"], row["region_id"]) not in already_done
    ]
    if not pending:
        print("Nothing to do, all crop-region PDFs already scraped.")
        return
    print(f"Fetching PDFs for {len(pending)} crop-region pairs ({len(already_done)} already done), langs={sorted(langs)}...")

    writer = IncrementalJsonlWriter(calendars_jsonl)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                collect_region_pdfs,
                session,
                out_dir,
                row["crop_id"],
                row["crop_name"],
                row["region_id"],
                row["region_name"],
                langs,
            ): row
            for row in pending
        }
        for future in tqdm(as_completed(futures), total=len(futures)):
            row = futures[future]
            try:
                rows = future.result()
            except Exception as exc:
                tqdm.write(f"crop {row['crop_id']} region {row['region_id']} failed: {exc}")
                continue
            writer.append_rows(rows)

    print(f"Done. Wrote {calendars_jsonl}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape crop weather calendars from bamis.gov.bd")
    parser.add_argument("--out-dir", default="data/bamis", help="Directory to write output to")
    parser.add_argument("--workers", type=int, default=6, help="Number of concurrent requests")
    parser.add_argument("--no-resume", action="store_true", help="Ignore existing output and start fresh")
    parser.add_argument(
        "--langs",
        default="en",
        help="Comma-separated languages to keep (bn, en). Default: en only.",
    )
    args = parser.parse_args()
    langs = {lang.strip() for lang in args.langs.split(",") if lang.strip()}
    run(out_dir=args.out_dir, workers=args.workers, resume=not args.no_resume, langs=langs)


if __name__ == "__main__":
    main()
