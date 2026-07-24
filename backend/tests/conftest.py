"""Pytest fixtures for the Argi backend.

Design (Django-TestCase-like isolation over an async stack):

* A **separate** database ``argi_test`` on the SAME compose Postgres (so
  pgvector is available). The app database ``argi`` is never touched.
* The test DB + ``vector`` extension + all tables are created ONCE per session
  via ``Base.metadata.create_all`` on a test engine (fast; no Alembic needed
  for the test schema).
* Each test gets a fresh async engine (created on that test's event loop, so we
  never reuse an engine across loops) and is **isolated by TRUNCATE**: every
  table is truncated with ``RESTART IDENTITY CASCADE`` before the test runs, so
  tests never see each other's rows (the Django ``TransactionTestCase``
  behavior). This is used instead of a single-connection SAVEPOINT rollback
  because the streaming endpoint deliberately opens its OWN ``AsyncSessionLocal``
  session (independent of the request's ``get_db`` session) and commits several
  times mid-turn — a nested-savepoint scheme would see the request's auth
  session roll those writes back on teardown.
* ``get_db`` and every module-level ``AsyncSessionLocal`` (source + streaming
  router + memory tools) are pointed at the per-test engine, so all app code —
  including the stream — commits to the same place and reads are consistent.
* The app lifespan is NOT run (plain ASGITransport), so no ``create_all`` /
  Alembic runs against the test DB during tests — schema is owned by fixtures.
"""
from __future__ import annotations

import asyncio
import os

# --- Point the app at the test DB BEFORE importing any app module ---------- #
os.environ.setdefault("TESTING", "1")
# Tests must never call OpenAI/Ollama — force offline fake embeddings for the
# knowledge base regardless of what .env/compose injected.
os.environ["KB_EMBEDDINGS_PROVIDER"] = "fake"
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://argi:argi_dev_password@localhost:5433/argi_test",
)
# The app reads DATABASE_URL via pydantic settings at import time; make the
# whole app operate against the test DB.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

# Import app modules AFTER DATABASE_URL is set.
from app import database as db_module  # noqa: E402
from app.agent import tools as tools_module  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import chat as chat_router  # noqa: E402

from tests import fakes  # noqa: E402


# --------------------------------------------------------------------------- #
# One-time database + schema setup (done synchronously via asyncio.run so we
# never fight pytest-asyncio over event-loop scopes).
# --------------------------------------------------------------------------- #
async def _create_database_if_missing() -> None:
    url = make_url(TEST_DATABASE_URL)
    db_name = url.database
    # Connect to a maintenance DB to issue CREATE DATABASE.
    for maint in ("postgres", "template1", "argi"):
        try:
            conn = await asyncpg.connect(
                host=url.host,
                port=url.port,
                user=url.username,
                password=url.password,
                database=maint,
            )
        except Exception:
            continue
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", db_name
            )
            if not exists:
                await conn.execute(f'CREATE DATABASE "{db_name}"')
        finally:
            await conn.close()
        return
    raise RuntimeError("Could not connect to a maintenance DB to create the test DB.")


async def _create_schema() -> None:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def _drop_schema() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Create the test DB + schema once, tear the schema down at the end."""
    asyncio.run(_create_database_if_missing())
    asyncio.run(_create_schema())
    yield
    try:
        asyncio.run(_drop_schema())
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Per-test engine + TRUNCATE isolation.
# --------------------------------------------------------------------------- #
# Truncate order does not matter with CASCADE; list all model tables.
_ALL_TABLES = [t.name for t in Base.metadata.sorted_tables]


@pytest_asyncio.fixture
async def test_engine():
    """A fresh async engine bound to this test's event loop."""
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(test_engine):
    """Normal (real-commit) session factory on the per-test engine."""
    return async_sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def db_session(session_factory):
    """A single session for direct-use tests (e.g. memory)."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def _bind_app_to_test_engine(test_engine, session_factory, monkeypatch):
    """Isolate + route all app DB access to the per-test engine.

    - TRUNCATE every table (RESTART IDENTITY) so the test starts clean.
    - Override ``get_db`` and monkeypatch every ``AsyncSessionLocal`` reference
      (source + streaming router + memory tools) to the per-test factory, so
      the app (including the SSE stream) commits to the same DB the tests read.
    """
    # Clean slate before the test.
    async with test_engine.begin() as conn:
        if _ALL_TABLES:
            table_list = ", ".join(f'"{name}"' for name in _ALL_TABLES)
            await conn.execute(
                text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")
            )

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(db_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(chat_router, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(tools_module, "AsyncSessionLocal", session_factory)

    yield

    app.dependency_overrides.pop(get_db, None)


# --------------------------------------------------------------------------- #
# HTTP clients
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def client(_bind_app_to_test_engine):
    """Anonymous httpx client wired to the app via ASGITransport.

    Lifespan is intentionally not run, so no schema DDL happens here.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client):
    """Register + log in a default user; return a Bearer header dict."""
    return await fakes.auth_headers_for(client, phone="01712345678")


@pytest_asyncio.fixture
async def auth_client(client, auth_headers):
    """A client whose default headers carry the default user's Bearer token."""
    client.headers.update(auth_headers)
    return client


# --------------------------------------------------------------------------- #
# Fake LLM wiring (no network / no OpenRouter, ever)
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_llm(request, monkeypatch):
    """Monkeypatch ``build_chat_model`` everywhere the agent uses it.

    Parametrize with ``@pytest.mark.parametrize("fake_llm", ["plain"|"tool"],
    indirect=True)``; defaults to ``"plain"``.
    """
    scenario = getattr(request, "param", "plain")
    factory = fakes.make_fake_llm(scenario)

    from app.agent import graph as graph_module
    from app.agent import llm as llm_module
    from app.agent import runner as runner_module

    monkeypatch.setattr(graph_module, "build_chat_model", factory)
    monkeypatch.setattr(runner_module, "build_chat_model", factory)
    monkeypatch.setattr(llm_module, "build_chat_model", factory)
    return scenario
