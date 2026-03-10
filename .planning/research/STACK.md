# Technology Stack

**Project:** Quant Sports Agentic Analytics Platform
**Researched:** 2026-03-09
**Research Mode:** Ecosystem — standard 2025 stack for LangGraph multi-agent + PostgreSQL + NFL data ingestion

---

## Confidence Note

All external verification tools (WebSearch, WebFetch, Bash/pip) were blocked during this research session.
Versions are sourced from training data current through August 2025. Where a version may have advanced
since cutoff, the confidence level is marked explicitly. Pin to exact versions after running
`pip index versions <package>` to confirm.

---

## Recommended Stack

### Agent Orchestration

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `langgraph` | `>=0.2, <0.3` | Multi-agent directed graph, state machine, routing | Native directed-graph model maps exactly to Master → Context/Quant/Arbitrage/Kinematic routing. Explicit `StateGraph` with typed `TypedDict` state. Checkpointing for interrupted runs. | MEDIUM — 0.2.x was stable as of Aug 2025; may be 0.3.x by now |
| `langchain-core` | `>=0.3, <0.4` | LangChain primitives (messages, runnables, tool-calling) | LangGraph depends on langchain-core; do NOT install full `langchain` package — only core is needed to keep dependencies minimal | MEDIUM |
| `langchain-openai` | `>=0.2` | OpenAI adapter for LangGraph nodes | Needed if using GPT-4o/o1 as orchestration LLM; kept out of data path entirely | MEDIUM |

### Data Validation

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `pydantic` | `>=2.7, <3.0` | Strict validation of all LLM outputs before SQL execution | Pydantic v2 (Rust core) is 5–17x faster than v1. `model_validate()`, `model_fields`, `@field_validator` with `mode='before'`. Use `model_config = ConfigDict(strict=True)` everywhere. Non-negotiable per project constraints. | HIGH — v2 stable since mid-2023, 2.7 released 2024 |

### Python Runtime & Type Checking

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Python | `3.12` | Runtime | 3.12 is the recommended production Python as of 2025. Faster than 3.11 (~5% interpreter speedup), `@override` decorator, better `TypeVar` inference. Avoid 3.13 (still beta-ish ecosystem as of Aug 2025). | HIGH |
| `mypy` | `>=1.10` | Static type checking | Strict mode: `--strict --disallow-untyped-defs`. Required for "strictly typed Python". Use `pyproject.toml` mypy config. | HIGH |
| `pyright` | `>=1.1.370` | IDE-level type inference (Pylance in VS Code) | Complementary to mypy; catches different classes of errors. Use both. | HIGH |

### PostgreSQL Drivers

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `asyncpg` | `>=0.29` | Primary async PostgreSQL driver | Fastest async Postgres driver available — up to 3x faster than psycopg2 async. Pure protocol implementation (no libpq). Use for all hot-path queries (odds ingestion, quant lookups). | HIGH — 0.29.0 stable 2024 |
| `psycopg[binary]` (v3) | `>=3.2` | Sync fallback + COPY operations | psycopg3 is the official successor to psycopg2. Use for bulk COPY ingestion of NFL historical data where asyncpg's COPY API is awkward. Do NOT use psycopg2 — it is unmaintained. | MEDIUM — 3.2.x released 2025 |
| `SQLAlchemy` | `>=2.0` | ORM / query builder | SQLAlchemy 2.0 has async support via `AsyncSession`. Use for schema migrations and non-hot-path queries only. Do NOT use for hot-path betting logic — raw asyncpg is faster and safer. | HIGH — 2.0 stable since 2023 |
| `alembic` | `>=1.13` | Schema migrations | SQLAlchemy-native migration tool. Required for managing multi-year NFL schema evolution. | HIGH |

### NFL Data Ingestion

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `nfl_data_py` | `>=0.3` | Historical NFL box scores, play-by-play, Next Gen Stats | Python wrapper around nflfastR data. Returns pandas DataFrames. Use `import_pbp_data()`, `import_players()`, `import_ngs_data()` for tracking. Free, comprehensive back to 1999. | MEDIUM — API stable but minor version unclear |
| `pandas` | `>=2.2` | DataFrame operations on NFL data | pandas 2.x with Arrow backend (`dtype_backend="arrow"`) reduces memory ~40% on large PBP datasets. Mandatory: drop unused columns immediately after load. | HIGH — 2.2 stable 2024 |
| `pyarrow` | `>=16.0` | Arrow memory backend for pandas | Enables pandas 2.x Arrow dtype backend. Also used for Parquet caching of NFL data to avoid re-fetching. | MEDIUM |

