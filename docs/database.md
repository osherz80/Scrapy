# Private ingestion database

The versioned scripts live under `db/migrations/` with paired destructive rollback
scripts under `db/rollback/`. Run administration commands from a repository
checkout containing the same SQL assets as the application version. Installing
the Python wheel alone does not install the repository's SQL assets.

## Scope and permissions

The private `supermarket` schema contains chains, current products, runs,
per-chain run outcomes, leases and daily claims. There is no price-history or raw
catalog table. Ten chain IDs are seeded; Carrefour and Shufersal start disabled.
Operational retention/recovery and atomic publication are later implementation
tasks, not implied by the presence of tables.

Three NOLOGIN permission groups isolate services:

| Role | Access |
|---|---|
| supermarket_search | Read chains and current products only |
| supermarket_control | Read chains; read/write run coordination tables; no product access |
| supermarket_ingestor | Read/write products and coordination; update only publication columns of chains |

Runtime roles cannot create schema objects, create roles, truncate products,
change the chain registry/enabled flags, or read migration history. They are not
superusers and have no CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS attributes or
inherited external memberships. Existing unsafe roles with these application
names cause migration failure instead of being silently altered.

An administrator must separately provision each actual LOGIN with only the
appropriate group membership and set its password using the hosting platform or
an interactive administration tool. No password is embedded in migration files.
The existing DATABASE_URL can be used for setup when its user has schema/role
administration permissions. A separate MIGRATION_DATABASE_URL is optional if
credentials are split later. For production operation, the daily worker should
use an ingestion-only login rather than administrator permissions.

PUBLIC schema/table/function access is revoked. Existing `anon`/`authenticated`
grants are explicitly revoked when those Supabase roles exist. Do not expose this
schema through the browser Data API. RLS is not used as a substitute for private
schema and role privileges. Administrative/service secrets remain server-side.

Current publication references protect their run records from deletion. Retention
must preserve active leases/current catalogs and prune only unreferenced old runs.
The scheduler date claim is unique. Database constraints enforce positive finite
prices, 1..3 samples, coherent nullable package pairs, valid statuses and bounded
operational JSON. Parameterized repositories must still enforce transitions,
admission, ownership and fencing; those rules are not fully enforced by DDL.

## Explicit administration

Use the existing `DATABASE_URL` through the launching process or secret injection.
An optional nonempty `MIGRATION_DATABASE_URL` overrides it; no additional variable
is required for setup. No environment file is read, and credentials
are not accepted as command arguments or emitted in logs. The administrator needs
permission to create the private schema, objects and permission roles.

```powershell
& .venv312/Scripts/python.exe -m ingestor.repository.migrate status
& .venv312/Scripts/python.exe -m ingestor.repository.migrate apply
```

Status is read-only and does not bootstrap an empty database. Apply obtains a
database-scoped transaction advisory lock, validates migration history, then
applies all pending scripts and ledger updates in one transaction. Forward and
rollback checksums are stored; edited applied scripts, unknown history or missing
earlier versions fail closed. Line endings are normalized for Windows/Linux
checksum parity. Lock wait is bounded at 5 seconds and statements at 120 seconds;
these are small initial schema migrations, not an online-index build framework.

Remote connections force `sslmode=verify-full` and `sslrootcert=system`; the
connection timeout is 10 seconds. Default libpq password-file lookup is disabled
using a project-local nonexisting passfile path, and service/file-backed URL
options are rejected. PGSERVICE configuration is not supported. The sole
unencrypted exception is an explicit loopback database named `ingestor_test...`.
Actual Supabase TLS/certificate compatibility has not yet been verified; a trust
failure must be resolved rather than disabling verification.

Explicit rollback targets only the latest applied version:

```powershell
& .venv312/Scripts/python.exe -m ingestor.repository.migrate rollback --version 001
```

Rollback 001 removes all six domain tables and their data. It deliberately retains
the empty migration ledger/schema and cluster-wide NOLOGIN groups, which may be
used by other databases. Any LOGIN credentials/memberships are not deleted. This
is an operator-invoked destructive recovery action, not an automatic failure path.
Failed migration SQL rolls back automatically and leaves no partial batch state.

Commands exit 0 on success or 2 with a sanitized JSON error code on failure.
Help opens no connection. Migration SQL and driver exception messages are never
dumped in logs.

## Run admission library

`repository.admission.admit_run` accepts a dedicated idle autocommit connection
and an explicit tuple of authorized chain IDs. It validates registry/enabled
state, takes transaction advisory locks in canonical chain order, and commits
the PENDING run, per-chain records and 30-minute reservations together. A conflict
rolls back the complete request. Disjoint admitted runs can coexist; control-role
credentials suffice. Deferred chains remain unavailable even if enabled manually.

`record_dispatch` records ACKNOWLEDGED, UNCERTAIN or REJECTED delivery outcomes.
Uncertainty retains the original reservation without extending its expiry;
definitive rejection fails pending records and releases only that run's leases.
Updates lock the run row and ignore claimed/terminal/scheduled runs and stale
notifications. The worker claim must use the same run-row lock. These functions
do not send HTTP requests, read environment files or expose backend endpoints.

Expired leases currently fail closed rather than being silently stolen. Task 16
will reconcile abandoned run records before admission/status retry. Do not treat
this library alone as an operational refresh service.

## Worker ownership library

