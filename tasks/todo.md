# Scraper implementation tasks

Status: scheduling/workflows implemented; hosted CI verified; production pilot remains open.
Check items only after evidence is recorded. Paths below are relative to this
scraper repository. Each task is a separate commit. The user authorized pushes;
deployment is not implied.

## 1. Reproducible Python bootstrap
Dependencies: none. Scope: medium (up to 5 files).
Files: `services/ingestor/pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `README.md`.
- [x] Python 3.12 runtime and editable package install work; exact dependencies are locked.
- [x] Test/lint/format/build commands are documented; tool caches/build scratch are directed to `Temp/`.
- [x] Verification: locked offline sync, Python 3.12.16, sdist/wheel build and Ruff. Initial future-slice tests fail with missing modules, as expected before implementation.

Bootstrap caveat: uv's first Python installation reported a user-level executable shim outside the project; the installer default was missed. It was not accessed or removed under the folder restriction. Documented installation now uses `--no-bin --no-registry`; subsequent tool operations use only the project-local runtime.

## 2. Stable chain registry
Dependencies: 1. Scope: small.
Files: `src/ingestor/chains.py`, `tests/unit/test_chains.py` (under `services/ingestor`).
- [x] Registry contains exactly the ten specified IDs with human display names; immutable records, no invented provider mappings.
- [x] Verification: 2 pytest cases pass (exact set/uniqueness/nonempty display names and immutable identity); Ruff lint/format pass.

## 3. Replaceable console logger
Dependencies: 1. Scope: medium (5 files).
Files: `logging/{__init__,types,transports}.py`, `tests/unit/test_logging.py`, `README.md`.
- [x] Typed contract, injected transport/factory, level filtering, bound context, UTC/common fields and JSON console output work.
- [x] Redaction includes nested fields, credential URLs, and exceptions; delivery/flush failure cannot change worker state; shutdown is bounded.
- [x] Verification: 13 logger tests cover capture transport, JSON/UTC schema, redaction, context snapshots, all severity thresholds, bounded recursive context, delivery failure and blocked flush. Full suite: 15 passed; Ruff lint/format and sdist/wheel build passed on Python 3.12.16.

Current boundary: tasks 1–4 are complete. User deferred Carrefour/Shufersal recovery on 2026-10-30; track it in `tasks/deferred.md` and continue task 6 with the eight locally passing chains. Task 7's HTTP/archive safety primitives and secure trial inspection were brought forward. No database connection or publication has occurred. See `docs/provider-evidence.md` for measured evidence and remaining hosted/eligibility gates.

Cleanup limitation: automatic approval review rejected recursive deletion of the verified task-created temporary/cache directories, including an explicit-literal-path retry, with `blocked by policy`. `Temp/`, initial Ruff/pytest caches, source/test bytecode caches and the empty runtime download scratch directory remain ignored locally. Future pytest/Ruff caches are configured under root `Temp/`. Cleanup remains unfinished; no alternate deletion mechanism was used to bypass the rejection.

## 4. Validated startup and CLI
Dependencies: 2, 3. Scope: medium.
Files: `config.py`, `cli.py`, `tests/unit/test_config.py`, `tests/unit/test_cli.py`, `README.md`.
- [x] Validate spec defaults and allowed chain IDs using injected/process environment, never dotenv; missing values produce sanitized errors.
- [x] CLI validates UUID/timezone/probe bounds, selects logger once and flushes on exit; unwired collection commands fail explicitly.
- [x] Verification: 46 configuration cases and 10 CLI cases, including help subprocess and sanitized errors. Full suite 71 passed; Ruff lint/format and sdist/wheel build passed on Python 3.12.16.

## Checkpoint: foundation
- [x] Tests, lint, formatting, build and CLI startup pass; no claim of operational collection.

## 5. Provider feasibility trial
Dependencies: 4. Scope: medium.
Files: `providers/trial.py`, `providers/inspection.py`, focused tests, `docs/provider-evidence.md`; dependencies use the existing `pyproject.toml` probe extra and `uv.lock` rather than a second requirements file.
- [x] Inspect and trial israeli-prices first; retain the guarded candidate for eight locally passing sources. User explicitly deferred Carrefour/Shufersal recovery and fallback evaluation to `tasks/deferred.md`.
- [x] Trial evaluates timestamp/identity/source package-pair coverage and memory path; explicitly list failed/unverified chains. Unit normalization and physical-branch classification are not claimed.
- [x] Verification: opt-in bounded local trial evaluated all ten, 8 passed; no raw-file artifacts. Deterministic failure/sanitization tests pass. Hosted coverage remains task 20.

Local recovery evidence: Carrefour's Stores file did not reveal aliases for the three filename/XML-ID mismatches. Fallback Shufersal listing parameters hit the same timeout (60,656 ms); no proxy/cost or weaker validation was introduced. Recovery/fallback orchestration is deferred by the user's request; the other eight chains proceed with the guarded candidate.

## 6. Provider adapter contract
Dependencies: 5. Scope: medium.
Files: `providers/types.py`, `providers/selected.py`, `tests/unit/test_provider.py`, `docs/provider-evidence.md`.
- [x] Typed composite branch IDs, physical-branch eligibility, pagination and latest exact PriceFull selection have verified mappings for the eight active sources.
- [x] No hidden retries or arbitrary workflow URLs; online-only/unknown classifications excluded. Only the eight specified grocery publishers are implemented; deferred sources fail before client creation.
- [x] Verification: strict roster/filename fixtures, explicit aliases/padding checks, three portal-family HTTP fixtures, completeness failures, unique composite mapping and download allowlisting. Bounded local inventories and three fully parsed/reconciled physical branches per active chain passed; see `docs/roster-mapping.md`. Hosted support is unverified.

Implemented: provider-independent immutable contracts, explicit branch-kind
classification, complete-inventory latest PriceFull selection, fail-closed
pagination and missing-time candidates, plus 11 focused contract tests. Actual
publisher Stores/filename mapping is now implemented in `providers/published.py`
and `roster.py`; unknown branch types are excluded rather than guessed. The SDK
remains diagnostic-only because its listing/retry behavior cannot enforce the
production boundary; the audited portal protocols use our bounded HTTP directly.

## 7. Bounded in-memory download
Dependencies: 6. Scope: medium.
Files: `providers/stream.py`, `tests/unit/test_stream.py`, `tests/fixtures/stream_cases.py`.
- [x] Timeout 60s, decompressed limit 100 MB, corrupt archives and truncation fail whole attempts; no raw disk/cache writes.
- [x] One streaming branch at a time; HTTP retry behavior stays inside application attempt budget.
- [x] Verification: existing gzip/bomb/corrupt/truncation/HTTP timeout/stream limits, new forbidden-write provider test, no retry/re-login path, plus local three-branch-per-source collection without raw artifacts.

## Checkpoint: source boundary
- [x] Adapter evidence recorded; limits and no-disk path proven for eight active sources. Hosted reachability remains separate.

## 8. Strict catalog parsing
Dependencies: 7. Scope: medium.
Files: `parsing.py`, `models.py`, `tests/unit/test_parsing.py`, `tests/fixtures/catalogs.py`.
- [x] Disable entities/DTD; preserve string codes, finite positive Decimal prices and item/catalog timestamp separation; interpret local times in Israel.
- [x] Reject invalid/empty catalogs and missing catalog times unless verified listing provides them; count invalid rows without retaining partial failed branches.
- [x] Verification: 24 parser cases plus 6 timestamp cases cover leading zeros, malformed tails, unsafe XML, duplicate SKUs/headers/fields, UTC/DST, aliases, UTF-16, unrepresentable optional dates and missing dimensions. Production parser also accepted one live catalog from each active chain; see `docs/catalog-validation.md`.

## 9. Package compatibility
Dependencies: 8. Scope: medium.
Files: `packaging.py`, `tests/unit/test_packaging.py`, `contracts/fixtures/package_cases.json`.
- [x] Equivalent units normalize; source quantity/unit remain a coherent pair; weighted flags and agreeing complete packaging signatures govern compatibility.
- [x] Unknown dimensions stay null; no density/name guessing; synthetic spec Tabasco 60 ml and QtyInPackage=0 semantics covered. Unverified QtyInPackage semantics are deliberately not used for identity or multiplication.
- [x] Verification: 12 package cases cover equivalent ml/l, mass/volume rejection, missing dimensions, conflicting flags/signatures and source/base pair coherence. An end-to-end offline collection test proves malformed-branch replacement before normalization.

Tasks 8–9 were implemented ahead of publisher-specific task 6 mapping because
they can be verified independently and are prerequisites for actual collection.
The callback path is tested with fixtures; no database writes or daily refresh
have run. Publisher roster/eligibility mapping remains open.
Verification after tasks 8–9: 184 tests passed; Ruff lint/format and sdist/wheel
build passed on Python 3.12.16. Local parser checks accepted all eight active
sources without storing raw catalogs. Existing temporary-cache cleanup remains
blocked by the earlier automatic approval review, as recorded above.

## 10. Chain aggregation
Dependencies: 9. Scope: medium.
Files: `aggregation.py`, `normalization.py`, `tests/unit/test_aggregation.py`, `contracts/fixtures/normalization.json`, `tests/unit/test_normalization.py`.
- [x] Distinct branch observations only; Decimal mean rounded once HALF_UP to 4 places, sample count 1..3, conflicts exclude product. Empty/fully rejected results have can_publish=false.
- [x] Deterministic newest catalog-observation metadata, ascending branch-ID ties, conservative oldest/newest source dates and API-compatible normalization fixtures. Item price-change time is preserved independently.
- [x] Verification: 16 Decimal cases, 13 reconciliation cases and 15 JavaScript golden normalization cases cover 1/2/3 branches, duplicate/conflict rules, leading zeros, source dates, package pairs and Hebrew/Unicode parity. Seven composition cases exercise complete inventory through averaged results without database writes.

Normalizer provenance: remote read-only Neuton-Back commit
`da310c2178ba9034773c14ae2bf087668423beff`, functions normalizeQuery/tokenize,
fixtures generated by Node 24.14.0. Existing backend code was not modified and
no file outside this scraper project was inspected. Numeric resource guards
reject excessive precision/exponents with diagnostics rather than approximating.

## 11. Random branch slots and replacements
Dependencies: 8, 10. Scope: small.
Files: `selection.py`, `tests/unit/test_selection.py`.
- [x] Shuffle eligible distinct candidates once with SystemRandom by default and injectable seeded RNG for tests.
- [x] Three slots, initial plus two replacements each, max nine attempts total; duplicate candidates rejected before collection, failed/lazy/empty results never accepted.
- [x] Verification: 12 deterministic sampling cases cover exhaustion, 0/1/2/3 successes, per-slot and total ceilings, sanitized correlated failures, missing metadata and deferred sources.

Policy was brought forward for independent verification. The collection callback
must return a fully parsed, validated nonempty catalog; production parser and
aggregation integration remain tasks 8–10/17. No live random refresh ran here.
Current verification: full suite 141 passed; Ruff lint/format and sdist/wheel
build passed on Python 3.12.16. Existing temporary/cache cleanup remains blocked
by the previously recorded automatic approval review; no deletion bypass was used.

## Checkpoint: collection semantics
- [x] Offline collection fixtures meet spec; full suite 235 passed, Ruff lint/format pass. Local source claims remain limited to the recorded eight-source parser/probe evidence; no live refresh or database publication has run. Publisher roster mapping remains task 6.

## 12. Private PostgreSQL schema
Dependencies: 2, 10. Scope: medium.
Files: `db/migrations/001_ingestion.sql`, `db/rollback/001_ingestion.sql`, `repository/migrate.py`, `tests/integration/test_schema.py`, `docs/database.md`.
- [x] Six domain tables plus private migration history, constraints/indexes, ten seeded chains (two deferred), and separate NOLOGIN read/control/writer groups. Public/anonymous grants revoked; worker cannot change enabled flags or truncate catalogs.
- [x] Explicit status/apply/latest-version rollback CLI, paired SQL, transaction advisory locking, forward/rollback checksum history, atomic batches, sanitized errors and verified remote TLS defaults. No environment files loaded or credentials embedded.
- [x] Verification: 32 real PostgreSQL integration cases and 244 offline cases passed (276 total) on an isolated PostgreSQL 18.3 cluster under Temp. Schema/index introspection, role denial, Supabase-style anonymous default grants, finite/positive prices, exact codes, rollback/reapply, failed-batch rollback, checksum drift, CLI operations and concurrent runners verified. Actual Supabase capacity remains a hosted measurement gate, not inferred from empty local tables.

Actual Supabase was not accessed. Per user instruction, administration uses the
existing DATABASE_URL, with optional MIGRATION_DATABASE_URL override. No extra
variable is required when DATABASE_URL has the needed privileges. Reviewed apply
and production ingestion-only LOGIN provisioning remain deployment work.
See `docs/database.md`. The temporary local server is
stopped after validation; temporary-file deletion remains subject to the prior
automatic approval-review rejection.

## 13. Atomic run admission
Dependencies: 12. Scope: medium.
Files: `runs/admission.py`, `repository/admission.py`, `tests/integration/test_admission.py`.
- [x] Ordered lease acquisition reserves all requested chains or none; create PENDING authorized run; disjoint requests may coexist.
- [x] Dispatch-pending TTL 30 minutes; uncertainty/rejection transitions preserve correct reservations.
- [x] Verification: real PostgreSQL conflicting/disjoint races using control-role connections, whole-request conflict rollback, injected permission failure after run insertion, uncertainty/acknowledgement/rejection, late rejection after claim, disabled/deferred sources, TTL and nested-transaction rejection. Nine offline validation cases also cover static sanitized errors and canonical order.

Admission/dispatch are library functions only; no workflow request or backend
endpoint is introduced. Expired leases deliberately remain reserved until task
16 reconciles old run state; they are never silently stolen. Worker claim must
lock the same run row before transitioning PENDING to RUNNING (task 14).
Full verification: 304 tests passed (48 real PostgreSQL integration cases),
Ruff lint/format and sdist/wheel build passed on Python 3.12.16.

## 14. Ownership and heartbeat
Dependencies: 13. Scope: medium.
Files: `runs/ownership.py`, `repository/ownership.py`, `tests/integration/test_ownership.py`.
- [x] Atomic PENDING claim once; random fencing token, GitHub execution correlation; duplicate delivery exits before collection.
- [x] Heartbeat every 30 seconds, TTL 300 seconds, fail closed on lost ownership; bounded job duration.
- [x] Verification: real PostgreSQL duplicate-claim and claim-versus-rejection races, ingestor-role renewal, missing/expired/wrong-token atomic failure, deadline cap, completed-chain exclusion, uncertainty resolution and old-token rejection after re-admission. Seven guard tests cover initial/background renewal failure, sanitized diagnostics, monotonic deadline, shutdown and no restart.

Ownership and guard libraries are implemented; task 17 must wire their dedicated
heartbeat connection and cancellation into the worker. Automatic abandoned-run
reconciliation remains task 16. Publication must independently fence under lock
(task 15); a successful heartbeat alone never authorizes an unfenced write.
Verification: the full 323-case suite passed, followed by the additional
old-owner/re-admission integration case (324 distinct tests total, 61 real
PostgreSQL cases). Ruff lint/format and sdist/wheel build passed on Python 3.12.16.

## 15. Atomic catalog publication
Dependencies: 10, 14. Scope: medium.
Files: `repository/publication.py`, `tests/integration/test_publication.py`, `tests/integration/test_visibility.py`.
- [x] Under locked valid fencing token, stage normalized rows and replace chain catalog/status in one transaction; no absent stale products remain after success.
- [x] Zero successful branches preserve old data; failures roll back; stale source watermark reported honestly.
- [x] Verification: 22 real PostgreSQL cases cover 1/3-branch publication, zero/all-rejected preservation, absent-product deletion and other-chain isolation, bounded attempt metadata, invalid inputs, duplicate publication, expired/wrong/newer owner, job deadline, failure after deletion/metadata update, expiry during insertion, redacted diagnostics and reader snapshot visibility.

Stages normalized parameter rows in memory for one chain; no staging tables,
extra database permissions or raw artifacts. Rechecks expiry after writes before
releasing the reservation. Per-chain outcomes commit atomically with the catalog;
whole-run finalization and abandoned-run recovery remain task 16. Supabase and
the CLI worker have not been invoked.
Verification: 346 tests passed, including 83 real PostgreSQL cases; Ruff
lint/format and sdist/wheel build passed on Python 3.12.16.

## 16. Recovery and retention
Dependencies: 15. Scope: medium.
Files: `runs/recovery.py`, `repository/recovery.py`, `tests/integration/test_recovery.py`.
- [x] Expired leases reconcile on admission/status; teardown fails unfinished chains without corrupting completed publication.
- [x] Prune operational records after 30 days without removing active/current references; no product history retained.
- [x] Verification: 15 PostgreSQL cases cover abandoned pending/running expiry, partial outcomes and finalization after last publication, status/admission recovery, missing ownership, deadline, concurrent disjoint re-admission after one shared old run, teardown token checks, recovery rollback on admission conflict, retention references/idempotency and a 100-record transaction bound. Nine offline cases verify final run status policy.

Earlier task 13's fail-closed expiry boundary is now replaced by explicit
reconciliation before admission/status. Completed outcomes/products are never
rewritten by recovery. Status and maintenance remain repository APIs; worker and
scheduled invocation are tasks 17–19. No Supabase operation has been performed.
Verification: the full 367-case suite passed, followed by the expanded 15-case
recovery integration suite (370 distinct tests total, 98 real PostgreSQL cases).
Ruff lint/format and sdist/wheel build passed on Python 3.12.16.

## Checkpoint: database correctness
- [x] Real PostgreSQL concurrency, rollback, fencing, crash, role and visibility tests pass; no mocks substituted for persistence/concurrency gates. Hosted reachability and capacity remain separate measurements.

## 17. Worker end-to-end
Dependencies: 4, 11, 16. Scope: medium.
Files: `runs/worker.py`, `cli.py`, `tests/integration/test_worker.py`, `tests/unit/test_worker_failures.py`.
- [x] Refresh reads authorized chains from run UUID and wires listing -> selection -> full parse -> aggregate -> fenced publish with heartbeat. Default factories now use the eight-source adapter and existing DATABASE_URL.
- [x] Per-chain partial success, run outcomes, cancellation/timeout and structured sanitized counts/durations have explicit behavior.
- [x] Verification: 12 fixture-backed PostgreSQL worker/CLI cases cover complete refresh, authorized chains, partial source failure, duplicate delivery, initial validation, heartbeat SQL failure, deadlines, cancellation, SIGTERM/keyboard interrupt, publication failure and cleanup. Eleven offline worker/CLI cases cover preflight without connection/secret echoes; startup also rejects limits beyond the repository's lease/job maxima.

Worker and default CLI composition are implemented. Refresh requires the admitted
run UUID and GitHub execution context, uses direct sessions from DATABASE_URL, and
never accepts workflow source URLs or arbitrary chain overrides. Connection policy
is shared with migration administration, including verified TLS and no env-file
loader. The default connector is tested on a disposable database with fixture
sources; all eight source adapters separately passed local read-only collection.
Cooperative safe points cannot forcibly cancel blocked calls; the hosted hard
timeout remains task 19. No Supabase operation has run. Next: schedule/workflows.
Verification: 395 tests passed, including 110 real PostgreSQL cases. Ruff
lint/format and sdist/wheel build passed on Python 3.12.16.

Latest verification after provider/default connector wiring: 434 tests passed,
including 111 real PostgreSQL cases; Ruff lint/format and sdist/wheel build passed.

## 18. Israel daily schedule

Dependencies: 13, 17. Scope: medium.
Files: `runs/schedule.py`, `repository/schedule.py`, `tests/unit/test_schedule.py`, `tests/integration/test_schedule_claim.py`.
- [x] Verified native Asia/Jerusalem 06:00 cron replaces the two-UTC-candidate fallback; application gate and atomic local-date claim reserve all eight active chains or record conflict. Deferred chains remain excluded.
- [x] Duplicate/delayed/missed invocations are explicit operational outcomes. 06:00–06:59 starts may run with delay reported; later starts fail without admission. A conflicted daily claim is retained; recovery uses manual admission/run-ID dispatch.
- [x] Verification: 14 schedule unit cases, CLI wiring, and five PostgreSQL integration cases cover winter/summer/DST transitions, midnight date conversion, no-I/O skips, concurrent claims, shared admission locks, failure rollback, durable conflicts and scheduled fixture-worker composition.

Schedule admission, the date claim, and all reservations commit together. Ordinary
manual admission retains its original transaction contract; an internal helper
allows scheduled composition without nested independent commits. Native timezone
support is verified in GitHub's official workflow syntax documentation. Workflow
configuration and actual hosted CI execution follow in task 19.
Verification: 454 tests passed, including 116 real PostgreSQL cases; Ruff
lint/format and sdist/wheel build passed on Python 3.12.16.

## 19. CI and refresh workflows
Dependencies: 17, 18. Scope: medium.
Files: `.github/workflows/{ci,refresh}.yml`, `docs/github-actions.md`.
- [x] Pinned runtime/dependency lock, contents-read permission, 45-minute refresh job, manual runId handoff and native 06:00 Asia/Jerusalem cron; no global cancellation.
- [x] Opt-in probe mode without DB secret, DATABASE_URL injected only into the refresh step, no raw artifacts; CI uses a loopback disposable PostgreSQL container with project-local data and no production credentials.
- [x] Verification: actionlint 1.7.12 and security inspection passed; hosted CI for commit a8d0b12 passed all checks, 454 tests (116 real PostgreSQL cases), distribution builds and container cleanup. [GitHub run](https://github.com/osherz80/Scrapy/actions/runs/41227246927).

Actionlint 1.7.12 validates both workflows locally. Checkout is pinned to its
verified full v6 commit; uv/actionlint archives and PostgreSQL 18.3 image are
checksum/digest pinned. Runtime/caches stay in workspace directories; managed
Python installation disables shims/registration. All 454 application tests pass
locally and on the GitHub-hosted Ubuntu runner. The hosted suite completed in
11.65 seconds with Python 3.12.16; no production URL was injected or accessed.

## Checkpoint: operational wiring
- [x] Offline/DB gates pass locally and on GitHub, workflows validate and hosted CI succeeds. Hosted retailer reachability, Supabase migration/connectivity and production capacity remain separate gates.

## 20. Controlled hosted pilot
Dependencies: 19. Scope: small.
Files: `docs/provider-evidence.md`, `docs/pilot-results.md`.
- [ ] Evaluate the eight active chains from the actual GitHub runner; normalized products demonstrated for reachable chains; failures have sanitized evidence. Carrefour/Shufersal stay deferred and are not accessed.
- [ ] Record exact dependencies, RAM/runtime, schema/unit/timestamp findings and direct database connectivity with verified TLS.
- [ ] Verification: controlled probe, then bounded refresh against explicitly designated environment; no raw catalogs in artifacts/logs.

## 21. Operator runbook
Dependencies: 20. Scope: medium.
Files: `README.md`, `docs/operations.md`, `docs/configuration.md`.
- [ ] Document setup, migrations/rollback, process env/secrets, dispatch/recovery, console logs and durable run status queries.
- [ ] Explain no centralized retention/alerts yet, transport replacement contract and unavailable-chain treatment.
- [ ] Verification: execute documented help/status/recovery procedure in designated environment; bootstrap may load root `.env` per user authorization, without displaying secrets.

## 22. Capacity and launch evidence
Dependencies: 21. Scope: small.
Files: `docs/pilot-results.md`, `tasks/todo.md`.
- [ ] Measure all-chain runtime, peak RAM, database tables/indexes/transient headroom and egress against actual free account limits.
- [ ] Verify consumer-facing SQL contract/current catalog semantics; API end-to-end search remains a separate integration dependency.
- [ ] Verification: full tests/lint/build, hosted report, account allowance evidence and reviewed release gate; explicitly list any remaining blockers.

## Checkpoint: release review
- [ ] All scraper acceptance criteria have evidence, zero secret/raw-file leakage, temporary task files cleaned, commits reviewable.
- [ ] Human reviews before production merge/deploy; no claim of API implementation or untested production readiness.

## Local environment bootstrap and migration diagnosis (2026-10-31)
- [x] User-authorized root `.env` bootstrap for CLI/migrations; process variables win, injected mappings bypass file access, malformed files fail without logging contents.
- [x] Reproduced local database status failure: TLS certificate verification fails with system roots and the bundled public CA store; no migration SQL executed.
- [x] Add project-local `DATABASE_SSLROOTCERT` support for workers/migrations while retaining `verify-full`; static TLS/authentication/DNS/timeout diagnostics keep driver text redacted.
- [x] Operator applied 001; agent applied user-authorized 002 using the supplied CA. Verified versions 001/002, seven public tables and absence of supermarket schema.

## Public schema correction (2026-10-31)
- [x] Preserve migration 001 checksums; migration 002 moves tables/function/history into public, removes legacy schema and retains data/ACLs. All runtime SQL updated.
- [x] Verification: 469 tests passed in full run; corrected schema fixture then 23 schema tests passed; 10 migration tests passed including upgrade preservation, rollback and idempotency. Ruff/build verified. Supabase migration 002 applied and checked directly.

## Production collection pilot command
- [x] Add source-only production path with existing sampling, parser, aggregation and limits; static per-chain outcomes and Linux RSS/runtime metrics. No database connection or persistence.
- [x] Four focused cases cover CLI wiring/no DB access, cleanup/failure continuation, deadline and deferred-source rejection. All 357 local unit tests, Ruff, actionlint and build pass.
- [x] Add opt-in manual CI pilot after verification so feature-branch source evidence can be collected without merging/deploying refresh. Hosted results pending.

## Operator documentation and hosted verification
- [x] Add configuration and operations guides covering bootstrap, CA secrets, roles, migrations, pilots, admission API/manual dispatch, durable status SQL, expiry/recovery, retention and replaceable console logging. Dedicated admission/dispatch CLI still absent.
- [x] Hosted CI on cdaa7ea passed 474 tests (357 unit + 117 PostgreSQL) in 12.78 seconds, quality gates, builds and cleanup: https://github.com/osherz80/Scrapy/actions/runs/41243414714.
- [x] Read-only Supabase baseline recorded in pilot results; worker credential is still elevated.
- [ ] Manual hosted source pilot: operator instructed how to dispatch; local CLI dispatch rejected with HTTP 401. No production refresh started.
