# Argi Backend

FastAPI + async SQLAlchemy + pgvector backend for the Argi agri-tech agentic
chat. Implements JWT auth (with refresh rotation + blacklist) and a LangGraph
single-agent ReAct pipeline that streams over SSE.

## Run

### Docker (recommended)
Built to run behind a Postgres service named `db` with the pgvector image
(e.g. `pgvector/pgvector:pg16`). From `docker-compose`:

```yaml
backend:
  build: ./backend
  env_file: .env
  ports: ["8000:8000"]
  depends_on: [db]
```

Schema is owned by **Alembic migrations**. The container entrypoint
(`entrypoint.sh`) runs `alembic upgrade head` (the first migration creates the
`vector` extension) and then launches uvicorn. The app no longer calls
`create_all` on startup.

### Local
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# point DATABASE_URL at a reachable pgvector Postgres, then:
uvicorn app.main:app --reload --port 8000
```

## Database migrations (Alembic)

Schema changes are versioned with Alembic (async `env.py`, uses
`settings.DATABASE_URL`, `compare_type=True`). **Model changes now mean a new
migration — never nuke the database.**

```bash
# after editing app/models.py, generate a migration from the diff:
alembic revision --autogenerate -m "add crop_notes table"
#  ^ review the generated file in migrations/versions/ before committing

# apply all pending migrations (this is what the container does at start):
alembic upgrade head

# roll back the most recent migration:
alembic downgrade -1
```

Notes:
- The `Makefile` wraps these: `make makemigrations m="msg"`, `make migrate`.
- The initial migration (`0001_initial`) `CREATE EXTENSION IF NOT EXISTS vector`
  before creating `long_term_memory`; keep the extension creation in the
  migration, not app startup.
- pgvector `Vector` columns render via a `render_item` hook in `env.py`, so
  autogenerate emits `pgvector.sqlalchemy.Vector(dim=...)` correctly.
- Running against a throwaway DB to sanity-check:
  ```bash
  DATABASE_URL=postgresql+asyncpg://argi:argi_dev_password@db:5432/argi_migtest \
    alembic upgrade head        # creates all tables + extension
  DATABASE_URL=... alembic downgrade base   # cleanly reverses
  ```

## Tests

See `tests/README.md`. Quick start (inside the backend container, against the
compose Postgres):

```bash
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://argi:argi_dev_password@db:5432/argi_test \
  pytest -q
# or: make test
```

## Environment
See `../.env.example`. Key vars:

| var | default | purpose |
|-----|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://argi:...@db:5432/argi` | async DSN (asyncpg) |
| `JWT_SECRET_KEY` / `JWT_ALGORITHM` | — / `HS256` | token signing |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | access lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | refresh lifetime |
| `BILLING_PROVIDER` | `mock` | `mock` (OTP `1234`) or real `bdapps` |
| `BDAPPS_PLUS_APPLICATION_ID` / `BDAPPS_PLUS_PASSWORD` | — | server-only BDT 199 Plus app credentials |
| `BDAPPS_PRO_APPLICATION_ID` / `BDAPPS_PRO_PASSWORD` | — | server-only BDT 499 Pro app credentials |
| `BDAPPS_PLUS_APPLICATION_HASH` / `BDAPPS_PRO_APPLICATION_HASH` | — | optional per-app OTP hashes |
| `OPENROUTER_API_KEY` | — | **required for chat**; agent raises without it |
| `OPENROUTER_MODEL` / `OPENROUTER_BASE_URL` | `deepseek/deepseek-chat` / openrouter | chat LLM |
| `EMBEDDINGS_PROVIDER` | `fake` | `fake` (offline, deterministic) or `ollama` |
| `EMBEDDING_DIM` | `768` | pgvector column width (must match provider) |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_EMBED_MODEL` | — | Ollama config |
| `HISTORY_LIMIT` | `40` | message window before rolling summary |
| `MEMORY_TOP_K` | `5` | semantic recall depth |
| `CORS_ORIGINS` | `http://localhost:3000,...` | comma-separated allowed origins |

> Embeddings default to `fake` so long-term memory works fully offline.
> The **chat** model always needs a valid `OPENROUTER_API_KEY`.

## Endpoints
All under the base URL (default `http://localhost:8000`). See
`docs/API_CONTRACT.md` for exact shapes.

- `POST /api/auth/register` · `POST /api/auth/login`
- `POST /api/auth/refresh` (rotation) · `POST /api/auth/logout` · `GET /api/auth/me`
- `POST /api/auth/password/change` · `POST /api/auth/password/reset/{request,confirm}`
- `GET /api/billing/{plans,subscription}` · `POST /api/billing/otp/{request,verify}`
- `POST /api/bdapps/sms/receive` · `POST /api/bdapps/subscription/notify`

Production BDApps portal callbacks:

- Message Receiving URL:
  `https://agrisense.cortextech.dev/api/bdapps/sms/receive`
- Subscription Notification URL:
  `https://agrisense.cortextech.dev/api/bdapps/subscription/notify`

Successful OTP verification is terminal: BDApps activates the subscription and
the frontend updates the plan immediately without a second continuation action.
Plus and Pro use separate BDApps application credentials because each
application owns one recurring tariff. Masked subscriber identities are
persisted and reused with the matching application for status, notification
and cancellation calls.

Production configuration and portal field values are documented in
`docs/BDAPPS_PRODUCTION_SETUP.md`.
- `POST /api/billing/subscription/cancel`
- `POST /api/chat/stream` (SSE) · `GET /api/chat/sessions`
- `GET /api/chat/sessions/{id}/messages` · `DELETE /api/chat/sessions/{id}`
- `GET /health`

## Agent
LangGraph ReAct loop (`app/agent/`): tools `get_current_time`, `calculator`,
`save_memory`, `recall_memory`. Long-term memory is user-scoped pgvector
semantic recall; each session also keeps a rolling `summary`. The stream
runner emits `session` / `message` / `message_update` / `progress` / `done` /
`error` frames per the contract.
