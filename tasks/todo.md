# Scraper implementation tasks

Status: implementing foundation. Check items only after evidence is recorded. Paths below are relative to this scraper repository. Each task is a separate commit; no remote push or deployment is implied.

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

Current boundary: tasks 1–4 are complete. Task 5 has a functioning, guarded probe and local all-ten-chain evidence (8 passing, Shufersal timeout, Carrefour identity conflict); provider recovery/fallback runtime selection remains open. Task 7's bounded HTTP/archive primitives and secure trial inspection were brought forward before live collection. There has been no database connection or publication. Branch push succeeded at fc8b50a after the earlier 403 was resolved. See `docs/provider-evidence.md` for exact run IDs, measured byte counts and unresolved gates.

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
- [ ] Inspect and trial israeli-prices first; record pinned version, listing/full retrieval interfaces, disk/retry behavior; fallback evidence if needed.
- [x] Trial evaluates timestamp/identity/source package-pair coverage and memory path; explicitly list failed/unverified chains. Unit normalization and physical-branch classification are not claimed.
- [x] Verification: opt-in bounded local trial evaluated all ten, 8 passed; no raw-file artifacts. Deterministic failure/sanitization tests pass. Hosted coverage remains task 20.

Local recovery evidence: Carrefour's Stores file did not reveal aliases for the three filename/XML-ID mismatches. Fallback Shufersal listing parameters hit the same timeout (60,656 ms); no proxy/cost or weaker validation was introduced. The fallback package was source-audited but has not been installed/trialled as an orchestrator. Task 5's selection/recovery item stays open.

## 6. Provider adapter contract
Dependencies: 5. Scope: medium.
Files: `providers/types.py`, `providers/selected.py`, `tests/unit/test_provider.py`, `docs/provider-evidence.md`.
- [ ] Typed composite branch IDs, physical-branch eligibility, pagination and latest exact PriceFull selection have verified mappings.
- [ ] No hidden retries, arbitrary workflow URLs, online/pharmacy-only branches or unverified support claims.
- [ ] Verification: pagination/type/identity/eligibility/timestamp fixture cases against selected adapter.

## 7. Bounded in-memory download
Dependencies: 6. Scope: medium.
Files: `providers/stream.py`, `tests/unit/test_stream.py`, `tests/fixtures/stream_cases.py`.
- [ ] Timeout 60s, decompressed limit 100 MB, corrupt archives and truncation fail whole attempts; no raw disk/cache writes.
- [ ] One streaming branch at a time; HTTP retry behavior stays inside application attempt budget.
- [ ] Verification: generated gzip/bomb/corrupt/timeout cases and forbidden-write tests.

## Checkpoint: source boundary
- [ ] Adapter evidence recorded; limits and no-disk path proven before collection orchestration.

## 8. Strict catalog parsing
Dependencies: 7. Scope: medium.
Files: `parsing.py`, `models.py`, `tests/unit/test_parsing.py`, `tests/fixtures/catalogs.py`.
- [ ] Disable entities/DTD; preserve string codes, finite positive Decimal prices and item/catalog timestamp separation; interpret local times in Israel.
- [ ] Reject invalid/empty catalogs and missing catalog times unless verified listing provides them; count invalid rows without retaining partial failed branches.
- [ ] Verification: leading zeros, malformed XML, entity payloads, invalid rows and timestamps.

## 9. Package compatibility
Dependencies: 8. Scope: medium.
Files: `packaging.py`, `tests/unit/test_packaging.py`, `contracts/fixtures/package_cases.json`.
- [ ] Equivalent units normalize; source quantity/unit remain a coherent pair; weighted flags and verified packaging signatures govern compatibility.
- [ ] Unknown dimensions stay null; no density/name guessing; Tabasco 60 ml and QtyInPackage=0 semantics covered.
- [ ] Verification: equivalent ml/l, mass/volume rejection, missing dimensions, conflicting flags/signatures, coherent conversion amount.

