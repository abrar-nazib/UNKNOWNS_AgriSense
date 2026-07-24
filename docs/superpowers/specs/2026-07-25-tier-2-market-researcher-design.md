# Tier 2 Market Researcher Design

## Goal

Deliver both Tier 2 requirements through one dedicated LangGraph `market_researcher` specialist:

1. Marketplace and supplier comparison for farm inputs.
2. Market-price intelligence with current and historical crop prices and a sell-now, store, or wait decision aid.

The feature uses realistic, deterministic mock data seeded from the bundled 129-crop CZIS catalog. It is a demo dataset, never a live market-price claim.

## Scope

The backend adds a market-researcher node and two deterministic tools:

- `find_input_suppliers(input_name, quantity, unit)`
- `analyze_crop_market(crop_name, quantity_kg=0)`

The frontend needs no new route or API contract. Existing streamed chat messages and tool-trace chips render the results.

## Architecture

`classify` routes supplier, input-cost, buyer, market-price, price-history, and sell/store/wait requests to `market_researcher`. The node has only market tools, static tools, and farm lookup tools. It does not use finance, crop-ranking, or pest-risk tools.

```text
CZIS crop catalog (129 crops)
  -> reviewed JSON seed source
  -> relational merchant, offer, and crop-quote tables
  -> market_researcher
  -> deterministic tool output + trace
  -> farmer-facing ranked answer with disclosure
```

Current finance projections retain their existing labelled demo assumptions unless the farmer supplies a price. Market tools must not silently overwrite financial assumptions.

## Dataset

### Seed source

Commit a reviewed JSON source under `backend/app/data/`. It derives crop identities and seasonality from `czis_crops.json`; it is not a second independent crop catalog. Startup/test seed logic transforms the source into database rows idempotently.

### Merchant network

Create exactly 22 Bangladesh merchant records. Each has a stable UUID/key, merchant name, district/upazila display location, latitude, longitude, role (`input_supplier`, `crop_buyer`, or `hybrid`), rating, base lead time, and service radius. Values must be internally plausible and deterministic.

### Input offers

Merchant input offers include common seed, fertilizer, irrigation, and crop-protection categories required by the existing focused crop-plan path. Each row contains normalized input key, display name, unit, unit price, available quantity, minimum order quantity, and stock status.

### Crop quotes

Buyer quotes only exist for crops the buyer supports. A quote has crop ID/name, market/buyer, quote date, farmgate or wholesale price basis, price per kg, confidence, and the required `seeded_demo_market_data` source label. Histories have bounded seasonal movement and controlled variation, not random per-request values.

## Supplier Comparison

The tool reads the active farm location, resolves its stored farm coordinates or the existing saved address/upazila coordinate mapping, searches matching in-stock offers, rejects unit and quantity mismatches, calculates Haversine distance in kilometres, and estimates delivery days from merchant base lead time plus distance. The farmer-facing response always identifies the nearest eligible supplier and reports each returned supplier's distance in kilometres.

Rank candidates by a normalized, deterministic score:

```text
0.40 delivered price + 0.25 distance + 0.20 delivery time +
0.10 rating + 0.05 stock fit
```

Return the top three plus the matching pool count. Each item exposes its score components, distance, estimated delivery, rating, quantity/stock context, and source label. Price is an item-price comparison only; no checkout, order placement, or payment flow is in scope.

## Crop Market Intelligence

The tool searches crop buyer quotes and history for the requested CZIS crop, favours farmgate/wholesale over retail, and computes latest price, seven- and thirty-day movement, range, volatility, and nearest buyer availability.

The deterministic decision result is one of:

- `SELL_NOW`: favourable current price relative to recent history or weak expected upside after bounded storage cost/risk.
- `STORE`: current price is below its recent range, the short-term trend is positive, and expected upside clears bounded storage cost/risk.
- `WAIT`: stable/uncertain market, insufficient expected upside, or insufficient data for sell/store confidence.

The result includes the explicit rules and inputs that produced it. It is a decision aid, never a forecast or price guarantee.

## No-Data Web Fallback

When the seeded database has no relevant local supplier or crop-market data, the node invokes a dedicated Bangladesh market web-fallback tool built on the existing bounded DuckDuckGo adapter. Queries use English and Bangla crop/input terms plus district/upazila context. Results must be Bangladesh-relevant, URL-cited, date-labelled when available, and marked `unverified_external_reference`.

External snippets are never parsed into a deterministic quote, mixed into the supplier score, or used as the sole basis of a sell/store/wait recommendation. If no trustworthy structured data exists, the tool asks the farmer to confirm a local quote instead.

## Safety and Presentation

- Every seeded field carries `seeded_demo_market_data` disclosure.
- Never call a seeded price current/live, and never promise future price movement.
- Keep farmgate/wholesale and retail bases distinct.
- Explain distance as straight-line estimate and delivery as heuristic estimate.
- Preserve external reference URLs in the existing tool trace.

## Error Handling

- Missing farm coordinates: first resolve the existing saved address/upazila mapping; only when neither source yields coordinates, return a structured location-required response and do not produce a distance ranking.
- Unknown crop/input: return normalized search suggestions from the catalog or supported input aliases.
- Quantity/unit mismatch: exclude incompatible offers and state why.
- No seeded results: return the fallback response plus disclosure.
- No sufficient crop history: return `WAIT` only as data-insufficient, without pretending a directional market signal.

## Verification

Unit tests cover seed integrity, exactly 22 merchants, crop references limited to the 129-CZIS catalog, Haversine distance, delivery estimates, supplier filtering/ranking/ties, historical-price aggregates, all three decision outcomes, and missing-data responses.

Integration and streaming tests cover classifier routing, market-tool availability, tool-trace events, active-farm coordinate use, fallback calls, source disclosures, and the guarantee that finance projections do not change from market-tool calls.

## Non-goals

- Live prices, live supplier inventory, payments, ordering, seller onboarding, or reviews submission.
- Routing distance, traffic-aware delivery estimates, and postal-geocoding.
- Claiming that external search snippets are verified Bangladesh market quotes.
