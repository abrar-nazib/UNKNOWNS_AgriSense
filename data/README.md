# CZIS Crop Zoning Data (BARC)

Scraped from the [Crop Zoning Information System](https://czis.cropzoning.gov.bd) (Bangladesh
Agricultural Research Council). Regenerate with:

```
conda run -n ML python -m czis_scraper.scrape --out-dir data
```

## Files

| File | Rows | Description |
|---|---|---|
| `upazilas.csv` | 497 | Division → District → Upazila hierarchy with codes and EN/BN names |
| `agro_climatic.csv` | ~2,590 | Per upazila: Pre-Kharif Transition Period, Kharif/Rabi Growing Period, Cool Winter Zone, Hot Summer Zone |
| `edaphic.csv` | ~12,290 | Per upazila: land type, soil texture, consistency, drainage, reaction (pH), moisture, salinity, water recession, relief |
| `map_units.csv` | ~5,880 | Per upazila: "Others" tab — land-cover map units (agri land sub-units, settlement, river, waterbody, etc.) |
| `edaphic_definitions.csv` | 47 | **Static** — the legend/definition text shown under each edaphic tab on the site (e.g. what "High land" or "Firm" consistency means) |
| `agro_climatic_data_source.txt` | 1 | **Static** — data-source credit shown under the Agro-Climatic tab |

`edaphic_definitions.csv` and `agro_climatic_data_source.txt` are fixed legend text embedded in
the site's frontend, not per-upazila data — they don't change per request and are written once
without hitting the network.

## Known gaps

17 upazilas (mostly riverine/haor areas, e.g. Narayanganj Sadar, Derai in Sunamganj) return no
edaphic survey data from the source site itself — not a scraper bug, the government dataset just
has no soil survey there. See `czis_scraper/scrape.py` output for the current list on each run.

## Joining the data

`upazila_code` in `agro_climatic.csv`, `edaphic.csv`, and `map_units.csv` matches `upazila_code`
in `upazilas.csv`. Join `edaphic.csv.type` against `edaphic_definitions.csv.type` +
`edaphic.csv.category` against `edaphic_definitions.csv.category` to attach the human-readable
definition to each row.
