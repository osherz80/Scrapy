# Scraper operator runbook

## Setup and schema

Follow [configuration](configuration.md), then from the repository root:

```powershell
& .venv312/Scripts/python.exe -m ingestor.cli check-config --require-database
& .venv312/Scripts/python.exe -m ingestor.repository.migrate status
```

check-config validates settings without opening a database connection. Migration
status connects and checks checksums without changing schema or data. Versions
001 and 002 should be present. All seven tables are in public. An operator runs
`python -m ingestor.repository.migrate apply` explicitly when new reviewed SQL
is ready. Ordinary worker jobs never run migrations.

Rollback is explicit: `python -m ingestor.repository.migrate rollback --version 002`
moves objects back to supermarket; code expecting public cannot run afterward.
Rollback of 001 deletes catalogs and run state. Do not use rollback to recover a
failed retailer download. Transactional publication preserves the previous
successful catalog when a replacement fails.

## Source pilot and hosted launch

Run `python -m ingestor.cli pilot` locally, or manually run Scraper CI on the
feature branch with source_pilot enabled after ci.yml with workflow_dispatch
exists on main. GitHub does not expose the manual button before that. See [pilot evidence](pilot-results.md).
Pilot success proves source collection, parsing and aggregation, not publication.

After source evidence and credential review, the refresh workflow must be
reviewed/merged to the default branch to activate its daily schedule and normal
manual UI. The schedule starts at 06:00 Asia/Jerusalem; 06:00–06:59 invocations
may start with delay reported. Earlier/duplicate invocations skip; later starts
fail without database admission. Carrefour and Shufersal stay disabled.

Manual refresh requires an admitted run UUID. Merely generating a UUID is not
admission. The Python repository API `admit_run(connection, chains)` atomically
creates the run and reserves all requested chains for 30 minutes. The connection
must be idle/autocommit with control permissions. Then dispatch refresh.yml with
mode=refresh and run_id equal to the returned ID. Record delivery through
`record_dispatch(connection, run_id, outcome)`: ACKNOWLEDGED for confirmed delivery,
UNCERTAIN for ambiguous delivery, REJECTED only for a definite rejection. Never
release reservations merely because a workflow request timed out. Repository
APIs exist; a dedicated admission/dispatch operator CLI is not implemented yet.

## Inspect and recover

These SQL queries are read-only and can run in Supabase SQL Editor:

```sql
SELECT id, status, origin, created_at, started_at, finished_at, error_code, github_run_id
FROM public.refresh_runs ORDER BY created_at DESC LIMIT 20;

SELECT chain_id, status, attempt_count, successful_branch_count, product_count, error_code
FROM public.refresh_run_chains
WHERE run_id = '<run UUID>'::uuid ORDER BY chain_id;

SELECT id, product_count, catalog_updated_at, source_updated_at, current_run_id
FROM public.chains ORDER BY id;
```

Stale display data alone does not indicate failure: check durable chain outcomes
and source times. A failed chain keeps its last published catalog. Do not delete
lease rows or change run statuses manually. `get_run_status(connection, run_id)`
reconciles expiry before returning status; it can write recovery transitions.
`reconcile_expired(connection)` reconciles abandoned pending/running runs with
control permissions. Healthy leases are preserved; completed chains stay intact.
After reconciliation, admit a fresh run and dispatch its returned UUID.

Pending reservations expire after 30 minutes; worker leases last at most five
minutes with a 30-second heartbeat; runs have a 45-minute deadline. A hard-killed
runner may leave state pending until subsequent admission/status reconciliation.
Retention removes at most 100 terminal runs older than 30 days per successful
cleanup invocation, preserving current publication references and active leases.

## Logs and failure handling

JSON console logging is the initial provider. GitHub retains workflow logs under
the repository's configured Actions policy; there is no centralized log platform,
durable log archive, external alerting or automatic alert delivery yet. Durable
run tables are the operational record, not full application logs. Review failures
in Actions and the SQL queries above. Logs contain counts, static codes and safe
context; credentials, raw XML and product catalogs are excluded.

Application code uses the Logger protocol/facade; provider-specific output lives
behind Transport. A future provider replaces/adds the transport at the composition
root while preserving filtering, redaction, context and bounded flushing.

DATABASE_TLS_VERIFICATION_FAILED: verify the CA certificate and path/secret.
DATABASE_AUTHENTICATION_FAILED: check the configured database credentials.
DATABASE_CONNECTION_TIMEOUT: inspect runner connectivity and database availability.
Source HTTP/roster/parser failures: inspect the static per-chain code and pilot
evidence. Do not weaken TLS, parser validation, timeouts or branch classification
to force a run through. See [database details](database.md).
