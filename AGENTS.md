# Repository Guidelines

## Project Structure & Module Organization
Transcribation Server is a Python/FastAPI project.

Current baseline:
- `src/app/`: API, ASR engines, DB, queue manager, Telegram bot.
- `tests/`: API and service tests.
- `alembic/`: DB migrations.
- `docs/`: documentation and API specs.
- `.env.example`: documented environment variables (never commit real secrets).

Keep modules small and cohesive. Prefer one feature per directory, with clear entry points such as `src/<feature>/index.*`.

## Build, Test, and Development Commands
Main workflow:
- `python -m pip install -e .[dev]`: install dependencies.
- `python -m uvicorn app.main:app --reload --app-dir src`: run local server.
- `python -m alembic upgrade head`: apply DB migrations.
- `python -m pytest -q`: run tests.

If additional scripts are introduced (lint/format/release), document them in `README.md`.

## Coding Style & Naming Conventions
Use consistent formatting and enforce it with tooling:
- Indentation: 4 spaces for Python.
- Naming: `PascalCase` for classes/components, `camelCase` for variables/functions, `kebab-case` for file names unless framework conventions differ.
- Keep functions focused, avoid long files, and prefer explicit types/interfaces where available.

Use type hints for new Python code and keep public request/response models explicit (Pydantic schemas).

## Testing Guidelines
Place tests in `tests/` or next to modules with `.test`/`.spec` naming. Follow patterns like `tests/<feature>/<unit>.test.*`.
- Add tests for all new logic and bug fixes.
- Cover success, failure, and edge cases.
- Run tests locally before opening a PR.

## Commit & Pull Request Guidelines
Use clear, scoped commits with imperative summaries (Conventional Commits preferred), for example:
- `feat(auth): add token refresh handler`
- `fix(api): handle empty transcript response`

PRs should include:
- Purpose and scope.
- Linked issue (`Closes #123`) when applicable.
- Test evidence (command output summary).
- Screenshots or sample requests/responses for UI/API changes.

## Security & Configuration Tips
Do not commit secrets, credentials, or production data. Keep local configuration in ignored files (for example `.env`) and maintain `.env.example` with safe defaults.
