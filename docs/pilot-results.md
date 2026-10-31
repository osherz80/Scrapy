# Controlled pilot evidence

## Procedure

The `pilot` command runs PublishedProvider, complete roster/catalog discovery,
full secure XML parsing, the existing three-branch sampling/replacement policy,
and aggregation. It does not create database connections, admit refresh runs,
publish products, or save raw catalogs. All eight active chains are selected by
default; Carrefour and Shufersal remain excluded. Logs contain counts and static
failure codes. A partial/failed pilot exits 1; all chains must produce publishable
aggregates to exit 0. The global execution budget is 45 minutes by default;
individual request/size limits remain unchanged.

Local execution from the repository root:

```powershell
& .venv312/Scripts/python.exe -m ingestor.cli pilot
```

Hosted execution requires ci.yml with workflow_dispatch to exist on the default
branch first. Then manually dispatch Scraper CI on the feature branch with
`source_pilot=true`. The source job runs only after verification succeeds and
receives no database secrets. Push/PR verification never accesses retailer sources.
Refresh workflow also supports `mode=pilot` once registered on the default branch.

Inspect `pilot.chain_completed`, `pilot.chain_failed` and `pilot.finished` JSON
events. Linux reports process peak RSS in bytes; the final event reports elapsed
milliseconds and coverage. No artifact contains raw product data. Workflow runtime
and RSS are evidence for this source-only process, not a completed publication or
database capacity measurement.

## Evidence status

- Local unit suite: 357 passed after pilot implementation.
- Existing public-schema integration coverage: 117 cases, including preserved
  data on 001→002 upgrade, permission boundaries, concurrency and rollback.
- Supabase migrations 001/002 applied and verified using the supplied CA and
  direct DATABASE_URL. No products have been published by the pilot.
- [Hosted CI run 41243414714](https://github.com/osherz80/Scrapy/actions/runs/41243414714)
  passed on cdaa7ea: 474 tests in 12.78 seconds, Ruff/actionlint, distribution
  builds and disposable PostgreSQL cleanup. The source-pilot job was skipped as
  intended on push; manual source execution remains pending.
- Read-only Supabase baseline (2026-10-31): database 11,245,235 bytes; seven
  scraper tables/indexes 180,224 bytes; products 0; runs 0. This is an empty-schema
  baseline, not a populated capacity estimate. Current connection can create roles;
  least-privilege worker LOGIN remains required for launch.
- Hosted source pilot and production publication/capacity evidence remain pending.
  CLI dispatch was rejected with HTTP 401; operator can manually run Scraper CI
  on feature/scraper-foundation with source_pilot enabled after ci.yml is
  registered on main. The missing default-branch workflow currently blocks the UI.
