# BAMIS Crop Weather Calendars

Scraped from the [Bangladesh Agrometeorological Information System (BAMIS)](https://www.bamis.gov.bd/en/calendar/)
crop weather calendar section. Regenerate with:

```
conda run -n ML python -m bamis_scraper.scrape --out-dir data/bamis
```

This is a **separate dataset and codebase from the CZIS scraper** (`czis_scraper/`, output in
`data/`) — different source site, different data shape (PDF calendars vs JSON API), kept apart
so the two don't get mixed up.

## Files

Output is JSONL (one JSON object per line) so it can be streamed straight into a DB
(`mongoimport --file calendars.jsonl`, line-by-line ingestion, etc.) rather than loaded as one
big JSON document.

| File | Description |
|---|---|
| `crops.jsonl` | 34 crops: `{crop_id, crop_name}` |
| `regions.jsonl` | Agro-met regions per crop: `{crop_id, region_id, region_name}` — each region covers a cluster of districts (e.g. "Bogura Region" = Bogura, Joypurhat, Pabna, Sirajganj) |
| `calendars.jsonl` | One record per (crop, region, language): `{crop_id, crop_name, region_id, region_name, lang, pdf_url, pdf_path, text}` — `text` is the full extracted PDF text embedded directly in the record |
| `pdfs/{crop_id}_{region_id}_{lang}.pdf` | Original calendar PDF as published (kept on disk since binaries can't live in JSON; `pdf_path` in `calendars.jsonl` points here) |
| `text/{crop_id}_{region_id}_{lang}.txt` | Same text as the `text` field, also kept as standalone files |

**Only English (`lang: "en"`) is scraped by default.** Bangla PDFs were dropped per current
preference; the scraper still supports both — pass `--langs en,bn` to include Bangla again. No
code changes needed if that changes later.

## Why PDFs instead of a JSON/HTML table

Unlike CZIS, BAMIS's "crop weather calendar" data isn't served as a table or API response — each
crop/region combination is a **published PDF** embedded in the page via `<iframe>`. Each PDF is a
genuine digital document (not a scanned image), so text and tables extract cleanly. Content
includes: weekly rainfall/temperature/humidity/sunshine/wind normals, crop growth-stage timeline,
favorable weather windows per stage, pest/disease risk conditions, and weather-warning thresholds.

## Gotcha this scraper works around

The site embeds both language versions of a calendar PDF in one page load via two buttons
(`#lan1`/`#lan2`), but **which button points to the Bangla vs English PDF depends on the
session's current language-cookie state** — not a fixed mapping. Trusting button IDs would
silently mislabel `bn`/`en` under a threaded scraper that also visits `/en/...` catalog pages.
Instead, `bamis_scraper/pdf_store.py` downloads both PDFs and detects language directly from the
extracted text (presence of Bengali Unicode characters), which is reliable regardless of session
state.

## Not yet done: structured table parsing

The `text` field is raw extracted text, not tidy per-week fields. `pdfplumber`'s table extraction on
these PDFs returns merged/irregular cells (inconsistent column spans per crop), so turning the
weekly weather-normals table into clean structured fields would need custom per-table parsing —
left as a follow-up if needed.
