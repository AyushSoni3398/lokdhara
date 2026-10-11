# Lokdhara backend

FastAPI API (`app.main`) and background worker (`app.worker`) — see `docs/SYSTEM_ARCHITECTURE.md`.

```bash
uv sync                                   # install
uv run alembic upgrade head               # create/upgrade the schema
uv run python -m app.cli seed-dev         # synthetic users, one per role (prints passwords)
uv run uvicorn app.main:app --reload      # API on http://localhost:8000 (docs at /api/docs)
uv run python -m app.worker               # worker (Ctrl+C to stop)
uv run pytest                             # tests (set LKD_TEST_DATABASE_URL for PostgreSQL tests)
uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
```

Layout: `app/modules/<domain>/` holds `models.py`, `schemas.py`, `service.py`, `router.py`;
migrations are hand-written in `migrations/versions/` (see `.claude/skills/database-design`).
Database tests create and drop their own throwaway database on the server named by
`LKD_TEST_DATABASE_URL`.
