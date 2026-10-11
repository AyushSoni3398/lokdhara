# Lokdhara — instructions for Claude Code

## Mission and scope

Lokdhara is a community-driven, research-oriented platform for preserving and digitising the **Mundari language** (ISO 639-3 `unr`, Jharkhand, India): consented audio recordings, Mundari text, transcriptions, Hindi/English translations, review, and versioned, consent-filtered research datasets.

**MVP = language preservation only.** Do not add general cultural-heritage features (recipes, artefacts, traditions), ASR/MT, public browsing, or open sign-up. Scope: `docs/MVP_SCOPE.md`.

## Current phase

**Plan approved (2026-10-11); Milestone 1 done; Milestone 2 (database, storage, auth) in progress.** Implement only the current milestone in `docs/ROADMAP.md`; do not start later milestones (uploads, auth, migrations, production infrastructure) without the owner's go-ahead.

## Architecture (see `docs/SYSTEM_ARCHITECTURE.md`, `docs/ARCHITECTURE_DECISIONS.md`)

- Modular monolith: FastAPI `api` process + `worker` process, one codebase.
- Frontend: React + TypeScript + Vite SPA, react-i18next (`hi`, `en`).
- Backend: Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, uv, ruff, mypy, pytest.
- Database: PostgreSQL 18 (JSONB only for open-ended metadata). Job queue in PostgreSQL (ADR-007).
- Files: S3-compatible object storage behind `ObjectStore`; local filesystem adapter in dev.
- Audio tooling: FFmpeg/ffprobe; model-based tools are advisory only.
- Deploy: Docker Compose on one VM + Caddy.

## Repository layout

```
CLAUDE.md, README.md, .gitignore, .editorconfig, .env.example
docs/                 # all planning and design docs (source of truth)
.claude/rules/        # path-scoped rules (load when matching files are touched)
.claude/skills/       # procedures: audio, text, database, privacy, git
backend/              # FastAPI app/ (main, config, db, errors, security, cli, worker,
                      #   modules/<domain>/{models,schemas,service,router}.py), migrations/, tests/
frontend/             # Vite React app: src/{pages,components,i18n}
infra/                # docker-compose.yml (Caddyfile in M8)
scripts/              # repository checks used by CI
.github/workflows/    # CI
```

## Development commands

```bash
docker compose -f infra/docker-compose.yml up -d db     # PostgreSQL 18 (local only)
cd backend && uv sync                                   # Python 3.13 deps
uv run alembic upgrade head                             # apply migrations
uv run python -m app.cli seed-dev                       # synthetic users (prints passwords)
uv run python -m app.cli create-admin --username …       # first real admin
uv run uvicorn app.main:app --reload                    # API :8000 (docs /api/docs)
uv run python -m app.worker                             # worker
uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run pytest
cd frontend && npm ci && npm run dev                    # SPA :5173 (proxies /api)
npm run lint && npm run typecheck && npm test && npm run build && npm run size
bash scripts/check-forbidden-files.sh                   # same check CI runs
```

Set `LKD_TEST_DATABASE_URL` to run the PostgreSQL integration tests locally (CI always runs them).

## Non-negotiable data rules

1. **Never commit** audio, collected text, consent documents, personal data, datasets/exports, DB dumps, `.env` files, keys, or credentials. Test fixtures must be synthetic and preferably generated at test time.
2. **Never modify or delete an original recording** during processing; derived files are separate and record tool versions (ADR-009).
3. **Never alter submitted text in place**; store verbatim, derive NFC/normalised forms separately (ADR-010). No single "correct" Mundari orthography is assumed.
4. **Never treat machine output as ground truth**; machine revisions are `origin = machine` and unverified (ADR-014).
5. **Never widen access beyond consent.** All visibility goes through the single effective-access rule (ADR-012, `docs/ACCESS_CONTROL.md`).
6. **Never log** audio, text content, names, contacts, tokens, or raw IPs.
7. Never assume contributed data may be published, used commercially, or used for AI training.
8. Do not claim legal compliance in code, docs, or UI copy.

## Before changing things

- Changing architecture, stack, schema, data lifecycle, consent, or access rules: read the relevant docs in `docs/` first, then record the change as a new ADR in `docs/ARCHITECTURE_DECISIONS.md` and update affected docs **in the same change**.
- Changing API behaviour: update `docs/API_SPECIFICATION.md` in the same change.
- New ambiguity: add it to `docs/ASSUMPTIONS_AND_OPEN_QUESTIONS.md`; ask the owner only if it materially affects architecture, cost, ownership, privacy, or scope.
- Touching personal data, consent, auth, uploads, or exports: use the `privacy-review` skill.

## Code quality and testing

- Small, focused changes. Pure functions for rules (validation, normalisation, effective access) so they are unit-testable.
- Every bug fix starts with a failing test. Consent gating, effective access, withdrawal propagation, and the export allow-list need exhaustive tests (`docs/TESTING_STRATEGY.md`).
- Integration tests use real PostgreSQL, not SQLite.
- Run lint, type-check, and tests before every commit that touches code.

## Git and commits

- Conventional Commits (`docs:`, `feat:`, `fix:`, `test:`, `chore:`, `refactor:`), small and independently reviewable.
- **No AI co-author or session trailers.** Use the developer's own configured git identity; never change git identity without asking; stop if the configured author is unexpected or a bot.
- No empty, artificial, or duplicate commits.
- Work on branches; never commit directly to `main` without the owner's agreement.
- Ask before the first push to any remote. Never force-push, rewrite published history, delete branches, change repository visibility, add collaborators, or configure secrets without explicit approval.
- Use the `git-workflow` skill before committing.

## Prohibited actions

- Creating paid cloud resources or production infrastructure without approval.
- Adding Claude/AI bots or external collaborators to the repository.
- Publishing or uploading collected language data anywhere.
- Adding dependencies that send data to third parties (analytics, AI APIs, managed auth) without an ADR.
