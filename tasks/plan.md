# Implementation plan: supermarket scraper

Source of truth: `SPEC-supermarket-scraper.md`, including section 9.1. Scope is the Python scraper, shared ingestion SQL, and its GitHub Actions jobs. No API implementation, Render deployment, or Neuton backend changes. Detailed execution and evidence live in `tasks/todo.md`.

## Working constraints

- Never read `.env`, including through dotenv, test discovery, subprocesses, or connection helpers. Assume configuration exists. Commands consume explicitly supplied process environment only; report missing configuration without values.
- All work stays within this project/workspace. Temporary downloads, test directories, and tool caches belong in the project-root `Temp/` directory; remove task-created temporary files after verification. Keep installed runtimes and virtual environments in ignored project directories.
- No paid services, proxies, raw catalog retention, branch-price persistence, or changes to the agreed sampling rules.
- Implement sequentially in tested, independently reversible commits. User authorized planning followed by implementation in this request; no additional plan-approval pause is needed. Review before merging/deploying.

## Architecture decisions

- Python 3.12 locally and in CI; exact dependency lock. Existing Python 3.11 environment is not the scraper runtime.
- Application logger protocol -> shared context/filtering/redaction facade and factory -> transport. Console JSON initially; injected capture transport proves replacement. No hosted logging prerequisite.
- Provider adapters expose branch identity, full-file publication metadata, and bounded in-memory streams. Trial israeli-prices first; adopt fallback only with recorded evidence. No claimed chain support without live verification.
- Fully validate a branch before its observations enter a chain aggregate. One branch at a time, no raw filesystem writes. Decimal arithmetic and coherent source/normalized package metadata.
- PostgreSQL owns runs, all-or-nothing admission, leases, daily claims, and fencing. Publication locks the current unexpired owner and atomically replaces one chain.
- Normalization fixtures bridge the future API contract; implement only ingestion normalization, not search scoring or HTTP routes.

## Dependency graph and ordered slices

1 runtime -> 2 chain registry -> 3 logger -> 4 configuration/CLI
-> 5 provider trial -> 6 adapter contract -> 7 bounded streaming
-> 8 XML validation -> 9 package reconciliation -> 10 aggregation -> 11 sampling
-> 12 schema -> 13 admission -> 14 claim/heartbeat -> 15 publication
-> 16 retention/recovery -> 17 worker -> 18 scheduling -> 19 workflows
-> 20 hosted pilot -> 21 operations -> 22 launch evidence.

Each task has a focused verification gate in `todo.md`. Checkpoints follow tasks 4, 7, 11, 16, 19, and 22. A failed provider gate is recorded and investigated before claiming coverage; it does not justify fabricating mappings or weakening ingestion semantics.

## Verification strategy

Use pytest deterministic tests for business rules and failure matrices, Ruff lint/format, and wheel builds. Write failing behavior tests before implementation. Use a disposable PostgreSQL database for transactional/concurrency/crash tests, never an implicitly selected production database. Integration tests require explicit `TEST_DATABASE_URL` from process environment; missing values are reported as unverified gates, not successful tests. Network smoke is opt-in; real hosted measurements are release evidence, not unit tests.

Verification commands from repository root, using the Python 3.12 virtual environment:

```powershell
python -m pytest services/ingestor/tests --basetemp=Temp/pytest
python -m ruff check services/ingestor
python -m ruff format --check services/ingestor
python -m build --no-isolation --outdir Temp/dist services/ingestor
```

CLI entry points are added in task 4; real collection is wired only in task 17. Database mutation commands must be explicit and documented; no automatic migration or refresh during import/startup.

## Risks and mitigations

| Risk | Impact | Evidence or mitigation |
|---|---|---|
| Library silently writes catalogs or retries | High | Inspect upstream implementation; instrument trial; replace download path before adoption |
| Hosted geo-blocking | High | Probe all ten from Actions; record unavailable sources, never purchase a proxy |
| Unknown package semantics | High | Verified field mappings, exact Tabasco fixtures, conservative conflicts |
| Expired workers publish | High | Lease row locking plus fencing in the publication transaction; real concurrent DB tests |
| DST or duplicate dispatch | High | Israel-local gate, daily unique claim, atomic PENDING claim |
| Direct database endpoint unavailable over runner network | Medium | Explicit hosted connection check; report need for session-pooler alternative if demonstrated |
| Free limits exceeded | High | Measure account allowance, runtime, RAM, full table/index size and staging headroom |
| Console logs leak credentials/source content | High | Redact before transport, safe exception representation, bounded structured summaries |
| Supplied XML fixture not present | Medium | Use clearly marked synthetic fixtures until exact supplied fixture is available; do not claim exact regression coverage |

## External evidence and inputs

No `.env` inspection is needed. Later tasks may require process-environment database credentials, a disposable PostgreSQL test endpoint, GitHub repository/workflow access, and any source account proven necessary by the provider trial. Record concrete missing inputs at the end of execution. Existing direct connection string presence is assumed, not tested. A hosted pilot and account-specific capacity checks cannot be inferred from local fixture success.

## Rollback and completion

Revert an individual code commit to undo a slice. Migrations have explicit corresponding rollback scripts and destructive-data caveats; never silently execute rollback. Preserve published data on zero-success collection and retain prior data on transactional failure. Completion requires all task gates, hosted reachability reports for ten chains, real DB integration evidence, measured free-tier fit, and an operator runbook. Foundation completion alone is not production readiness.
