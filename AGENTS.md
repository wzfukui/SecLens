# Repository Guidelines

## Project Structure & Module Organization
- `app/` holds the FastAPI application (routers, schemas, services) and starts at `app/main.py`.
- `collectors/` contains source-specific plugins; each plugin maintains its own state and exposes a `run()` entry point.
- `tests/` mirrors the `app/` and `collectors/` layout with matching module names.
- `scripts/` hosts one-off utilities such as local ingestion runners or data migration helpers.
- Configuration examples live in `.env.example`; keep environment-specific overrides in `.env` (never commit).

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` sets up and activates the virtual environment.
- `pip install -r requirements.txt` installs API, collector, and tooling dependencies.
- `uvicorn app.main:app --reload` runs the API locally with hot reload.
- `python scripts/run_collector.py --source aliyun` executes a single collector against the ingest API.
- `pytest` runs the entire test suite; add `-k name` to target a subset.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and `snake_case` for modules, functions, and variables.
- Use `PascalCase` for Pydantic models and SQLAlchemy ORM classes.
- Keep FastAPI routers grouped by domain (e.g., `alerts.py`, `sources.py`).
- Run `ruff check .` before committing to enforce lint rules and auto-fix trivial issues.

## Testing Guidelines
- Use `pytest` with fixtures under `tests/fixtures` for shared setup (database, HTTP mocks).
- Name test files `test_<module>.py` and ensure each new feature has unit coverage plus an ingestion happy-path test.
- Integrate `pytest --cov=app --cov=collectors` in CI; target ≥80% coverage for core modules.

## Commit & Pull Request Guidelines
- Write commits in the imperative mood (e.g., `Add Aliyun bulletin collector`).
- Organize changes so each commit addresses a single concern; rebase to keep history linear.
- PRs must describe the change, testing performed (`pytest`, manual collector run), and any configuration updates.
- Link to tracking issues and include screenshots or sample payloads when modifying API responses or UI.

## Security & Configuration Tips
- Never hard-code credentials; rely on environment variables and `.env` templates.
- Review third-party source terms before adding a collector and honor rate limits (`time.sleep` if necessary).
- Store long-lived API tokens in the secrets manager of your deployment environment, not in code or `.env` files.
