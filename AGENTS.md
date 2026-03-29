# Repository Guidelines

## Project Structure & Module Organization
Source lives under `src/`, with `main.py` bootstrapping `bot/` (telegram handlers & keyboards), `ucp/` (HTTP client + Pydantic models), and `middleware/` (validators, rate limiter). Specs that drive changes stay in `SPEC.md`; README captures deploy notes. Tests mirror packages inside `tests/` (`test_ucp_client.py`, etc.) and should track any new module you add.

## Build, Test & Development Commands
- `pip install -e ".[dev]"` – install runtime + dev dependencies.
- `python -m src.main` – run the bot locally (respects `.env`).
- `pytest -v` – execute the async-heavy test suite.
- `ruff check src tests` – lint + enforce formatting fixes before opening a PR.
Use `.env.example` as the template for local config, then run with `USE_POLLING=true` for polling mode.

## Coding Style & Naming Conventions
Python 3.11, 4-space indentation, 100-char soft limit (per `tool.ruff`). Favor type hints, dataclasses/Pydantic models, and descriptive handler names like `catalog.py::browse_catalog`. Function/class names follow `snake_case`/`PascalCase`; Telegram state constants live in `states.py` as SCREAMING_SNAKE_CASE. Let Ruff autofix simple issues (`ruff check --fix`).

## Testing Guidelines
Pytest is configured via `pyproject.toml` (asyncio auto-mode). Name files/functions `test_*.py`/`test_*`. Mock HTTP boundaries with `respx` and cover both happy-path and failure scenarios for each handler plus UCP client call. Block merges if new logic lacks tests; aim to keep coverage parity with SPEC §8 scenarios.

## Commit & Pull Request Guidelines
Git history uses Conventional Commit prefixes (e.g., `feat: add checkout guard`). Keep subject ≤72 chars and describe intent, not mechanics. PRs should link specs or issues, enumerate behavior changes, call out env var impacts, and attach logs/screenshots for Telegram flows when relevant. Include test + lint command outputs in the PR description to speed review.

## Security & Configuration Tips
Never commit secrets—`.env` stays local. Always set `TELEGRAM_WEBHOOK_SECRET`, `UCP_API_KEY`, and merchant URL before hitting staging. Validate incoming webhook secrets and avoid logging full payloads; stick to high-level breadcrumbs via `configure_logging` in `src.config`.
