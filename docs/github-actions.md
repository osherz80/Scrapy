# GitHub Actions operation

The repository contains two workflows. CI runs on pushes, pull requests and
manual dispatch. Refresh runs on the native `0 6 * * *` schedule with
`timezone: Asia/Jerusalem`, or manual dispatch. Jobs use standard GitHub-hosted
Ubuntu 24.04 runners, Python 3.12.16, uv 0.13.6 and the committed dependency lock.
There is no always-on worker/server or workflow-global concurrency cancellation.

## Required setup

Add the existing direct connection string as the repository Actions secret
`DATABASE_URL`. It is injected into the refresh step's process environment only.
CI and source-only probes do not receive it. No workflow reads, uploads or creates
an `.env` file. No separate migration URL or CI password secret is required.

Add a second repository Actions secret, `DATABASE_CA_CERT`, containing the entire
downloaded PEM certificate including BEGIN/END CERTIFICATE lines. The refresh
step requires this secret, writes it without logging to `Temp/database-ca.crt`
with restricted file permissions, validates its PEM format, and sets
`DATABASE_SSLROOTCERT` to that path. The file is removed on step exit; probe/CI
steps receive neither database secret. Local CLI `.env` bootstrap does not
provision hosted secrets or certificates. Verified hosted connectivity remains
a launch prerequisite.

The public schema must already be migrated and the URL's login must have the
runtime permissions described in [database setup](database.md). Workflows never
apply production migrations automatically. The administrator's explicit migration
command remains `python -m ingestor.repository.migrate apply` with an authorized
process environment. Actual Supabase migration and verified hosted connectivity
have not been inferred from local tests.

Schedules use the repository's default branch, so merging the reviewed workflow
to `main` is a launch step. Feature-branch pushes run CI but do not activate that
branch's daily cron. The manual Run workflow UI likewise requires the workflow
to exist on the default branch. No merge or production refresh was performed as
part of writing these files.

## Daily refresh

GitHub targets 06:00 Israel time, including DST. Python independently checks the
local time: starts within 06:00–06:59 report their startup delay; earlier starts
skip, and starts from 07:00 onward fail as missed without opening a DB connection.
There is no automatic historical backfill or guaranteed exact-minute delivery.

The scheduler reserves all eight active chains and inserts one unique local-date
claim in the same transaction. A duplicate skips. Any existing chain reservation
causes a durable failed scheduled run with SCHEDULE_CONFLICT and no partial new
reservations. The daily claim remains consumed; recovery is an explicit manual
request, not an automatic retry that might overlap the original worker.

An admitted run proceeds through the regular worker: single claim, dedicated
heartbeat connection, sequential physical-branch sampling, full validation,
aggregation and fenced atomic publication. Carrefour and Shufersal stay deferred.
The 45-minute job timeout includes checkout/setup. Hard kills may prevent teardown;
five-minute lease expiry and later admission/status reconciliation recover them.

## Manual refresh and probe

Choose `mode: refresh` and supply `run_id` for a PENDING run already admitted by
the control layer. The workflow passes only that UUID to the worker; chain lists
and source URLs are not workflow inputs. Values pass through quoted environment
arguments rather than expression interpolation into shell commands. Missing or
invalid UUIDs fail without collection.

For source reachability diagnostics, choose `mode: probe`; leave `run_id` empty.
This runs the existing bounded one-attempt-per-chain feasibility probe across the
eight enabled chains. It has no database secret, no DB writes and no raw artifacts.
It is diagnostic evidence, not proof of complete roster/aggregation or production
capacity. The hosted pilot still requires separate recorded measurements.

## CI isolation and supply chain

CI receives no production URL. It starts PostgreSQL 18.3 pinned by OCI digest,
binding port 55439 only to loopback and storing its disposable cluster under
`Temp/pg-test/`. The job-local test database uses trust authentication; there is
no real password to store or accidentally reuse. Integration fixtures require the
explicit TEST_DATABASE_URL/test-name prefix and never fall back to DATABASE_URL.
The container stops even if a check fails; the hosted machine is discarded after
the job. No database dump, Temp directory or catalog artifact is uploaded.

Checkout is pinned to a full commit SHA with credential persistence disabled.
uv/actionlint release archives are pinned by version and SHA256, verified before
extraction. The custom setup action keeps managed Python under `.runtime/`, the
venv under `.venv312/`, and tool/download/build/cache scratch under root `Temp/`.
It disables Python shims/registration and uses locked dependencies. GitHub's own
runner/checkout infrastructure manages its platform files.

CI checks workflow syntax/expressions and shell commands with actionlint 1.7.12,
Ruff lint/format, the complete offline/PostgreSQL suite and sdist/wheel builds.
No rule/test is skipped to accommodate Actions. Required-check branch protection
is a separate repository setting, not implied by a green job.

## Logs and failure recovery

Read the Actions job logs for structured console events and sanitized error types.
Read refresh_runs/refresh_run_chains through the control repository for durable
state. Log retention follows repository settings; no external logging platform,
dashboards or automated alert delivery is provisioned here. Never upload raw
source payloads as debugging artifacts.

A failed source preserves that chain's prior catalog while other chains may
publish. A failed/partial worker exits nonzero. Duplicate deliveries skip before
collection. Failed retention maintenance is logged without undoing a committed
catalog. An interrupted run can be reconciled by status/admission; prepare a new
authorized manual run when its old reservations have been reconciled.

Official references: [schedule/timezone syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule),
[trigger behavior and delays](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[GitHub-hosted runners](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners).

## Hosted verification

[CI run 41227246927](https://github.com/osherz80/Scrapy/actions/runs/41227246927),
commit `a8d0b12`, passed on 2026-10-31. All job steps succeeded: tool/runtime setup,
workflow/Python quality checks, isolated PostgreSQL startup, 454 tests, package
build and container cleanup. The Linux suite used Python 3.12.16 and completed in
11.65 seconds. This verifies CI infrastructure and fixture-backed behavior; it
does not demonstrate retailer reachability from that runner or a Supabase refresh.

## Source-only production pilot

Manually dispatch Scraper CI with `source_pilot=true` on the selected branch.
The pilot job waits for verification, then runs the same production collection
path as refresh without receiving database credentials or publishing data. It
never runs on push or pull requests. Refresh also accepts `mode=pilot` once its
workflow is registered. See [pilot procedure and evidence](pilot-results.md).

Manual dispatch prerequisite: ci.yml with workflow_dispatch must exist on main
before GitHub exposes Run workflow. It is currently only on the feature branch.
Once registered on main, the branch selector can target feature/scraper-foundation.

## One-click full refresh

Choose Supermarket refresh > Run workflow, keep mode=refresh and leave run_id
empty. The runner creates/reserves the database run and immediately collects and
publishes all enabled chains. The optional run_id is only for API-admitted runs.
An overlapping active run fails admission safely; no operator UUID is needed.
