# Tier 2 Market Researcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a traceable LangGraph market-researcher specialist that compares seeded input suppliers and produces disclosed crop-market sell/store/wait guidance.

**Architecture:** A 22-merchant reviewed JSON source and the existing 129-crop CZIS catalog seed three relational tables idempotently. A pure market engine reads those rows, computes Haversine distance, transparent supplier scores, price-history statistics, and market actions. LangChain tools adapt the engine to the active farm, with an isolated Bangladesh DuckDuckGo reference fallback when structured seeded data is absent.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async/PostgreSQL, Alembic, LangChain/LangGraph, existing DuckDuckGo research adapter, pytest/pytest-asyncio.

## Global Constraints

- Derive crop identities and seasons only from `backend/app/data/czis_crops.json` (129 rows); do not create a second crop catalog.
- Seed exactly 22 merchant profiles and label every output `seeded_demo_market_data`; never call its values live/current or guaranteed.
- Keep farmgate/wholesale and retail price bases distinct; only farmgate/wholesale may drive crop-market actions.
- Supplier score is `0.40 price + 0.25 distance + 0.20 delivery + 0.10 rating + 0.05 stock fit`; disclose every component, every supplier's kilometre distance, and the nearest eligible supplier.
- Use straight-line Haversine distance and call delivery a heuristic estimate.
- External Bangladesh web results are URL-cited, `unverified_external_reference`, and cannot affect deterministic ranking or alone determine `SELL_NOW`, `STORE`, or `WAIT`.
- Preserve existing frontend/SSE contracts and do not let market research mutate finance assumptions.
- Do not commit or push unless Sefayet explicitly says `yes, push now`.

---

## File Structure

- Create `backend/app/data/market_merchants.json` — reviewed metadata and input-offer source for exactly 22 merchants.
- Create `backend/app/engines/market_research.py` — pure data validation, seed-row generation, distance, scoring, price aggregates, and action decisions.
- Create `backend/app/market_repository.py` — async SQLAlchemy persistence/query boundary and idempotent seeding.
- Create `backend/migrations/versions/0007_market_research.py` — production schema migration after current merge head `0006_merge_kb_bdapps`.
- Modify `backend/app/models.py` — `MarketMerchant`, `MarketInputOffer`, and `MarketCropQuote` ORM models/indexes.
- Modify `backend/app/agent/tools.py` — market tools plus bounded Bangladesh fallback adapter wrapper.
- Modify `backend/app/agent/runner.py` — construct and expose the market tools only to `market_researcher`.
- Modify `backend/app/agent/graph.py` — add the specialist, route intents, and enforce its response policy.
- Modify `backend/tests/fakes.py` — deterministic market-researcher scripted turns.
- Create `backend/tests/unit/test_market_research.py` — pure-engine, seed, and scoring tests.
- Create `backend/tests/integration/test_market_research.py` — database/tool behaviour tests.
- Modify `backend/tests/unit/test_graph_routing.py`, `backend/tests/unit/test_tools.py`, and `backend/tests/streaming/test_stream_agent.py` — routing, exposure, and trace regression coverage.
- Modify `README.md`, `docs/PLAN.md`, root `PLAN.md`, and root `HANDOFF.md` — explicit real-vs-mock disclosure, progress, and resume state.

## Task 1: Define the Reviewed Merchant Seed and Persistence Schema

**Files:**
- Create: `backend/app/data/market_merchants.json`
- Modify: `backend/app/models.py`
- Create: `backend/migrations/versions/0007_market_research.py`
- Test: `backend/tests/unit/test_market_research.py`

**Interfaces:**
- Produces `MarketMerchant`, `MarketInputOffer`, and `MarketCropQuote` ORM models.
- Produces source document fields `merchant_key`, `role`, `latitude`, `longitude`, `rating`, `base_delivery_days`, `service_radius_km`, and `input_offers`.
- Consumed by `seed_market_catalog(session)` in Task 2.

- [ ] **Step 1: Write failing schema/seed contract tests**

