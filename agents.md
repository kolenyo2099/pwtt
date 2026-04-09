# FlightWatch — Development Guidelines

## Environment

- **Always use UV** for virtual environments. All Python dependencies are installed via `uv`. Never use pip or poetry directly.
  ```bash
  uv venv && source .venv/bin/activate
  uv pip install -r requirements.txt
  ```

## Code philosophy

- **Write the simplest code that gets the job done.** Avoid clever abstractions, premature generalization, and unnecessary layers. If a plain function does the job, use a plain function.
- **Write commented code for a non-technical auditor.** Every module, function, and non-obvious block should have a plain-language comment explaining *what it does and why* — not just what the code literally says. Assume the reader can follow logic but has no coding background.
- **Write modular code.** Split concerns into small, focused files. No file should grow so large that it becomes hard to navigate. A good rule of thumb: if a file exceeds ~200 lines, consider splitting it.

## Project structure

- Keep backend and frontend clearly separated (`backend/`, `frontend/`).
- Data access, business logic, and API routes are separate modules — never mix them.
- Configuration lives in one place (a settings file or environment variables), never scattered across modules.

## Installer & run script

- **Always provide a `setup.sh` bash script** at the project root. Running it should:
  1. Create the UV virtual environment.
  2. Install all Python dependencies.
  3. Install frontend dependencies (npm/pnpm).
  4. Create the SQLite database if it doesn't exist.
  5. Print clear instructions for starting the app.
- **Always provide a `run.sh` bash script** that starts both the backend and frontend with a single command.

## Tauri compatibility

- The frontend (SvelteKit) must be buildable as a **Tauri MacOS desktop app**. Keep this in mind at every step:
  - Avoid browser APIs that are unavailable in Tauri's WebView.
  - Keep the SvelteKit app in SPA mode (or static adapter) so it can be embedded in Tauri.
  - The FastAPI backend runs as a sidecar process — design it to be startable as a subprocess from Tauri.
  - Do not hardcode ports or URLs; use environment variables with sensible defaults.

## Version control

- **Always initialize a git repository** at the project root on first setup (`git init`).
- The `setup.sh` script should run `git init` if no `.git` folder exists.
- Include a `.gitignore` that covers Python, Node, SQLite files, and environment files.

## Stack

- **Backend:** FastAPI + SQLite (via `aiosqlite` or `sqlite3`) + APScheduler for the poller.
- **Frontend:** SvelteKit (SPA/static mode for Tauri compatibility).
- **Data:** SQLite local database. Schema migrations handled with plain SQL files, not an ORM migration framework.

