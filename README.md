# iut_cse_hackathon_team_unknowns

Scrapers for two Bangladeshi government agriculture data sources, built for farmer-facing tools.

## Summary

| | CZIS | BAMIS |
|---|---|---|
| Code | `czis_scraper/` | `bamis_scraper/` |
| Data | `data/` | `data/bamis/` |
| Source | [czis.cropzoning.gov.bd](https://czis.cropzoning.gov.bd) | [bamis.gov.bd](https://www.bamis.gov.bd/en/calendar/) |
| What | Soil/land/agro-climatic stats per upazila | Crop weather calendars (PDF) per crop/region |
| Format | JSON API → CSV | HTML + PDF → JSONL |
| Run | `python -m czis_scraper.scrape` | `python -m bamis_scraper.scrape` |

Both run in the `ML` conda env: `conda run -n ML python -m <package>.scrape`

## `czis_scraper/` — Crop Zoning Information System (BARC)

Soil and climate data for all 497 upazilas: land type, soil texture/consistency/drainage/
reaction/moisture/salinity/water-recession/relief, agro-climatic periods, and land-cover map units.

| File | What it does |
|---|---|
| `constants.py` | Base URL and the endpoint type keys (edaphic/agro-climatic categories) |
| `client.py` | HTTP session with retries |
| `admin.py` | Walks Division → District → Upazila to get every upazila code |
| `data.py` | Fetches the actual soil/climate/map-unit data for one upazila |
| `notes.py` | Static legend text (category definitions) scraped once from the site's frontend, not per-upazila |
| `scrape.py` | CLI entrypoint — orchestrates the above, writes CSVs to `data/`, resumable |

Output: `data/upazilas.csv`, `agro_climatic.csv`, `edaphic.csv`, `map_units.csv`,
`edaphic_definitions.csv`, `agro_climatic_data_source.txt`. Details in `data/README.md`.

## `bamis_scraper/` — Bangladesh Agrometeorological Information System

Crop weather calendars (weekly rainfall/temperature/humidity/wind normals, growth stages,
favorable conditions, pest risk, weather warnings) per crop × agro-met region, sourced as PDFs.

| File | What it does |
|---|---|
| `constants.py` | Base URL and calendar section path |
| `client.py` | HTTP session with retries |
| `catalog.py` | Lists all crops, then all regions per crop |
| `pdf_links.py` | Finds both language PDF links on a crop/region page |
| `pdf_store.py` | Downloads a PDF, extracts its text, and detects Bangla vs English from the actual text (button IDs on the site aren't a reliable language signal) |
| `scrape.py` | CLI entrypoint — orchestrates the above, writes JSONL to `data/bamis/`, resumable, `--langs en,bn` to control which languages to keep (default: English only) |

Output: `data/bamis/crops.jsonl`, `regions.jsonl`, `calendars.jsonl` (full PDF text embedded per
record — built for streaming into a DB), plus the raw `pdfs/`/`text/` files. Details in
`data/bamis/README.md`.

## Notes

- Both scrapers are resumable — re-running skips work already saved in the output files.
- `scrap.py` in the repo root is an old scratch file, unrelated to either package.
