# Task 6 — Dated Season Plan (Tier 0 #4)

**Status:** engine + tool shipped (this change). Deterministic, offline-safe.

## Goal
Turn an established farm profile into a **dated, source-cited calendar**: land
preparation → sowing/transplanting → fertilizer splits → irrigation → weeding →
pest checkpoints → harvest. Every date traceable in the Agent Trace + calendar UI.

## Architecture — bundled official calendar + live enrichment
1. **Bundled calendar data** (`app/data/bd_crop_calendar.json`) — DAE **BAMIS**
   crop-weather calendars + BARC **FRG 2024** snapshot. Per crop: official
   sowing/transplant window, default duration, ordered stages with day-offsets
   relative to the establishment event, `weather_sensitive` flags and agronomic notes.
   Source: `bamis.gov.bd` crop-weather calendars (regional sowing windows,
   growth stages, fertilizer/irrigation/pest timing, harvest durations).
2. **Deterministic engine** (`app/engines/season_plan.py`) — pure functions, no I/O.
   - Establishment date: farmer-provided date wins; otherwise the **earliest
     feasible day inside the current or next official window**, clearly labelled
     as an assumption (never silently invented).
   - Each stage date = establishment date + offset (`"duration"` / `"duration-N"`
     resolve against the crop duration; CZIS variety duration can override).
   - **Weather overlay:** for weather-sensitive tasks inside the 16-day horizon,
     heavy rain (≥10 mm) on the scheduled day defers irrigation or shifts
     fertilizer/sowing to the next dry day (<5 mm), recording the original date
     and the reason. Outside the horizon, calendar dates stand.
3. **Live enrichment (never blocks):** Open-Meteo 16-day forecast (rain overlay).
   On any outage the plan is still produced from bundled dates, labelled
   `weather_overlay: none`.
4. **Agent tool** (`build_season_plan` in `tools.py`) — thin wrapper: resolves the
   crop, pulls the active farm's coordinates, fetches the forecast (best-effort),
   calls the engine, returns structured JSON. Registered on the **advisor** and
   **recommender** groups. Emits a `plan` trace chip.

## Real vs mock
- **Real/live:** Open-Meteo forecast (weather overlay), CZIS coordinates/duration.
- **Bundled reference (labelled):** BAMIS/FRG calendar snapshot — cited via
  `sources` + `disclaimer` in every payload; never presented as exact.

## Supported crops (CZIS crop_id)
mustard (22) · wheat (3) · potato (12) · maize/Rabi (6) · boro_rice (1).

## Follow-ups
- CZIS variety-specific `duration_override` (hook present; wire the live call).
- Persist the generated plan to a `plans` table for cross-session recall.
- Add gold-number pytest cases under `backend/tests/` mirroring the smoke check.