### Odds Ingestion

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `httpx` | `>=0.27` | Async HTTP client for The Odds API | httpx is the async-native replacement for requests. Built-in rate limiting support, HTTP/2, connection pooling. Use `httpx.AsyncClient` with explicit timeout/retry config. Do NOT use `requests` (blocking). | HIGH |
| `tenacity` | `>=8.3` | Retry logic for API calls | Exponential backoff with jitter for The Odds API rate limit compliance. Composable with httpx. | HIGH |

### Web Scraping

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `playwright` | `>=1.44` (async) | JavaScript-rendered pages | Use `async_playwright` context manager. Required for ESPN injury reports, beat writer pages that block simple HTTP clients. | HIGH |
| `beautifulsoup4` | `>=4.12` | HTML parsing after Playwright fetch | Pair with `lxml` parser (faster than html.parser). Use only on static or pre-rendered HTML. | HIGH |
| `lxml` | `>=5.2` | BS4 parser backend | Fastest HTML/XML parser for BeautifulSoup. Always pass `features="lxml"` to `BeautifulSoup()`. | HIGH |

### Task Scheduling & Background Jobs

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `apscheduler` | `>=4.0` | Cron-style scheduling for data pipelines | APScheduler 4.0 is async-native (asyncio). Schedule odds refreshes, injury scrapes, NGS pulls. Do NOT use Celery — overkill for single-machine local dev. | MEDIUM — 4.0 RC as of Aug 2025; verify stable release |
| `asyncio` | stdlib | Event loop orchestration | Python 3.12 asyncio is the backbone. All I/O-bound work (DB queries, API calls, scraping) must be async. | HIGH |

### Caching & Rate Limiting

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `redis` / `redis-py` | `>=5.0` | In-memory cache for odds, computed probabilities | Optional but recommended. Cache computed Kelly outputs and odds snapshots to avoid redundant DB hits. Use Redis 7.x with `asyncio` interface. | MEDIUM — useful but not v1-critical |
| `limits` | `>=3.12` | Rate limiting for The Odds API | Enforces stay-within-quota logic before requests hit httpx. Prevents accidental API quota burn during dev. | MEDIUM |

### Testing

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `pytest` | `>=8.2` | Test runner | Standard. Use `pytest-asyncio` for async test cases. | HIGH |
| `pytest-asyncio` | `>=0.23` | Async test support | Required for testing async agent nodes, DB queries, scraper coroutines. Set `asyncio_mode = "auto"` in `pyproject.toml`. | HIGH |
| `pytest-postgresql` | `>=6.0` | Ephemeral Postgres for integration tests | Spins up a real Postgres instance per test session. Required for testing Pydantic→SQL pipeline without mocking. | MEDIUM |
| `factory-boy` | `>=3.3` | Test fixture factories | Generate typed Pydantic model instances for testing agent nodes in isolation. | MEDIUM |

### Configuration & Environment

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `pydantic-settings` | `>=2.3` | Typed env var loading | `BaseSettings` from pydantic-settings reads `.env` files and validates all config at startup. No `os.environ.get()` calls scattered through code. | HIGH |
| `python-dotenv` | `>=1.0` | `.env` file loading | Used by pydantic-settings internally; also useful for local dev. | HIGH |

### Logging & Observability

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `structlog` | `>=24.1` | Structured JSON logging | Structured logging with context binding. Agent run IDs, bet IDs, timestamp precision required for audit trail. Do NOT use plain `logging` module — too unstructured for multi-agent event traces. | HIGH |
| `langsmith` | `>=0.1` | LangGraph trace observability | LangSmith integrates natively with LangGraph for tracing agent node execution, LLM call latency, and token usage. Free tier available. Invaluable for debugging routing logic. | MEDIUM |

### Dependency Management

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `uv` | `>=0.4` | Package manager and venv | uv is 10–100x faster than pip for installs and resolves. Replaces pip + virtualenv. Use `uv sync` and `uv.lock` for reproducible builds. | HIGH — ecosystem consensus as of 2025 |

---

## Alternatives Considered and Rejected

