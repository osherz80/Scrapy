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
$env:PYTHONDONTWRITEBYTECODE = "1"
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

## Logging boundary

Application modules accept `ingestor.logging.types.Logger`; the CLI composition
root creates a logger once with `ingestor.logging.create_logger`. Child loggers
bind `run_id`, `entry_point`, chain/provider/branch IDs as those become available.
Use stable events and bounded counts/durations, never product rows or raw content.

```python
from ingestor.logging import create_logger

logger = create_logger(environment="development", version="local")
run_logger = logger.child(run_id="example", entry_point="probe")
run_logger.info("run.started", "Starting probe", chain_count=1)
logger.flush(timeout=1.0)
```

The factory accepts an injected `Transport` (`write(record)` / `flush()`). Console
JSON to stderr is the initial provider. A future provider needs an adapter and
composition-root wiring; ingestion call sites keep the same interface. Filtering,
context snapshots, serialization limits and redaction happen before delivery.
URL text is withheld entirely; exceptions expose their type only because messages
and tracebacks may include credentials or source content. Delivery failures are
contained; shutdown flush waits at most its configured budget (capped at five
seconds). A stalled flush runs in a daemon thread and cannot block process exit.

There is no centralized logging storage, dashboard or automatic alert delivery.
Future Actions logs use repository retention; database run records will supply
durable operational status when that slice is implemented.

## Configuration and CLI

`python -m ingestor.cli --help` needs no secrets and opens no connections.
`python -m ingestor.cli check-config` validates process settings only;
add `--require-database` to require a PostgreSQL URL. It does not test connectivity,
TLS, schema, privileges or source reachability. Exit codes: 0 valid, 2 invalid
configuration/arguments, 3 collection command not enabled. `refresh` and
`scheduled` currently validate inputs then exit explicitly with code 3; neither
publishes data or reports a successful refresh.

### Optional source feasibility probe

Install the locked candidate extra with the same project-local tool/cache settings:

```powershell
uv sync --project services/ingestor --extra dev --extra probe --locked
& .venv312/Scripts/python.exe -m ingestor.cli probe --chains rami-levy --max-branches 1
```

Omit `--chains` to evaluate every enabled chain sequentially. `--max-branches`
is a strict per-chain attempt cap (1..3); this diagnostic is separate from daily
random sampling and replacements. It never connects to the database, publishes
rows, or saves raw catalogs. Exit 1 means at least one chain failed validation.
Missing optional dependency produces a sanitized `PROBE_DEPENDENCY_MISSING` event.

The wrapper uses single-attempt HTTP, approved HTTPS hosts, a 40-request per-chain
budget (including authentication and redirects), at most five redirects per
request, and a 120-second per-chain deadline checked at network boundaries.
Each response and decompressed catalog is capped by
`PROVIDER_MAX_DECOMPRESSED_BYTES`; socket timeouts and overall deadlines also
apply. No environment proxy configuration is inherited. Portals that ignore
identity HTTP encoding currently fail explicitly rather than decompress without
a bound. Only one branch payload is inspected at a time, with XML entities/DTD
disabled; exceptions never dump source content.

Success means a full XML catalog passed basic price/identity validation locally.
Physical-branch eligibility, complete-roster pagination, package reconciliation,
random sampling, SQL publication and hosted reachability remain separate gates.
Review [provider evidence](docs/provider-evidence.md) before making coverage claims.

Carrefour and Shufersal recovery is deferred by user decision; see
[deferred work](tasks/deferred.md). Their public IDs remain in the registry, but
defaults exclude both and source adapters reject direct access with
`SOURCE_DEFERRED`, even if an explicit environment list includes their IDs.

The provider contract uses composite `(chain, subchain, store)` identities and
explicit physical/online/pharmacy/unknown branch classifications. Inventory
selection consumes the entire listing before returning candidates, chooses only
latest exact PriceFull files and keeps missing-time branches as failed-attempt
candidates rather than silently falling back to older files. Unknown branch types
are not guessed. Publisher-specific metadata mapping is still being implemented.

The sampling policy shuffles once using SystemRandom, then attempts three slots
with at most two replacements each. Its collection callback must completely
validate the catalog before returning; lazy, empty and failed results cannot
contribute observations. This policy is unit-tested but is not yet wired to
production parsing, aggregation or database publication.

The production parser and package normalizer are now implemented and tested
independently; [catalog validation](docs/catalog-validation.md) documents their
contracts, duplicate handling, source-time rules and local source evidence.
The live probe remains a basic diagnostic and does not assert full production
eligibility. Decimal reconciliation and the injected collection composition are
also implemented: complete inventory -> sampling -> parse -> reconcile. Empty or
fully conflicted results are explicitly nonpublishable. Backend name/token parity
uses pinned JavaScript-generated fixtures. Publisher roster/eligibility mapping,
the refresh worker and database publication are still open.

| Process variable | Default / requirement |
|---|---|
| DATABASE_URL | Required for refresh/scheduled or explicit database validation; never logged |
| ENABLED_CHAINS | Eight active chains by default; comma-separated distinct registry IDs |
| PROVIDER_TIMEOUT_SECONDS | 60, positive integer |
| PROVIDER_MAX_DECOMPRESSED_BYTES | 100000000, positive integer |
| REFRESH_STALE_HOURS | 48, positive integer |
| RUN_LEASE_SECONDS | 300, greater than heartbeat interval |
| RUN_TIMEOUT_MINUTES | 45, positive integer |
| HEARTBEAT_SECONDS | 30, positive integer smaller than lease TTL |
| LOG_PROVIDER | console (only supported provider initially) |
| LOG_LEVEL | info; debug/info/warn/error/fatal |
| LOG_ENV | development |
| APP_VERSION | GITHUB_SHA, then unknown if neither is supplied |

Environment files are never loaded automatically. Supply settings through the
launching process or hosted secret injection. Invalid-setting messages identify
the variable without echoing its value; argument errors also withhold raw input.
