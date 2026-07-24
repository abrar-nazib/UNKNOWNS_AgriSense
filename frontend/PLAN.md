# PLAN.md — AgriSense Frontend Implementation

Built to `DESIGN.md` (Agronomic Instrument / B3). Approach **C** (chat + expandable
plan artifact + right collapsible trace panel). Branch: `features/redesign`.
**No commits/pushes without Sefayet's yes.**

## Latest implementation status (Jul 24, Codex)

- Billing is no longer seeded/local-only. The frontend calls authenticated FastAPI
  `/api/billing/*`; subscription state is persisted in Postgres.
- Mock mode uses OTP `1234`; real mode is ready for BDApps credentials.
- Plus and Pro use separate BDApps application credentials and expose availability through
  `subscribable_plan_ids`; cancel-before-switch prevents simultaneous carrier subscriptions.
- `/forgot-password` is linked from login and registration; profile password change is persisted.
- The unauthenticated field-demo route and mock workspace have been removed. Authenticated users
  enter the real workspace from the landing page and can log out beside that button.
- Tool traces are aggregated per user turn onto the final assistant reply for display. Live SSE
  `message_update` rows win stale query snapshots, and completed empty tool-step bubbles collapse.
  Every completed reply—including no-tool replies—has a clickable persisted-duration trace.
- `npm run typecheck` and production `npm run build` pass.

## Locked decisions
- Identity: mobile-number auth + address (PR #1, pending merge).
- Plan data: **frontend defines the schema, backend fills it** — an `agrisense_plan` JSON
  rides inside the frozen SSE contract (a tool result or fenced ```agrisense-plan block).
- Billing: persisted subscription backend with `mock|bdapps` provider switching.
- The real FastAPI SSE stream is the only chat execution path.

## Backend integration points (from B1 — real contract)
- Auth: `POST /api/auth/{register,login,refresh,logout}` · `GET /api/auth/me`. Login = `{phone,password}`. Bearer everywhere.
- Chat: `POST /api/chat/stream` (SSE) · `GET /api/chat/sessions` · `GET /api/chat/sessions/{id}/messages` · `DELETE /api/chat/sessions/{id}`.
- **SSE frames:** `session · message · message_update · progress{stage,detail} · done · error`.
  `Message = {id, role, content, tool_trace:[{tool,args,result}], model, created_at}`. Whole-bubble (no token deltas).
- Base URL `NEXT_PUBLIC_API_URL` → **http://localhost:8080** (compose backend host port; baked at build).
- Contract is **frozen** — new agronomy tools appear as trace chips with no frontend change. `agrisense_plan` must fit inside it.

## Route / file tree (Next.js App Router + TS + Tailwind)
```
src/app/
  page.tsx                 photo-led landing → /chat or /login
  login/  register/  forgot-password/  profile/
  chat/page.tsx  chat/[sessionId]/page.tsx   workspace (home)
src/components/
  chat/        MessageList · MessageBubble · Markdown · ModelBadge · MissingFieldsChips
  trace/       TracePanel · TraceGroup(latest|history) · ToolCallRow · ProgressTimeline
  plan/        PlanCard · PlanArtifact · CropComparison · SeasonCalendar · FinanceBreakdown
  profile/     BillingDashboard · SpendChart · PasswordChange
  ui/          (existing) TextInput · PasswordInput · LeafMark  (+ Button · Panel · Collapsible)
src/lib/
  types.ts(+plan types) · api.ts · auth.tsx · stream.ts · phone.ts
  finance.ts     pure cost/yield/ROI/break-even (single source; powers what-if)
  planParse.ts   extract agrisense_plan from a message (structured or markdown fallback)
src/data/  bd-geocodes.json (PR #1)
src/styles/ theme via tailwind.config.ts + globals.css (Agronomic Instrument tokens + fonts)
```

## Agentic UX components (first-class)
- **Streaming:** `stream.ts` consumes the authenticated backend SSE contract.
- **Trace panel:** right, collapsible, focused on one user turn; each `ToolCallRow` shows tool name,
  sent parameters, and expandable raw result. The final answer owns the complete turn trace.
- **Steps/thinking:** `ProgressTimeline` from `progress` frames (memory→tool→summary) + working indicator.
- **Missing-info:** `MissingFieldsChips` (location·size·soil·water·budget·season ✓/✗).
- **States:** loading (skeleton/indicator), **Stop** (abort mid-stream), error banner, empty state.
- **Model badge** per assistant bubble.

## Milestones
- [x] **M1 · Real workspace** — authenticated FastAPI SSE chat with sessions, trace, plan, and stop states.
- [x] **M2 · Trace panel** — collapsible, latest-vs-history groups, ToolCallRow detail, ProgressTimeline.
- [x] **M3 · Plan artifact** — CropComparison + SeasonCalendar + FinanceBreakdown.
- [x] **M4 · Intake + states** — MissingFieldsChips, Stop, loading/error/empty, ModelBadge.
- [x] **M5 · Real backend** — `stream.ts`, `planParse.ts`, and `NEXT_PUBLIC_API_URL=8080`.
- [x] **M6 · Profile + billing** — persisted PasswordChange + server-backed subscription status.
- [ ] **M7 · Uploads (staged)** — Composer attachments; mock leaf-disease + doc-ingest results.
- [x] **M8 · Landing hero** — licensed Bangladesh paddy photo, field-brief overlay, and GSAP entrance.
- [x] **M9 · BDApps subscription foundation** — persisted mock flow + real provider adapter.
      Independent Plus/Pro app routing is complete; portal passwords, Pro ID, and live tests remain.
- [x] **M10 · Reliable agent trace display** — cache write-through/live precedence, final-answer
      turn aggregation, and `Thought for <duration>` status on every completed prompt; state
      regression and backend streaming tests pass.
- [ ] **M11 · Release readiness** — judge click-path rehearsal and README integration table.

## Skills, used surgically
- Structure/logic: `nextjs-developer`, `react-expert`, `typescript-pro`. Styling: `ckm-ui-styling` (Tailwind/Radix primitives).
- Design taste: `ui-ux-pro-max` (done — palette/type), match `DESIGN.md`. Motion:
  `gsap-*`/`framer-motion` (sparingly). Data: `dataviz` (M6). Core logic
  (`finance.ts`, `planParse.ts`): `test-driven-development`.

## Judge demo script (4-min click-path)
1. Land → field story → "Start" → login (phone) → real workspace.
2. Type a vague opening ("plant something this winter, 2 bigha, sandy soil, Rangpur").
3. Agent asks only for the **missing** fields (water, budget) — chips update. Answer.
4. Plan streams in; **PlanCard** appears. Open **Trace** → point at the weather number → expand the `get_weather` call → "that came from a real API, not the model."
5. Open **PlanArtifact** → edit a finance input / drag rainfall −30% → numbers recompute live (scenario sim).
6. Profile → backend history analytics + BDApps subscription status. Close.

## Build checklist (cross-cutting)
- [x] `tsc --noEmit` clean. [x] Production build clean. [ ] Reduced-motion verified. [ ] Keyboard + focus rings.
- [x] Unauthenticated mock workspace removed. [x] No emoji icons (Lucide only).
  [ ] No commits without approval.