## 10. Chain aggregation
Dependencies: 9. Scope: medium.
Files: `aggregation.py`, `normalization.py`, `tests/unit/test_aggregation.py`, `contracts/fixtures/normalization.json`, `tests/unit/test_normalization.py`.
- [ ] Distinct branch observations only; Decimal mean rounded once HALF_UP to 4 places, sample count 1..3, conflicts exclude product.
- [ ] Deterministic newest metadata/tie selection, conservative oldest/newest source dates and API-compatible normalization fixtures.
- [ ] Verification: 1/2/3 branches, duplicate/conflict cases, rounding, leading zeros and Hebrew normalization parity.

## 11. Random branch slots and replacements
Dependencies: 8, 10. Scope: small.
Files: `selection.py`, `tests/unit/test_selection.py`.
- [ ] Shuffle eligible distinct candidates once with secure runtime randomness and injectable seeded RNG for tests.
- [ ] Three slots, initial plus two replacements each, max nine attempts total; never repeat branch or merge a failed partial parse.
- [ ] Verification: deterministic failure matrices, exhaustion, 0/1/2/3 successful branches and replacement diagnostics.

## Checkpoint: collection semantics
- [ ] Offline collection fixtures meet spec; full suite/lint/build pass; source coverage claims remain evidence-based.

## 12. Private PostgreSQL schema
Dependencies: 2, 10. Scope: medium.
Files: `db/migrations/001_ingestion.sql`, `db/rollback/001_ingestion.sql`, `repository/migrate.py`, `tests/integration/test_schema.py`, `docs/database.md`.
- [ ] Six required tables, constraints/indexes, chain seeds and least-privilege read/control/writer roles; no public/anonymous access.
- [ ] Explicit migration and rollback commands; credentials never persisted in SQL or logs.
- [ ] Verification: real disposable PostgreSQL migrations/role-denial tests and size introspection.

## 13. Atomic run admission
Dependencies: 12. Scope: medium.
Files: `runs/admission.py`, `repository/admission.py`, `tests/integration/test_admission.py`.
- [ ] Ordered lease acquisition reserves all requested chains or none; create PENDING authorized run; disjoint requests may coexist.
- [ ] Dispatch-pending TTL 30 minutes; uncertainty/rejection transitions preserve correct reservations.
- [ ] Verification: concurrent conflicting/disjoint admissions, rollback and uncertain/definitive dispatch outcomes.

## 14. Ownership and heartbeat
Dependencies: 13. Scope: medium.
Files: `runs/ownership.py`, `repository/ownership.py`, `tests/integration/test_ownership.py`.
- [ ] Atomic PENDING claim once; random fencing token, GitHub execution correlation; duplicate delivery exits before collection.
- [ ] Heartbeat every 30 seconds, TTL 300 seconds, fail closed on lost ownership; bounded job duration.
- [ ] Verification: duplicate claim race, expiry/reclaim, failed heartbeat and stale-owner rejection.

## 15. Atomic catalog publication
Dependencies: 10, 14. Scope: medium.
Files: `repository/publication.py`, `tests/integration/test_publication.py`, `tests/integration/test_visibility.py`.
- [ ] Under locked valid fencing token, stage normalized rows and replace chain catalog/status in one transaction; no absent stale products remain after success.
- [ ] Zero successful branches preserve old data; failures roll back; stale source watermark reported honestly.
- [ ] Verification: 1-branch publication, zero preservation, crash injection, expired owner, concurrent reader snapshot and absent-product deletion.

## 16. Recovery and retention
Dependencies: 15. Scope: medium.
Files: `runs/recovery.py`, `repository/recovery.py`, `tests/integration/test_recovery.py`.
- [ ] Expired leases reconcile on admission/status; teardown fails unfinished chains without corrupting completed publication.
- [ ] Prune operational records after 30 days without removing active/current references; no product history retained.
- [ ] Verification: hard-kill expiry, partial outcomes, current/active retention and idempotent cleanup.

