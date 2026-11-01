# XML item storage correction

User contract (2026-11-01): one current row per chain/barcode; continue averaging
ItemPrice across sampled branches. Copy all other fields from one selected branch
without normalization, filtering, unit conversion or timestamp conversion.
Use XML snake_case names and remove product compatibility_metadata,
source_updated_at and newest_source_updated_at. Do not apply production migrations
as part of implementation.

1. Add lossless text capture and the supplied Keshet regression fixture. Preserve
   empty fields, whitespace, lexical numbers and timestamps. Keep XML security,
   identity checks and complete-document validation.
2. Aggregate by exact barcode with deterministic metadata selection: newest
   catalog publication, then branch identity ascending. No package-compatibility
   exclusions. Retain items with unusual/missing optional values. Reject malformed
   structural identity rather than silently discard rows. ItemPrice is the only
   calculated XML field; a single contribution retains its original text.
3. Add a forward/rollback migration to replace product column aliases with XML
   snake_case names and text values; retain operational chain/run/sample context.
   Preserve existing known data on upgrade and clearly document that previously
   discarded XML fields require a refresh to recover. Never invent missing data.
4. Publish the new representation through the existing atomic fenced transaction.
   Update schema/publication/worker integration cases, spec, operations and API
   compatibility notes. Verify on disposable PostgreSQL; no production writes.

Unknown source fields must not be silently discarded. Preserve their exact named
values alongside the explicit known-field columns, without runtime DDL.

Acceptance: the supplied barcode retains quantity='60.00', unit_qty='גרם',
qty_in_package='12', unit_of_measure='100 גרם', unit_of_measure_price='21.50',
the full manufacture_item_description and unchanged PriceUpdateTime text.