```python
def test_reviewed_seed_has_exactly_22_unique_bangladesh_merchants():
    seed = market_research.load_merchant_seed()
    assert len(seed["merchants"]) == 22
    assert len({row["merchant_key"] for row in seed["merchants"]}) == 22
    assert all(20.5 <= row["latitude"] <= 26.7 for row in seed["merchants"])
    assert all(88.0 <= row["longitude"] <= 92.8 for row in seed["merchants"])


def test_all_seeded_crop_quotes_reference_czis_catalog():
    catalog = {row["id"] for row in czis_mod.list_crops()}
    quotes = market_research.build_crop_quote_seed()
    assert {quote["crop_id"] for quote in quotes} <= catalog
    assert len({quote["crop_id"] for quote in quotes}) == 129
```

- [ ] **Step 2: Run the unit test to verify it fails**

Run: `docker compose exec -T backend pytest -q tests/unit/test_market_research.py`

Expected: FAIL because `market_research` and its seed source do not exist.

- [ ] **Step 3: Add source JSON and ORM models**

Create exactly 22 named merchant profiles across Bangladesh hubs (Rajshahi, Bogura, Rangpur, Dinajpur, Dhaka, Gazipur, Mymensingh, Jashore, Khulna, Barishal, Cumilla, and Chattogram). Include `input_supplier`, `crop_buyer`, and `hybrid` roles; at least three suppliers for each supported input key (`seed`, `urea`, `tsp`, `mop`, `irrigation_service`, `crop_protection`). Do not include crop prices in the JSON: Task 2 derives quote histories from the authoritative crop catalog.

```python
class MarketMerchant(Base):
    __tablename__ = "market_merchants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(24), index=True)
    district_name: Mapped[str] = mapped_column(String(80))
    upazila_name: Mapped[str] = mapped_column(String(80), default="")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    rating: Mapped[float] = mapped_column(Float)
    base_delivery_days: Mapped[int] = mapped_column(Integer)
    service_radius_km: Mapped[float] = mapped_column(Float)
    source_label: Mapped[str] = mapped_column(String(48), default="seeded_demo_market_data")


class MarketInputOffer(Base):
    __tablename__ = "market_input_offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("market_merchants.id", ondelete="CASCADE"), index=True)
    input_key: Mapped[str] = mapped_column(String(64), index=True)
    unit: Mapped[str] = mapped_column(String(24))
    unit_price_bdt: Mapped[float] = mapped_column(Float)
    available_quantity: Mapped[float] = mapped_column(Float)
    minimum_order_quantity: Mapped[float] = mapped_column(Float)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
```

Add `MarketCropQuote` with `merchant_id`, `crop_id`, `crop_name`, `quote_date`, `price_basis`, `price_per_kg_bdt`, `confidence`, and `source_label`; add indexes for `(crop_id, quote_date)` and `(merchant_id, quote_date)`. Write the matching Alembic upgrade/downgrade operations using the current migration head.

- [ ] **Step 4: Run unit schema/seed tests**

Run: `docker compose exec -T backend pytest -q tests/unit/test_market_research.py`

Expected: PASS for source validation; database tests remain pending until Task 2.

- [ ] **Step 5: Check migration and schema diff**

Run: `docker compose exec -T backend alembic upgrade head && docker compose exec -T backend python -m pytest -q tests/unit/test_market_research.py`

Expected: migration applies once; tests pass without changing existing tables.

- [ ] **Step 6: Commit only with explicit approval**

Do not commit unless Sefayet explicitly authorizes it.

## Task 2: Build Deterministic Seeding and Market-Research Engine

**Files:**
- Create: `backend/app/engines/market_research.py`
- Create: `backend/app/market_repository.py`
- Test: `backend/tests/unit/test_market_research.py`
- Test: `backend/tests/integration/test_market_research.py`

**Interfaces:**
- Consumes `MarketMerchant`, `MarketInputOffer`, `MarketCropQuote`, `czis_mod.list_crops()`, and an `AsyncSession`.
- Produces `seed_market_catalog(session) -> SeedResult`, `haversine_km(...) -> float`, `rank_supplier_offers(...) -> list[dict]`, and `analyze_price_history(...) -> dict`.
- Consumed by the agent tools in Task 3.

- [ ] **Step 1: Write failing engine tests**

