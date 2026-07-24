import argparse
import csv
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm

from .admin import build_admin_table
from .client import build_session
from .data import fetch_agro_climatic, fetch_edaphic, fetch_map_units
from .notes import AGRO_CLIMATIC_DATA_SOURCE, EDAPHIC_NOTES

AGRO_CLIMATIC_FIELDS = ["upazila_code", "type", "param", "area", "percent", "len"]
EDAPHIC_FIELDS = ["upazila_code", "type", "category", "area", "ord"]
MAP_UNIT_FIELDS = ["upazila_code", "map_unit", "unit_title_en", "unit_title_bn", "area", "percent"]


def write_static_notes(out_dir: str) -> None:
    """Write the site's fixed legend text (category definitions, data-source credit)."""
    notes_df = pd.DataFrame(EDAPHIC_NOTES, columns=["type", "category", "note"])
    notes_df.to_csv(os.path.join(out_dir, "edaphic_definitions.csv"), index=False)
    with open(os.path.join(out_dir, "agro_climatic_data_source.txt"), "w", encoding="utf-8") as f:
        f.write(AGRO_CLIMATIC_DATA_SOURCE + "\n")


def load_done_upazilas(csv_path: str) -> set[str]:
    if not os.path.exists(csv_path):
        return set()
    return set(pd.read_csv(csv_path, usecols=["upazila_code"], dtype=str)["upazila_code"])


class IncrementalCsvWriter:
    """Append-only CSV writer shared across worker threads."""

    def __init__(self, path: str, fieldnames: list[str]):
        self.path = path
        self.fieldnames = fieldnames
        self.lock = threading.Lock()
        self._ensure_header()

    def _ensure_header(self) -> None:
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=self.fieldnames).writeheader()

    def append_rows(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self.lock, open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            for row in rows:
                writer.writerow({k: row.get(k) for k in self.fieldnames})


def collect_upazila(session, upazila_code: str, need: set[str]) -> dict[str, list[dict]]:
    """Fetch only the datasets in `need` (subset of {'agro', 'edaphic', 'mu'})."""
    result: dict[str, list[dict]] = {}
    if "agro" in need:
        result["agro"] = fetch_agro_climatic(session, upazila_code)
    if "edaphic" in need:
        result["edaphic"] = fetch_edaphic(session, upazila_code)
    if "mu" in need:
        result["mu"] = fetch_map_units(session, upazila_code)
    return result


def run(out_dir: str, workers: int, resume: bool) -> None:
    os.makedirs(out_dir, exist_ok=True)
    write_static_notes(out_dir)
    admin_csv = os.path.join(out_dir, "upazilas.csv")
    agro_csv = os.path.join(out_dir, "agro_climatic.csv")
    edaphic_csv = os.path.join(out_dir, "edaphic.csv")
    map_unit_csv = os.path.join(out_dir, "map_units.csv")

    session = build_session(pool_size=workers)

    if resume and os.path.exists(admin_csv):
        admin_df = pd.read_csv(admin_csv, dtype=str)
    else:
        print("Fetching division/district/upazila hierarchy...")
        admin_df = build_admin_table(session)
        admin_df.to_csv(admin_csv, index=False)
    print(f"Found {len(admin_df)} upazilas -> {admin_csv}")

    done = {
        "agro": load_done_upazilas(agro_csv) if resume else set(),
        "edaphic": load_done_upazilas(edaphic_csv) if resume else set(),
        "mu": load_done_upazilas(map_unit_csv) if resume else set(),
    }
    needs = {
        code: {dataset for dataset, done_codes in done.items() if code not in done_codes}
        for code in admin_df["upazila_code"]
    }
    needs = {code: need for code, need in needs.items() if need}
    if not needs:
        print("Nothing to do, all upazilas already scraped.")
        return
    print(f"Fetching data for {len(needs)} upazilas ({len(admin_df) - len(needs)} fully done)...")

    writers = {
        "agro": IncrementalCsvWriter(agro_csv, AGRO_CLIMATIC_FIELDS),
        "edaphic": IncrementalCsvWriter(edaphic_csv, EDAPHIC_FIELDS),
        "mu": IncrementalCsvWriter(map_unit_csv, MAP_UNIT_FIELDS),
    }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(collect_upazila, session, code, need): code for code, need in needs.items()}
        for future in tqdm(as_completed(futures), total=len(futures)):
            code = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                tqdm.write(f"upazila {code} failed: {exc}")
                continue
            for dataset, rows in result.items():
                writers[dataset].append_rows(rows)

    print(f"Done. Wrote {agro_csv}, {edaphic_csv} and {map_unit_csv}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape crop-zoning data from czis.cropzoning.gov.bd")
    parser.add_argument("--out-dir", default="data", help="Directory to write CSV output to")
    parser.add_argument("--workers", type=int, default=8, help="Number of concurrent requests")
    parser.add_argument("--no-resume", action="store_true", help="Ignore existing output and start fresh")
    args = parser.parse_args()
    run(out_dir=args.out_dir, workers=args.workers, resume=not args.no_resume)


if __name__ == "__main__":
    main()
