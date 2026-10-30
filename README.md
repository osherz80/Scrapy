# Supermarket scraper

Python 3.12 ingestion worker. Requirements: [spec](SPEC-supermarket-scraper.md).
Execution order and evidence: [plan](tasks/plan.md), [tasks](tasks/todo.md).
The API and Neuton backend are outside this implementation's scope.

## Local development

Use Python 3.12 and uv. Keep the current shell inside this repository. Never read
`.env`; commands use explicitly supplied process environment only. No command below
connects to a database or source portal.

```powershell
New-Item -ItemType Directory -Force Temp | Out-Null
$env:TEMP = "$PWD/Temp"
$env:TMP = "$PWD/Temp"
$env:UV_CACHE_DIR = "$PWD/Temp/uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$PWD/.runtime/python"
$env:UV_PYTHON_BIN_DIR = "$PWD/.runtime/bin"
$env:UV_PROJECT_ENVIRONMENT = "$PWD/.venv312"
uv python install 3.12 --no-bin --no-registry
uv sync --project services/ingestor --extra dev --locked
& .venv312/Scripts/python.exe -m pytest services/ingestor/tests --basetemp=Temp/pytest
& .venv312/Scripts/python.exe -m ruff check services/ingestor
& .venv312/Scripts/python.exe -m ruff format --check services/ingestor
& .venv312/Scripts/python.exe -m build --no-isolation --outdir Temp/dist services/ingestor
```

The exact resolution is committed in `services/ingestor/uv.lock`; use `--locked`
to reject unexpected dependency changes. Build output and tool caches are temporary;
delete task-created contents of `Temp/` after verification. Runtime and virtual
environment directories remain ignored and local. On Linux use `.venv312/bin/python`.

Collection, database migrations, and hosted workflows are subsequent plan tasks.
Their existence or operational readiness must not be inferred from bootstrap tests.