```python
def test_haversine_distance_is_symmetric_and_zero_for_same_point():
    assert market_research.haversine_km(24.3745, 88.6042, 24.3745, 88.6042) == 0
    assert market_research.haversine_km(24.3745, 88.6042, 24.3636, 88.6241) == pytest.approx(2.35, abs=0.25)


def test_supplier_score_prefers_lower_delivered_cost_before_rating():
    ranked = market_research.rank_supplier_offers(
        offers=[cheap_far_offer, costly_near_offer], quantity=20, farm_lat=24.37, farm_lon=88.60
    )
    assert ranked[0]["merchant_key"] == "cheap-far"
    assert ranked[0]["score_components"]["price_weight"] == 0.40


def test_price_history_actions_cover_sell_store_wait():
    assert market_research.analyze_price_history(high_current_history)["action"] == "SELL_NOW"
    assert market_research.analyze_price_history(recovering_history)["action"] == "STORE"
    assert market_research.analyze_price_history(flat_history)["action"] == "WAIT"
```

- [ ] **Step 2: Run the engine test to verify it fails**

Run: `docker compose exec -T backend pytest -q tests/unit/test_market_research.py`

Expected: FAIL because the market engine APIs are undefined.

- [ ] **Step 3: Implement deterministic catalog seeding**

Implement `load_merchant_seed()` and `build_crop_quote_seed()` in the engine. `build_crop_quote_seed()` must load all 129 rows via `czis_mod.list_crops()`, derive a stable crop price band from crop name/category/season, assign each crop to two or three crop-buying/hybrid merchants using a stable crop ID modulo, and generate a fixed 60-day daily farmgate/wholesale history ending at `date.today()`. No random module or per-request time variation is allowed. Every generated row has `source_label="seeded_demo_market_data"` and a price basis of `farmgate` or `wholesale`.

Implement `seed_market_catalog(session)` in the repository:

```python
async def seed_market_catalog(session: AsyncSession) -> dict[str, int]:
    """Insert the reviewed 22-merchant catalog only when it is absent.

    Returns counts for merchants, input_offers, and crop_quotes. It must be
    safe to call on every tool invocation without duplicating rows.
    """
```

Use the merchant key as the idempotency boundary. Query helpers must call `seed_market_catalog()` before reading and return plain dictionaries, never ORM instances.

- [ ] **Step 4: Implement calculations and query boundaries**

Implement Haversine with Earth radius `6371.0088`; round display distance to one decimal only after ranking. Estimate delivery as `base_delivery_days + ceil(distance_km / 80)` capped at seven days. Normalize each candidate field across the matching pool before applying the approved score weights. Exclude out-of-stock, below-minimum, insufficient-quantity, unit-mismatched, and out-of-service-radius offers, returning structured exclusion counts.

`analyze_price_history()` must use the latest 7/30 days, range position, percent movement, volatility, and a bounded storage-cost/risk threshold. Return `WAIT` with `reason_code="INSUFFICIENT_HISTORY"` for fewer than 14 observations; expose values and rules used for every action.

- [ ] **Step 5: Write and run database integration tests**

```python
@pytest.mark.asyncio
async def test_seed_is_idempotent_and_has_129_crop_histories(db_session):
    first = await repo.seed_market_catalog(db_session)
    second = await repo.seed_market_catalog(db_session)
    assert first["merchants"] == 22
    assert second["merchants"] == 0
    assert await repo.count_distinct_quoted_crops(db_session) == 129
```

Run: `docker compose exec -T backend pytest -q tests/unit/test_market_research.py tests/integration/test_market_research.py`

Expected: PASS with the exact merchant/crop counts and deterministic rankings.

- [ ] **Step 6: Commit only with explicit approval**

Do not commit unless Sefayet explicitly authorizes it.

## Task 3: Expose the Two Market Tools and Bounded Bangladesh Fallback

**Files:**
- Modify: `backend/app/agent/tools.py`
- Test: `backend/tests/integration/test_market_research.py`
- Test: `backend/tests/unit/test_tools.py`

**Interfaces:**
- Consumes Task 2 repository functions and existing `research_mod.search_web()`.
- Produces `build_market_research_tools(user) -> list[BaseTool]` with tools named `find_input_suppliers` and `analyze_crop_market`.
- Consumed by Task 4 runner/graph wiring.

- [ ] **Step 1: Write failing tool payload tests**