`repository.ownership.claim_run` locks a PENDING run and its ordered leases, checks
the complete authorized set and current database time, then records the GitHub
execution ID (`run_id` or `run_id:attempt`) and a new random fencing token. A
duplicate/terminal/unknown delivery returns no ownership. A missing/expired lease
fails without changing the run. Claim resolves manual dispatch uncertainty;
scheduled runs retain NOT_REQUIRED. Dispatch rejection and claim use the same
run-row lock, so only one can succeed.

`heartbeat` locks the run before ordered leases and renews every unfinished chain
atomically, validating token, expiry and deadline. Completed chains are excluded;
missing/expired/mismatched leases prevent all renewal. Defaults are 300-second
leases and a 2,700-second job deadline. Tests can shorten these values; extending
past the spec's five-minute TTL/45-minute maximum is rejected. The deadline also
caps each renewed lease. Old ownership cannot renew a later run's reservation.

`runs.ownership.LeaseGuard` performs an initial renewal, then runs a dedicated
heartbeat thread every 30 seconds. Its check fails after renewal errors, local
monotonic deadline or shutdown. Shutdown waits at most five seconds. The worker
must provide a separate connection with bounded I/O for renewal, call the guard
before more work, cancel/close in-flight work at teardown, and still verify the
token in the publication transaction. Python threads cannot forcibly cancel
blocked I/O. Recovery and CLI worker wiring remain later tasks.

## Atomic chain publication

`repository.publication.publish_collection` consumes one immutable
`ChainCollection` and its `RunOwnership`, using a dedicated idle autocommit
connection. It validates distinct attempts/successes, counters, exact chain
identity, aware source dates and already-rounded Decimal prices. It stages only
that chain's parameter rows in memory; no raw files, database staging tables or
additional TEMP/schema privileges are needed.

The transaction locks the run, run-chain outcome and chain lease, verifies the
fencing token/run/expiry/deadline, deletes the prior chain catalog, inserts all
replacement rows, and updates chain metadata and the successful outcome. Exact
string codes and true oldest/newest source dates are preserved. Absent products
are removed. A stale source date remains stale; ingestion time is separate.
After writes, the transaction checks current database time against the locked
lease again, then releases that chain's reservation. Expiry during a long insert
batch causes full rollback. Other chains are not replaced or released.

Zero successful branches or no surviving products records a failed chain with
NO_SUCCESSFUL_BRANCHES/NO_PUBLISHABLE_PRODUCTS and releases its reservation while
preserving existing products and chain publication metadata. Operational branch
metadata contains only bounded subchain/store IDs and success flags, including
failed attempts; no observed prices or raw payloads are retained.

Any SQL/constraint/ownership failure rolls back products, metadata, outcome and
lease changes. Repeating an already committed chain is rejected, protecting a
successful publication after an uncertain caller response. Per-chain success or
failure does not finalize the whole run; task 16 supplies finalization/recovery.
Durations, product counts and source age are logged through the existing facade;
driver error messages and product values are not logged.

Real PostgreSQL tests inject failures after deletion and during metadata update,
expire a lease inside insertion, and prove stale-owner rejection after a later
admission. A paused writer demonstrates complete old-catalog visibility until
commit, then complete new data/metadata; a REPEATABLE READ reader keeps its old
snapshot across that commit. This verifies repository transactions, not an API
search implementation or a live Supabase refresh.

## Verification

`python -m pytest` or the explicit `services/ingestor/tests/unit` path runs offline
tests by default. For the full suite, explicitly provide `TEST_DATABASE_URL` for
a disposable administrative database named `ingestor_test...`, then run:

```powershell
& .venv312/Scripts/python.exe -m pytest services/ingestor/tests --basetemp=Temp/pytest
```

Integration tests never fall back to DATABASE_URL and fail if the test URL is
missing or the database name is outside the test prefix. Schema tests roll back
their transactions. Migration tests create uniquely named test databases and
remove only those databases in cleanup. The test administrator needs CREATEDB
and CREATEROLE; use an isolated local cluster or dedicated disposable instance.
Do not designate production as a test target.

Local verification used the already installed PostgreSQL 18.3, a new loopback
cluster at port 55439, and data/logs exclusively under root `Temp/pg-test/`.
No Docker images, system database service, Supabase database or real source data
were used. Runtime-role grants, numeric/identity constraints, anonymous defaults,
checksum drift, rollback/reapply, failed-batch rollback, CLI operations and two
concurrent migration runners were tested against real PostgreSQL.

For capacity measurement on the designated environment, inspect table totals
(including each table's indexes/TOAST) without counting indexes twice:

```sql
SELECT c.relname, pg_total_relation_size(c.oid) AS bytes
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'supermarket' AND c.relkind = 'r'
ORDER BY bytes DESC;
```

This query is an operator tool; empty local table sizes are not free-tier capacity
evidence for full production catalogs.

The temporary server is stopped after verification. Files remain subject to the
previously recorded cleanup-policy rejection. Production setup still needs an
explicit administrator process environment and a reviewed apply; worker LOGIN
provisioning and actual hosted TLS verification remain launch gates.

References: [PostgreSQL privileges](https://www.postgresql.org/docs/18/ddl-priv.html),
[Psycopg transaction contexts](https://github.com/psycopg/psycopg/blob/master/docs/basic/transactions.rst).