| Category | Recommended | Rejected | Why Rejected |
|----------|-------------|----------|--------------|
| Agent framework | `langgraph` | AutoGen, CrewAI | AutoGen is research-focused, poor production state management. CrewAI hides control flow — bad for a deterministic quant system where routing logic must be explicit. |
| LLM validation | `pydantic` v2 | `instructor`, `guardrails-ai` | `instructor` is excellent but adds abstraction over Pydantic; unnecessary since we call `model_validate()` directly on structured outputs. `guardrails-ai` is heavy and opinionated. |
| DB driver (sync) | `asyncpg` + psycopg3 | `psycopg2` | psycopg2 is synchronous-only and in maintenance mode. No new features. psycopg3 is the official successor. |
| ORM hot path | raw asyncpg | SQLAlchemy ORM on hot path | SQLAlchemy ORM adds per-row Python overhead; unacceptable for high-frequency quant queries. SQLAlchemy 2.0 is used for migrations and schema management only. |
| HTTP client | `httpx` | `requests`, `aiohttp` | `requests` is blocking — unusable in async context. `aiohttp` is fine but httpx has cleaner API, built-in retry hooks, and is the community consensus async-first choice. |
| Scraping JS pages | `playwright` | `selenium`, `splash` | Selenium is slow and requires WebDriver manager complexity. Splash is unmaintained. `playwright` has async-native Python API and is maintained by Microsoft. |
| Scheduling | `apscheduler` 4.x | Celery, RQ | Celery and RQ require a separate broker (Redis/RabbitMQ) and worker processes — massive overkill for local single-machine v1. APScheduler 4.x runs in-process. |
| Full LangChain | `langchain-core` only | Full `langchain` package | Full `langchain` pulls in ~100 transitive deps and introduces version conflicts. Only `langchain-core` + `langgraph` + specific adapters needed. |
| Data validation ORM | `pydantic` | `attrs`, `dataclasses` | dataclasses have no runtime validation. `attrs` has validators but less ecosystem integration with LangGraph/LangChain tool-calling schemas. |
| Package manager | `uv` | `poetry`, `pip` | `poetry` is 10–50x slower than uv. pip without lockfile is not reproducible. uv is the 2025 standard. |

---

## What Must NOT Be Used

| Package | Reason |
|---------|--------|
| `langchain` (full package) | 100+ transitive deps, conflicts; use `langchain-core` only |
| `psycopg2` | Synchronous-only, maintenance mode since 2023; blocks event loop |
| Any LLM call for data retrieval | LLM must never be a stats source — violates core project constraint |
| `requests` library in async code | Blocks the event loop; all I/O must use `httpx` or `aiohttp` |
| `openai` SDK raw calls in agent nodes | Use LangGraph's `ToolNode` + `langchain-openai` adapter to stay in graph |
| Flat floats for bet sizing | Kelly Criterion only; any function returning a flat stake size is a bug |
| `pandas` without column pruning | Multi-year PBP DataFrames are 3–5 GB raw; drop unused columns immediately after load |
| `pickle` for agent state persistence | Use LangGraph's built-in checkpointer (PostgreSQL or SQLite backed) instead |

---

## Installation

```bash
# Install uv first (replaces pip/virtualenv)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create project
uv init sportsbet --python 3.12
cd sportsbet

# Core agent stack
uv add langgraph langchain-core langchain-openai pydantic pydantic-settings

# Database
uv add asyncpg "psycopg[binary]" sqlalchemy alembic

# NFL data
uv add nfl_data_py pandas pyarrow

# Odds API + scraping
uv add httpx tenacity playwright beautifulsoup4 lxml

# Scheduling + observability
uv add apscheduler structlog langsmith

# Dev dependencies
uv add --dev mypy pyright pytest pytest-asyncio pytest-postgresql factory-boy

# Install Playwright browsers (one-time)
playwright install chromium
```

---

## Key Configuration Anchors

```toml
# pyproject.toml — required sections

[tool.mypy]
strict = true
disallow_untyped_defs = true
warn_return_any = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.12"
```

---

## Sources

- LangGraph documentation: training data (Aug 2025 cutoff); verify at https://langchain-ai.github.io/langgraph/
- Pydantic v2 docs: HIGH confidence, stable since 2023; https://docs.pydantic.dev/latest/
- asyncpg: HIGH confidence; https://magicstack.github.io/asyncpg/
- psycopg3: MEDIUM confidence; https://www.psycopg.org/psycopg3/docs/
- nfl_data_py: MEDIUM confidence; https://github.com/nflverse/nfl_data_py
- uv package manager: HIGH confidence; https://docs.astral.sh/uv/

**NOTE:** All versions marked MEDIUM confidence should be validated with `pip index versions <package>` before locking in `uv.lock`. The version ranges specified are lower bounds — pin to latest stable at project init time.
