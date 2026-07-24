# AgriSense AI — Project Guide

> Bdapps Agentic AI Hackathon (IUT 12th ICT Fest). Full brief:
> [docs/Agentic_AI_Hackathon_Final_Question.pdf](docs/Agentic_AI_Hackathon_Final_Question.pdf).
> **Hard deadline: hacking ends 25 July 2026, 09:00.** On-time = final commit
> pushed before the cutoff. Repo naming convention `TeamName_AgriSense` — ours is
> `UNKNOWNS_AgriSense`.

## The mission

Build an **agent, not a chatbot**: an autonomous agricultural advisor that takes a
smallholder farmer from an empty field to a **costed, weather-aware season plan**,
and keeps advising through harvest. It must hold a conversation to learn the farm,
pull real external data, chain multiple dependent steps toward a goal, remember
context across turns/sessions, and explain every recommendation in terms of the
inputs behind it ("apply 45 kg/acre urea in 3 days *because* soil is sandy, rice is
vegetative, and no rain is forecast" — not "apply urea").

Five judged agentic behaviors: **tool use, multi-step planning, handling missing
information, memory, explainability.**

## Scope discipline (read before building)

The single biggest way teams lose is half-building many features. **Ship Tier 0
end-to-end first; add a tier only when the layer beneath it works.** A payment demo
whose crop advice ignores the weather it just fetched will be noticed.

### Tier 0 — Core (REQUIRED). Single path: short conversation → grounded, explained, costed season plan for one farm.

| # | Capability | Done when | Status |
|---|---|---|---|
| 1 | Conversational intake | Collects ≥ location, farm size, soil type, water availability, budget, target season; asks targeted follow-ups only for missing fields | ✅ DONE (Task 2 + soil) — SIX MANDATORY slots (location, farm_size, **soil_type**, water, budget, season); crop advice is HARD-GATED until all present. Soil auto-fills mechanically from the bundled CZIS edaphic survey (480 upazilas, [backend/app/data/bd_soil.json](backend/app/data/bd_soil.json), accessors [backend/app/soil.py](backend/app/soil.py)) as a marked `survey_default_confirm_with_farmer`; farmer statements override and survive moves; unsurveyed upazila → default cleared, `get_soil_context` returns SOIL_UNKNOWN → agent must ask. Multi-farm: facts apply to the ACTIVE farm; different/new field → list/select/create_farm (create_farm now geo-resolves + soil-prefills); new farm = full six-field intake before advice |
| 2 | Live weather grounding | Calls a **real** weather API by location; uses actual rainfall/temp, no invented forecasts | ✅ DONE (Task 1) — `get_weather` tool → Open-Meteo (keyless), 16-day daily incl. ET0, geocode w/ bundled-centroid fallback, WEATHER_UNAVAILABLE on outage (never invents) |
| 3 | Crop recommendation | Ranks ≥3 candidate crops w/ suitability, water need, risk, rough profit | ❌ TODO (Task 5) |
| 4 | Season plan | Dated calendar: sowing window, fertilizer timing, irrigation, weed/pest checkpoints, harvest | ❌ TODO (Task 6) |
| 5 | Financial projection | Itemized cost + yield, revenue, net profit, ROI, break-even; internally consistent (change input → outputs change) | ✅ DONE (Task 7) — standalone `calculate_financials` tool (advisor + recommender), pure-`Decimal` engine [backend/app/engines/finance.py](backend/app/engines/finance.py): itemized fertilizer cost (REAL, live CZIS dose x seeded Tk/kg — skips "or"-alternative rows) + seeded seed/labor/irrigation/pesticide costs; low/base/high yield×price → revenue/profit/ROI; break-even yield & price. Seeded reference for **68 common BD crops** (cereals/oilseeds/pulses/tubers/cash crops/spices/vegetables — perennial/orchard crops out of scope) in [backend/app/data/finance_reference.json](backend/app/data/finance_reference.json)/[backend/app/finance_ref.py](backend/app/finance_ref.py), explicitly labeled `seeded_demo_value` (no live BD price feed exists — DAM's API 500s, PLAN.md D4) pending a real feed; a farmer's own stated yield/price always overrides (`farmer_estimate`, also serves what-if questions). Invariants gold-tested: itemized costs sum exactly to total, profit ≡ revenue − cost every scenario, ROI sign matches profit sign, doubling area doubles cost/revenue/profit but leaves ROI% unchanged |
| 6 | Explained reasoning | Every recommendation names the specific farm inputs + retrieved data it rests on | ⚠️ partial (prompt enforces naming inputs; weather cites real values; full grounding lands with Tasks 3-7) |
| 7 | Knowledge base + RAG | Agronomic data (extension manuals, fertilizer/crop/soil refs) ingested into a KB; agent retrieves; crop/fertilizer/plan advice grounded in retrieval, not model recall | ✅ DONE (Task 4) — `backend/app/rag/` (recursive chunker w/ FRG page tracking, pgvector `knowledge_chunks` 1536-dim), embeddings via **OpenRouter** `openai/text-embedding-3-small` (same key as chat; provider switch in `llm.py`), `search_knowledge_base` tool on advisor + recommender (English query, `<retrieved_document>` untrusted delimiters, top-5). FULL FRG 2024 corpus ingested: 287 chunks from [backend/app/data/kb_corpus/frg2024.md](backend/app/data/kb_corpus/frg2024.md) (Rahi's OCR pipeline, pages 10-239 incl. tesseract'd AEZ tables). Committed vector backup [backend/app/data/kb_seed/](backend/app/data/kb_seed/) (`kb_chunks.jsonl` + row-aligned `kb_embeddings.npy`) — restore on any fresh db with `python -m scripts.seed_rag_data` (zero API calls); re-ingest only after corpus edits (`scripts.ingest_kb` then `scripts.backup_kb`). Verified live: urea-split question → KB chip → FRG 2024 pp. 61/63/87 cited answer |
| 8 | Visible agent trace | UI exposes every tool call, params sent, raw values returned | ✅ DONE (tool-trace chips + `message_update` frames) |

### Tier 1 — Advanced (differentiators)
Persistent memory across sessions (✅ infra done via pgvector), proactive
weather-triggered advice, fertilizer/irrigation scheduler, pest/disease risk,
scenario simulation ("what if rainfall drops 30%?" → revised numbers).

### Tier 2 — Bonus (only after Tier 0 solid)
Marketplace/supplier comparison (mock catalog OK), market price intelligence
(sell/store/wait), leaf-photo disease detection, **bdapps CaaS Payment Gateway**
(sandbox — docs: https://dev.bdapps.com/API_Documentation/bdapps_tap_api.html),
Bengali/voice interaction.

### Judging (100 pts)
Agentic behavior 20 · Scope & execution 15 · Accuracy & practicality 20 ·
Knowledge base 12 · bdapps Payment 10 · Explainability 10 · Tech implementation 8 ·
Innovation 5. **"Don't spend too much time on UI/UX."** Priority = a stable Tier 0
that runs end-to-end in a 4-minute demo.

## What is built now

- **Auth**: **phone number is the identity** (unique login credential; no email —
  rural farmers have phones). `username` is a non-unique display name. Registration
  captures the farm **address with CZIS/BBS geocodes** down to the **union**
  (OPTIONAL — some upazilas list none; a non-empty union_code is validated
  server-side against the bundled gazetteer) → union centroid pins the farm to
  exact lat/lon, else the upazila centroid does. JWT register/login/me +
  refresh with rotation, jti blacklisting, reuse detection, logout blacklist.
  ([backend/app/routers/auth.py](backend/app/routers/auth.py), [backend/app/security.py](backend/app/security.py), [backend/app/schemas.py](backend/app/schemas.py))
- **Chat**: SSE streaming, user-scoped sessions/messages, reliable per-prompt agent trace display.
  Every completed final reply has a persisted `Thought for …` trace, even when it used no tools;
  tool-using turns aggregate native tool-step rows onto that final reply.
  ([backend/app/routers/chat.py](backend/app/routers/chat.py), [backend/app/agent/runner.py](backend/app/agent/runner.py))
- **Agent**: **multi-node specialist workflow** (PLAN.md D1 rev 2):
  `classify` (flash-lite + keyword fallback; heuristic-only under TESTING) routes
  each turn to a specialist — `intake` (slot-filling, farm+soil tools),
  `advisor` (general/weather/fertilizer, full toolset), `recommender`
  (dedicated crop-choice node: profile gate -> soil survey -> CZIS
  catalog/varieties -> ranked, input-named shortlist; Task 5's deterministic
  ranker plugs in here) — all sharing ONE ToolNode that returns control to
  `state.active_agent`. `state.reply_language` is refreshed by classify from
  EVERY user message (Bengali script/Banglish->bengali, else english); each
  node appends the language directive LAST (recency-authoritative), and the
  routing progress frame surfaces it (`specialist: X · reply: bengali`). **Per-node LLMs** via
  `build_chat_model(model)` (`OPENROUTER_MODEL` = gemini-2.5-flash for
  specialists, `OPENROUTER_MODEL_LITE` = flash-lite for routing only — lite was
  tested and rejected for extraction). Still NO interrupt()/checkpointer/Send;
  trace chips + frozen SSE contract unchanged; routing surfaces as a `progress`
  frame. Tier 0 planning lands as a future `planner` node.
  ([backend/app/agent/graph.py](backend/app/agent/graph.py), [backend/app/agent/state.py](backend/app/agent/state.py), [backend/app/agent/tools.py](backend/app/agent/tools.py), [backend/app/agent/runner.py](backend/app/agent/runner.py), [backend/app/agent/messages.py](backend/app/agent/messages.py))
- **BD admin gazetteer**: [backend/app/data/bd_admin.json](backend/app/data/bd_admin.json)
  (1.7MB, committed) — full division>district>upazila>**union** hierarchy (8/64/
  497/7,761) harvested from CZIS `getAdminByCode.php` + centroids joined from
  OCHA COD-AB (pcode == BBS geocode; 5,160 union points). Provenance + rebuild
  scripts: [scripts/data_harvest/](scripts/data_harvest/). Accessors in
  [backend/app/geo.py](backend/app/geo.py) (`resolve_coords` w/ union→upazila→district fallback,
  `find_place`/`find_upazila_by_name`/`find_union_by_name`, `union_valid`).
  Public dropdown endpoint `GET /api/geo/unions/{upazila_code}`
  ([backend/app/routers/geo.py](backend/app/routers/geo.py)).
- **CZIS crop grounding (Task 3)**: [backend/app/adapters/czis.py](backend/app/adapters/czis.py) — live
  BARC Crop Zoning endpoints (un-authed, **point-based lon/lat**, regex parsers,
  no bs4 dep). `list_crops` (bundled 129-crop catalog
  [backend/app/data/czis_crops.json](backend/app/data/czis_crops.json)), `get_varieties` (yield/duration),
  `get_crop_context` (variety **ids** at a point), `get_fertilizer_recommendation`
  (CZIS server-computed Urea/TSP/DAP/MoP/Gypsum/Zinc doses — relayed verbatim,
  never recomputed). `CzisError`/`CZIS_UNAVAILABLE` → fall back to FRG KB.
  Advisor tools `czis_list_crops/czis_crop_varieties/czis_crop_context/
  czis_fertilizer_recommendation` default to the active farm's coordinates.
- **Cropping-pattern economics**: [backend/app/data/bd_cropping_patterns.json](backend/app/data/bd_cropping_patterns.json)
  — recorded per-upazila cropping patterns from CZIS `/croppingpattern/{code}`
  (rabi/kharif-1/kharif-2 rotation + **BCR** over variable/total cost + **gross
  margin Tk/decimal**). Accessors in [backend/app/patterns.py](backend/app/patterns.py); agent tool
  `get_cropping_patterns` (advisor + recommender) serves the active farm's
  upazila sorted most-profitable-first, PATTERNS_UNKNOWN sentinel when
  uncovered. THE grounding source for "rough profit" claims —
  `gm_tk_per_decimal x area_decimal` via the calculator tool, never invented.
- **Financial projection (Task 7)**: `calculate_financials` tool (advisor +
  recommender) → pure-`Decimal` engine [backend/app/engines/finance.py](backend/app/engines/finance.py). Fertilizer
  cost is REAL when `crop_id`+`variety_id` are given (live CZIS dose x seeded
  Tk/kg, skipping "or"-alternative rows to avoid double-counting); seed/labor/
  irrigation/pesticide costs and the yield/price used for revenue come from
  [backend/app/data/finance_reference.json](backend/app/data/finance_reference.json) (68 common BD crops, `seeded_demo_value`
  — no live BD price feed exists yet, DAM's API 500s per PLAN.md D4) via
  [backend/app/finance_ref.py](backend/app/finance_ref.py). Every field is source-labeled; a farmer's own stated
  yield/price always overrides the seeded ones (`farmer_estimate` — also the
  what-if mechanism). Returns itemized costs, low/base/high revenue/profit/
  ROI, break-even yield & price; FINANCE_REFERENCE_UNKNOWN sentinel for
  uncovered (perennial/orchard) crops — never invents numbers.
- **Weather (Task 1)**: `get_weather` tool → [backend/app/adapters/weather.py](backend/app/adapters/weather.py)
  (Open-Meteo, keyless, 16-day max, ET0, retry + WEATHER_UNAVAILABLE sentinel,
  evidence metadata). **Coordinates-first**: default = the active farm's stored
  lat/lon (union centroid from registration — no geocoding at all,
  `geocode_source: farm_profile`); named admin places resolve offline via the
  gazetteer; the flaky live geocoder only runs for non-admin place names; the
  model can also pass explicit latitude/longitude. Farm location edits re-resolve
  codes + coords from the gazetteer in `update_farm_profile`
  (`_re_resolve_farm_geo`).
- **Farm profiles + intake (Task 2)**: `farms` table (farm-level location — one
  user, many farms; registration only prefills). Tools: `get_farm_profile`
  (reports `missing_required_fields`: location, farm_size, water_availability,
  budget, season), `update_farm_profile` (explicit facts only; deterministic area
  conversion via [backend/app/engines/units.py](backend/app/engines/units.py) — bigha/kani need farmer-confirmed
  local factor else marked ASSUMED; plausibility warnings), `list/select/create_farm`.
  All queries scoped to the authenticated user id — never model-supplied.
- **Deterministic engines** live in [backend/app/engines/](backend/app/engines/) (units done; crop
  ranker/fertilizer/calendar/finance land in Tasks 5-7). Core rule: LLM never
  computes farmer-facing numbers.
- **Memory**: long-term semantic recall via pgvector + rolling per-session summary,
  PLUS post-turn **automatic extraction** (PR #8): flash-lite pulls durable personal
  facts from every completed turn (no tool call needed), dedups by embedding
  distance (<0.15), never breaks the reply (best-effort, TESTING-skipped). Farmer
  identity (account username) is injected as a system message every session.
  ([backend/app/agent/memory.py](backend/app/agent/memory.py)) Farm facts belong in the farm profile, not memory.
- **RAG KB (Task 4)**: [backend/app/rag/](backend/app/rag/) — `chunker.py` (recursive splitter,
  keeps FRG `<!-- Page N -->` page ranges), `store.py` (idempotent per-source
  ingest + cosine top-k over `knowledge_chunks`, 1536-dim). Embeddings:
  OpenAI `text-embedding-3-small` via `build_kb_embeddings()` (provider switch
  `KB_EMBEDDINGS_PROVIDER`; tests force `fake`; memory table stays 768-dim —
  separate concerns). Default provider is **openrouter** — routes
  `KB_EMBED_MODEL=openai/text-embedding-3-small` through the existing
  `OPENROUTER_API_KEY` (verified live; raw-string inputs, no tiktoken
  pre-tokenizing). Tool `search_knowledge_base(query_en, crop?)` wraps hits
  in `<retrieved_document>` blocks (untrusted; prompt forbids obeying/quoting
  doses as final numbers); registered on advisor AND recommender (step 5b of
  its directive). Corpus: [backend/app/data/kb_corpus/frg2024.md](backend/app/data/kb_corpus/frg2024.md)
  (Rahi's `frg_ocr_pipeline.py` output — embedded text + tesseract OCR,
  pages 10-239) → 287 chunks. **Seeding a fresh db**: `docker compose exec
  backend python -m scripts.seed_rag_data` restores from the committed
  backup ([backend/app/data/kb_seed/](backend/app/data/kb_seed/): `kb_chunks.jsonl` + row-aligned
  `kb_embeddings.npy`) with zero embedding calls. Only after corpus edits:
  `python -m scripts.ingest_kb app/data/kb_corpus/frg2024.md --source "FRG
  2024"` then `python -m scripts.backup_kb` (refresh + commit the seed).
- **Frontend**: Next.js login/register/chat, agri-green theme, streaming + tool
  chips. ([frontend/src/](frontend/src/)) Gotcha fixed in `0b31359`: never key ChatColumn by
  session id and never abort the stream on the session-frame echo — that killed
  the first reply of every new chat.

## Where to build the remaining Tier 0 (extension points)

- **THE ROADMAP is [docs/PLAN.md](docs/PLAN.md)** — locked architecture decisions
  (D1-D5), verified data-source matrix, and the incremental Task 1→10 sequence
  (Task N only starts when Task N-1 is solid; Tasks 1-4 shipped). Next: Task 5
  crop ranker → Task 6 season plan →
  Task 7 finance (= Tier 0 complete checkpoint) → 8 polish → 9 Tier 1 → 10 Tier 2.
- **New agent tools** (CZIS, KB retrieval, ranking, planning, finance) → add
  `@tool`/factory functions in [backend/app/agent/tools.py](backend/app/agent/tools.py); register in the
  runner's tool list. Streaming + trace UI handle new tools automatically — **no
  frontend change needed** for a tool to appear as a chip.
- **External HTTP sources** → adapter module in [backend/app/adapters/](backend/app/adapters/)
  (injectable httpx client for offline MockTransport tests; evidence metadata;
  cached-snapshot fallback for .gov.bd flakiness). CZIS endpoints are documented
  in PLAN.md D4 (plain HTTP, no auth, no Playwright).
- **Deterministic math** → pure functions in [backend/app/engines/](backend/app/engines/) with
  gold-number unit tests; tools are thin wrappers.
- **RAG knowledge base** → ✅ built (see above). Add corpora via
  `scripts/ingest_kb.py` with a new `--source`; query in ENGLISH (cross-lingual
  Bengali→English retrieval is weak — PLAN.md D3); structured fertilizer tables
  still go to JSON, never RAG (numbers are computed).
- **Emit progress** from long tools via `get_stream_writer()` (see `_emit` in
  tools.py) → surfaces as `progress` SSE frames in the working indicator.
- The API + SSE contract is **frozen** in [docs/API_CONTRACT.md](docs/API_CONTRACT.md); honor it so the
  frontend keeps working.

## Key design docs

- [docs/PLAN.md](docs/PLAN.md) — **the implementation roadmap** (see above).
- [docs/INSIGHTS.md](docs/INSIGHTS.md) — original architecture steer: LLM gathers
  info + explains; **deterministic services** compute. Its orchestration machinery
  (interrupt/checkpointer/Send/scheduler) was **dropped** after gap analysis —
  PLAN.md D1 records why; keep its evidence-discipline, source-precedence and
  fertilizer-mode ideas.
- [docs/EXAMPLE_FLOW.md](docs/EXAMPLE_FLOW.md) — 30 Bangla multi-turn test
  scenarios w/ expected traces + failure conditions; the behavioral spec.
- [docs/FRG_PDF_EXTRACTION.md](docs/FRG_PDF_EXTRACTION.md) — FRG 2024 PDF anatomy:
  pdftotext works for the 5 demo-crop tables + RAG corpus; AEZ 25/26 pages are
  image-only (transcribe by hand); no OCR blocker.
- [docs/RESEARCH_crop_disease_models.md](docs/RESEARCH_crop_disease_models.md) —
  parked Tier 2 leaf-photo disease detection (off-the-shelf models + integration).

## Dev commands

```bash
cp .env.example .env          # set JWT_SECRET_KEY + OPENROUTER_API_KEY
docker compose up --build     # db (pgvector) + backend + frontend
docker compose logs -f backend
docker compose down           # stop
docker compose down -v && docker compose up -d --build   # full reset (wipes db)
```

- **Migrations = Alembic** (schema is Alembic-owned; startup runs `alembic upgrade
  head` via `entrypoint.sh`, no more `create_all`). After changing a DB model:
  `alembic revision --autogenerate -m "msg"` → review → `alembic upgrade head`
  (or `make makemigrations m="msg"` / `make migrate` in `backend/`). **No db nuke
  needed for schema changes anymore** — nuke only to clear data.
- **Tests** (regression guard, run before/after changes): from `backend/`,
  `docker compose exec backend sh -c "pip install -r requirements-dev.txt && \
  TEST_DATABASE_URL=postgresql+asyncpg://argi:argi_dev_password@db:5432/argi_test pytest -q"`
  (or `make test`). PLACEHOLDER_TEST_COUNT tests: unit (security/phone/tools/
  weather adapter/KB chunker/czis adapter/finance engine/geo gazetteer/unit
  conversion), integration (auth rotation/blacklist, chat ownership, farm tools +
  cross-user isolation), streaming (SSE tool_trace→message_update→done, weather
  chip, multi-turn intake via the turn-sequence fake in `tests/fakes.py`). LLM +
  HTTP are faked — no network. Isolated against a separate `argi_test` db.
  Realtime transport is **SSE, not WebSocket**. Add tests with any new feature.
  NOTE: the container has no source volume mount — `docker compose up -d --build
  backend` (or `docker cp` for a quick single file) before re-running tests.
- Frontend trace display aggregates native tool-step rows onto the final answer
  per user turn (`frontend/src/lib/chatTurns.ts`). Live SSE rows must win stale
  persisted query rows, and stream frames are written through to React Query.
- Frontend http://localhost:3000 · Backend http://localhost:8080 (docs `/docs`) ·
  Postgres localhost:5433. (Host ports 8080/5433 avoid local clashes; container
  ports are 8000/5432. `NEXT_PUBLIC_API_URL` in `.env` is baked into the frontend at
  build time — rebuild the frontend after changing it.)
- Quick backend smoke test: register (username + **phone** + password1/2 + address
  fields) → login by **phone** → `POST /api/chat/stream` with
  `Accept: text/event-stream, */*` and a `Bearer` access token.

## Conventions & constraints

- **Real vs mock**: the submission README must clearly state which data is
  real/live and which is generated/mock. Weather + payment should be genuinely
  called (sandbox OK); a seeded supplier/price catalog is explicitly allowed.
- **Grounding over invention**: numbers in the plan must come from a real tool call
  or the KB, and be traceable in the visible trace — never model imagination.
- **Financial math must be internally consistent**: judges will change an input and
  check the outputs change correctly. Keep the calc deterministic (do it in a tool,
  not free-text from the LLM).
- **Secrets**: `.env` is gitignored (holds the real OpenRouter key); `.env.example`
  stays blank. Teams provide their own API keys.
- **GitHub auth is SSH** (`git@github.com:abrar-nazib/UNKNOWNS_AgriSense.git`); never
  switch origin to HTTPS on this machine.
- **All application code must be written during the 24h window** — scaffolding is
  fine, a pre-existing AgriSense codebase is not.
- Backend: async SQLAlchemy 2.0, match existing file layout. Frontend: don't
  over-invest in UI polish (low judged weight) — spend the time on Tier 0 substance.
