# Deferred source work

User decision (2026-10-30): Carrefour and Shufersal were not blockers for the
current scraper implementation. Shufersal was recovered on 2026-11-01; Carrefour
remains deferred.

## Carrefour
- Resolve filename/listing store IDs versus XML store IDs (416 -> 134, 471 -> 530,
  472 -> 903 observed locally). No verified alias is exposed by the inspected
  Stores file. Preserve strict identity validation; do not invent a mapping.
- Re-run local and hosted probes after resolving the source identity contract.

Carrefour retains its public ID in the registry. Collection defaults exclude it
and direct attempts report SOURCE_DEFERRED. Leave any existing published catalog
untouched. Deferral is not successful refresh coverage and must remain visible in
run/configuration reporting.

## Shufersal (recovered 2026-11-01)

The earlier local listing timeout was transient. The production provider now
implements the audited portal protocol directly through the bounded client:

- `GET /FileObject/UpdateCategory` with `catID=2` for PriceFull and `catID=5` for
  Stores, `storeId=0`, following the advertised last page to read the complete
  inventory rather than stopping on the first empty page.
- Stores and PriceFull files are served from signed Azure blob URLs, so the
  provider allows `*.blob.core.windows.net` only for this family.
- Shufersal's Stores name carries a date but not a full HHMMSS time
  (`Stores7290027600007-000-20261101-020.gz`); the filename date is used only for
  roster ordering. The XML exposes the exact `LastUpdateDate`/`LastUpdateTime`.
- A dedicated request budget covers the paginated listing plus sampled catalog
  downloads; all existing host, byte, time and no-disk limits still apply.

Local pilot evidence (`pilot --chains shufersal`, 2026-11-01): complete inventory
listed in ~42s, 418 roster branches (389 with a PriceFull file), 3/3 sampled
catalogs validated, 6,055 publishable products, exit 0. No database writes and no
raw files. Migration `006_enable_shufersal.sql` enables the chain in `public.chains`.
Hosted reachability remains a separate launch gate.