```python
@pytest.mark.asyncio
async def test_find_input_suppliers_uses_active_farm_coordinates(db_session, user):
    tool = (build_market_research_tools(user))[0]
    payload = json.loads(await tool.ainvoke({"input_name": "urea", "quantity": 100, "unit": "kg"}))
    assert payload["status"] == "ok"
    assert payload["results"][0]["distance_km"] >= 0
    assert payload["nearest_eligible_supplier"]["merchant_key"] == payload["results"][0]["merchant_key"]
    assert payload["source_label"] == "seeded_demo_market_data"


@pytest.mark.asyncio
async def test_market_no_data_returns_bangladesh_reference_fallback(monkeypatch, db_session, user):
    monkeypatch.setattr(research_mod, "search_web", fake_bangladesh_search)
    tool = (build_market_research_tools(user))[1]
    payload = json.loads(await tool.ainvoke({"crop_name": "Unknown crop"}))
    assert payload["status"] == "NO_STRUCTURED_MARKET_DATA"
    assert payload["external_reference"]["source_label"] == "unverified_external_reference"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend pytest -q tests/integration/test_market_research.py tests/unit/test_tools.py`

Expected: FAIL because market tools do not exist.

- [ ] **Step 3: Add `build_market_research_tools`**

Match existing tool-builder closure patterns: obtain a short-lived `AsyncSessionLocal()` session per invocation, resolve the active farm with `_get_or_create_active_farm`, and emit progress through `_emit("market", ...)`.

`find_input_suppliers` accepts `input_name: str`, `quantity: float`, and `unit: str`. It resolves the active farm's explicit latitude/longitude first, then uses the existing stored address/upazila coordinate mapping when coordinates are absent. It returns `LOCATION_REQUIRED` only when neither source resolves a location, `NO_MATCHING_SUPPLIERS` plus a fallback if structured offers do not match, or `ok` with the top three candidates, each candidate's kilometre distance, `nearest_eligible_supplier`, and all disclosure fields.

`analyze_crop_market` accepts `crop_name: str` and `quantity_kg: float = 0`. It resolves aliases against the actual CZIS catalog, returns nearest buyer quotes/history/action, and includes `recommendation_disclaimer`. It never calls the finance engine or modifies farm state.

- [ ] **Step 4: Add the external fallback wrapper**

Implement a private async helper that builds English and Bangla query strings with the input/crop and the active farm district/upazila. Call existing `research_mod.search_web(query, max_results=3)` only after a no-data result. Keep only results whose URL/title/snippet has a Bangladesh signal (`.bd`, `Bangladesh`, or Bangla text), preserve `url`, `title`, `snippet`, and date when supplied, and return the `unverified_external_reference` label. Catch `ResearchError` and return a degraded structured payload, not a fabricated result.

- [ ] **Step 5: Run focused tools tests**

Run: `docker compose exec -T backend pytest -q tests/integration/test_market_research.py tests/unit/test_tools.py`

Expected: PASS; test output shows no network calls because fallback is mocked.

- [ ] **Step 6: Commit only with explicit approval**

Do not commit unless Sefayet explicitly authorizes it.

## Task 4: Add the Market Researcher LangGraph Specialist

**Files:**
- Modify: `backend/app/agent/graph.py`
- Modify: `backend/app/agent/runner.py`
- Modify: `backend/tests/unit/test_graph_routing.py`
- Modify: `backend/tests/unit/test_tools.py`
- Modify: `backend/tests/fakes.py`
- Modify: `backend/tests/streaming/test_stream_agent.py`

**Interfaces:**
- Consumes `build_market_research_tools(user)` and the two tool names from Task 3.
- Produces a `market_researcher` classifier target and its bounded tool group.
- Preserves the shared `ToolNode` and existing SSE trace events.

- [ ] **Step 1: Write failing routing/exposure tests**

```python
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Find suppliers for 100 kg urea near my farm", "market_researcher"),
        ("What is the current potato market price?", "market_researcher"),
        ("Should I sell my wheat now or store it?", "market_researcher"),
    ],
)
def test_market_queries_route_to_market_researcher(message, expected):
    assert graph.classify_heuristic(message) == expected
```

- [ ] **Step 2: Run routing tests to verify they fail**

Run: `docker compose exec -T backend pytest -q tests/unit/test_graph_routing.py tests/unit/test_tools.py`

Expected: FAIL because `market_researcher` is not an agent or tool group.

- [ ] **Step 3: Wire graph, classifier, runner, and prompt policy**

Add `market_researcher` to `AGENTS`, `_node_models()`, classifier prompt, deterministic keyword patterns, and runner tool groups. Route market terms before generic advisor fallback but after crop recommendation/season-plan/finance intents so existing bounded workflows retain precedence.

