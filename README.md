# Supermarket scraper

Python 3.12 ingestion worker. Requirements: [spec](SPEC-supermarket-scraper.md).
Execution order and evidence: [plan](tasks/plan.md), [tasks](tasks/todo.md).
The API and Neuton backend are outside this implementation's scope.

## Local development

Use Python 3.12 and uv. Keep the current shell inside this repository. Local CLI
and migration launches automatically load this repository's `.env`; process
variables take precedence. File contents and credentials are never logged.
Explicitly injected mappings (including tests) bypass file loading. The local
development installation commands below do not connect to a database or source portal.

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
& .venv312/Scripts/python.exe -m pytest services/ingestor/tests/unit --basetemp=Temp/pytest
& .venv312/Scripts/python.exe -m ruff check services/ingestor
& .venv312/Scripts/python.exe -m ruff format --check services/ingestor
& .venv312/Scripts/python.exe -m build --no-isolation --outdir Temp/dist services/ingestor
```

The exact resolution is committed in `services/ingestor/uv.lock`; use `--locked`
to reject unexpected dependency changes. Build output and tool caches are temporary;
delete task-created contents of `Temp/` after verification. Runtime and virtual
environment directories remain ignored and local. On Linux use `.venv312/bin/python`.

Collection and database coordination are implemented and verified locally.
Source roster mapping is locally verified for eight chains. Hosted source/capacity checks remain gates;
operational readiness must not be inferred from fixture/bootstrap tests.

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
Actions logs use repository retention; database run records already supply
durable operational status independently of the console transport.

## Configuration and CLI

`python -m ingestor.cli --help` needs no secrets and opens no connections.
`python -m ingestor.cli check-config` validates process settings only;
add `--require-database` to require a PostgreSQL URL. It does not test connectivity,
TLS, schema, privileges or source reachability. Exit codes: 0 valid, 2 invalid
configuration/arguments, 3 command not enabled. `refresh --run-id <UUID>` is now
wired to live adapters and direct DATABASE_URL sessions. It consumes an existing
PENDING run admitted by the control library; it never creates authorization from
a newly invented UUID or takes a chain/URL override. GITHUB_RUN_ID is required,
with GITHUB_RUN_ATTEMPT defaulting to 1. Actions supplies these in hosted execution.
`scheduled` checks the Israel-local 06:00 hour, claims the local date once, reserves
the active chain set atomically, then runs the worker. Delayed starts within that
hour are logged; later starts fail without admission. Refresh
is an explicit network/database mutation command; check-config remains
connection-free. A real Supabase refresh has not been run during implementation.

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
are not guessed. Publisher metadata mapping and local collection evidence are
recorded in [roster mapping](docs/roster-mapping.md).

The sampling policy shuffles once using SystemRandom, then attempts three slots
with at most two replacements each. Its collection callback must completely
validate the catalog before returning; lazy, empty and failed results cannot
contribute observations. Fixture-backed worker tests now connect this policy to
the production parser, aggregation and real PostgreSQL publication.

The production parser and package normalizer are now implemented and tested
independently; [catalog validation](docs/catalog-validation.md) documents their
contracts, duplicate handling, source-time rules and local source evidence.
The live probe remains a basic diagnostic and does not assert full production
eligibility. Decimal reconciliation and the injected collection composition are
also implemented: complete inventory -> sampling -> parse -> reconcile. Empty or
fully conflicted results are explicitly nonpublishable. Backend name/token parity
uses pinned JavaScript-generated fixtures. Worker orchestration and atomic
publication and publisher roster mapping are implemented. The production adapter
uses audited portal protocols with our bounded HTTP client; the SDK remains
optional for probes and is not required by refresh.

The worker claims a PENDING run once, reads its chain list from PostgreSQL,
renews ownership on a dedicated connection, and collects/publishes chains
sequentially. Per-chain source failure allows other chains to proceed. Lease
loss, cancellation or deadline stops further work, closes providers/connections,
and uses a fresh connection for best-effort teardown of unfinished chains.
Completed publications survive teardown. Source attempts never swallow ownership
errors as ordinary replacement failures. SIGTERM is cooperative; keyboard
interrupts are handled, and the prior signal handler is restored.

Factories must bound source/database I/O and honor the supplied monotonic
deadline. Safe-point checks cannot forcibly interrupt blocked Python calls;
the hosted hard timeout and expiry recovery remain necessary. Worker result codes
are 0 success/duplicate skip, 1 failed/partial, 2 invalid preflight, 130 cancelled.
The CLI requires GITHUB_RUN_ID and optional GITHUB_RUN_ATTEMPT (default 1).
See [database behavior](docs/database.md) for publication, recovery and retention.

## Database schema and migrations

Private schema, least-privilege groups, checksum migration history and explicit
administration commands are implemented; see [database setup](docs/database.md).
Migrations 001 and 002 are applied to Supabase; scraper tables are in `public`.
Admin commands use the existing `DATABASE_URL` from process environment or root `.env`.
`MIGRATION_DATABASE_URL` is an optional override for separate credentials later;
the worker's production URL should eventually use an ingestion-only login.
If the database CA is not trusted by the system, download its CA certificate and
set `DATABASE_SSLROOTCERT=certs/supabase-ca.crt`. See [certificate setup](certs/README.md).
Both migrations and workers retain TLS certificate and hostname verification.

```powershell
& .venv312/Scripts/python.exe -m ingestor.repository.migrate status
& .venv312/Scripts/python.exe -m ingestor.repository.migrate apply
```

Rollback is explicit/destructive and requires the latest version; read the database
guide before using it. Ordinary pytest defaults to offline unit tests. Running the
full `services/ingestor/tests` path requires `TEST_DATABASE_URL` for a disposable
database named `ingestor_test...`; missing configuration fails rather than skips
integration coverage. Runtime LOGIN provisioning and hosted TLS/capacity checks
remain launch work; admission, fencing, publication and recovery are implemented.

| Process variable | Default / requirement |
|---|---|
| DATABASE_URL | Required for refresh/scheduled or explicit database validation; never logged |
| DATABASE_SSLROOTCERT | Optional project-local database CA path; defaults to system trust |
| GITHUB_RUN_ID / GITHUB_RUN_ATTEMPT | Required execution ID / attempt defaults to 1 for refresh |
| ENABLED_CHAINS | Eight active chains by default; comma-separated distinct registry IDs |
| PROVIDER_TIMEOUT_SECONDS | 60, positive integer |
| PROVIDER_MAX_DECOMPRESSED_BYTES | 100000000, positive integer |
| REFRESH_STALE_HOURS | 48, positive integer |
| RUN_LEASE_SECONDS | 300, maximum 300, greater than heartbeat interval |
| RUN_TIMEOUT_MINUTES | 45, positive integer, maximum 45 |
| HEARTBEAT_SECONDS | 30, positive integer smaller than lease TTL |
| LOG_PROVIDER | console (only supported provider initially) |
| LOG_LEVEL | info; debug/info/warn/error/fatal |
| LOG_ENV | development |
| APP_VERSION | GITHUB_SHA, then unknown if neither is supplied |

Environment files are never loaded automatically. Supply settings through the
launching process or hosted secret injection. Invalid-setting messages identify
the variable without echoing its value; argument errors also withhold raw input.

## GitHub Actions

[Workflow operation and setup](docs/github-actions.md) explains daily 06:00 Israel
refreshes, authorized manual run IDs, source-only probes and CI isolation. Add
the repository secret `DATABASE_URL`; no `.env` file is used or uploaded. CI
receives only a disposable local test database, never the production secret.
Refresh jobs are capped at 45 minutes and do not cancel unrelated runs.

The production schema must be explicitly migrated before the first refresh.
Schedules activate from the default branch after review/merge; pushing a feature
branch runs CI without activating that branch's cron. Workflows never apply
production migrations automatically. Supabase schema changes are applied only by explicit operator authorization.