## Checkpoint: database correctness
- [ ] Real PostgreSQL concurrency, rollback, fencing, crash, role and visibility tests pass; do not substitute mocks for this gate.

## 17. Worker end-to-end
Dependencies: 4, 11, 16. Scope: medium.
Files: `runs/worker.py`, `cli.py`, `tests/integration/test_worker.py`, `tests/unit/test_worker_failures.py`.
- [ ] Refresh reads authorized chains from run UUID and wires listing -> selection -> full parse -> aggregate -> fenced publish with heartbeat.
- [ ] Per-chain partial success, run outcomes, cancellation/timeout and structured sanitized counts/durations have explicit behavior.
- [ ] Verification: fixture-backed end-to-end DB runs plus induced provider failure correlated through capture logger.

## 18. Israel daily schedule
Dependencies: 13, 17. Scope: medium.
Files: `runs/schedule.py`, `repository/schedule.py`, `tests/unit/test_schedule.py`, `tests/integration/test_schedule_claim.py`.
- [ ] 03:00/04:00 UTC candidates use Asia/Jerusalem 06:00 gate and atomic local-date claim, reserve all ten or report conflict.
- [ ] Duplicate/delayed/missed invocations are honest operational outcomes, not guaranteed delivery.
- [ ] Verification: winter/summer/DST transitions, concurrent daily claims and conflicting leases.

## 19. CI and refresh workflows
Dependencies: 17, 18. Scope: medium.
Files: `.github/workflows/{ci,refresh}.yml`, `docs/github-actions.md`.
- [ ] Pinned runtime/dependency lock, minimum permissions, 45-minute job, manual runId handoff and two cron candidates; no global cancellation.
- [ ] Opt-in probe mode, secret injection only through process env, no raw artifacts; CI runs offline suite and disposable PostgreSQL integration.
- [ ] Verification: workflow syntax/security inspection and actual CI run when repository access is available.

## Checkpoint: operational wiring
- [ ] Offline/DB gates pass and workflows validated; hosted source reachability is still separate.

## 20. Controlled hosted pilot
Dependencies: 19. Scope: small.
Files: `docs/provider-evidence.md`, `docs/pilot-results.md`.
- [ ] Evaluate all ten from actual GitHub runner; normalized products demonstrated for reachable chains; inaccessible ones have explicit sanitized failure evidence.
- [ ] Record exact dependencies, RAM/runtime, schema/unit/timestamp findings and direct database connectivity with verified TLS.
- [ ] Verification: controlled probe, then bounded refresh against explicitly designated environment; no raw catalogs in artifacts/logs.

## 21. Operator runbook
Dependencies: 20. Scope: medium.
Files: `README.md`, `docs/operations.md`, `docs/configuration.md`.
- [ ] Document setup, migrations/rollback, process env/secrets, dispatch/recovery, console logs and durable run status queries.
- [ ] Explain no centralized retention/alerts yet, transport replacement contract and unavailable-chain treatment.
- [ ] Verification: execute documented help/status/recovery procedure in designated environment; record missing inputs without inspecting `.env`.

## 22. Capacity and launch evidence
Dependencies: 21. Scope: small.
Files: `docs/pilot-results.md`, `tasks/todo.md`.
- [ ] Measure all-chain runtime, peak RAM, database tables/indexes/transient headroom and egress against actual free account limits.
- [ ] Verify consumer-facing SQL contract/current catalog semantics; API end-to-end search remains a separate integration dependency.
- [ ] Verification: full tests/lint/build, hosted report, account allowance evidence and reviewed release gate; explicitly list any remaining blockers.

## Checkpoint: release review
- [ ] All scraper acceptance criteria have evidence, zero secret/raw-file leakage, temporary task files cleaned, commits reviewable.
- [ ] Human reviews before production merge/deploy; no claim of API implementation or untested production readiness.