Give the node only `static_tools + farm_tools + market_tools`. Its directive must require the matching market tool, retain source labels, explain the score/action from returned values only, state the non-live/non-guarantee disclosure, and never invoke `calculate_crop_financials` or make payment/order promises.

Add fake streaming scripts that make a market tool call then emit a result explanation. Do not change graph edges: the existing shared `ToolNode` must return market calls to the active specialist and emit the normal trace.

- [ ] **Step 4: Add streamed trace regression test**

```python
@pytest.mark.asyncio
async def test_market_turn_persists_market_tool_trace(auth_client, monkeypatch):
    monkeypatch.setattr(graph_mod, "build_chat_model", make_fake_llm("market_supplier"))
    events = await stream_turn(auth_client, "Find urea suppliers for 100 kg")
    traces = {step["tool"] for event in events for step in event.get("tool_trace", [])}
    assert "find_input_suppliers" in traces
```

- [ ] **Step 5: Run graph and streaming tests**

Run: `docker compose exec -T backend pytest -q tests/unit/test_graph_routing.py tests/unit/test_tools.py tests/streaming/test_stream_agent.py`

Expected: PASS with unchanged non-market routing cases.

- [ ] **Step 6: Commit only with explicit approval**

Do not commit unless Sefayet explicitly authorizes it.

## Task 5: Verify Migration, Contracts, and Full Tier 2 Behaviour

**Files:**
- Test: `backend/tests/integration/test_market_research.py`
- Test: `backend/tests/streaming/test_stream_agent.py`
- Modify: `README.md`
- Modify: `docs/PLAN.md`
- Modify: `PLAN.md`
- Modify: `HANDOFF.md`

**Interfaces:**
- Consumes completed schema, engine, tools, and graph wiring.
- Produces proof that supplier and price intelligence are deterministic, disclosed, traceable, and isolated from finance.

- [ ] **Step 1: Write end-to-end behavioural assertions**

```python
@pytest.mark.asyncio
async def test_market_analysis_does_not_change_finance_assumptions(db_session, user):
    before = finance_mod.load_assumptions()
    payload = await invoke_crop_market_tool(user, "Wheat")
    after = finance_mod.load_assumptions()
    assert payload["source_label"] == "seeded_demo_market_data"
    assert before == after


@pytest.mark.asyncio
async def test_market_payload_discloses_mock_data_and_external_boundaries(db_session, user):
    payload = await invoke_supplier_tool(user, "urea", 100, "kg")
    assert payload["disclosure"]
    assert payload["results"][0]["source_label"] == "seeded_demo_market_data"
    assert "not live" in payload["disclosure"].lower()
```

- [ ] **Step 2: Run all focused Tier 2 tests**

Run: `docker compose exec -T backend pytest -q tests/unit/test_market_research.py tests/integration/test_market_research.py tests/unit/test_graph_routing.py tests/unit/test_tools.py tests/streaming/test_stream_agent.py`

Expected: PASS; coverage proves the 22/129 seed contract, tools, fallback, routing, and trace.

- [ ] **Step 3: Run migration and application health checks**

Run:

```bash
docker compose up -d --build
docker compose exec -T backend alembic current
python3 -c 'import urllib.request; r=urllib.request.urlopen("http://localhost:8080/docs", timeout=5); print(r.status)'
python3 -c 'import urllib.request; r=urllib.request.urlopen("http://localhost:3000", timeout=5); print(r.status)'
```

Expected: Alembic reports `0007_market_research`; backend docs and frontend both print `200`.

- [ ] **Step 4: Perform a manual tool-trace rehearsal**

Use an authenticated chat session with:

```text
Find the best suppliers for 100 kg of urea near my farm.
What is the current market price for potato, and should I sell now, store, or wait?
```

Expected: first trace shows `find_input_suppliers`; second shows `analyze_crop_market`; both answers disclose seeded values and expose score/action reasoning.

- [ ] **Step 5: Document the demo boundary and handoff**

Add README language that merchant offers and historical prices are seeded demo data derived from the 129-crop CZIS catalog, external fallback is unverified reference-only, and no live buying/selling/payment occurs. Update nested/root plans and handoff with final test totals, migration version, demo prompts, and any open limitations.

- [ ] **Step 6: Commit/push only with explicit approval**

Do not commit or push unless Sefayet explicitly authorizes it.
