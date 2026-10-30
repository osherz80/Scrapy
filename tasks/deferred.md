# Deferred source work

User decision (2026-10-30): Carrefour and Shufersal are not blockers for the current
scraper implementation. Continue with the eight other configured chains.

## Carrefour
- Resolve filename/listing store IDs versus XML store IDs (416 -> 134, 471 -> 530,
  472 -> 903 observed locally). No verified alias is exposed by the inspected
  Stores file. Preserve strict identity validation; do not invent a mapping.
- Re-run local and hosted probes after resolving the source identity contract.

## Shufersal
- Investigate listing timeouts, including the tested fallback parameter variant.
  Local timeout is not proof of geo-blocking. No paid proxy is authorized.
- Evaluate fallback adapter only when source access can be demonstrated safely;
  preserve no-disk, request and decompressed-byte limits.

Both chains retain their public IDs in the registry. Until explicitly resumed,
collection defaults exclude them and direct attempts report SOURCE_DEFERRED.
Leave any existing published catalog untouched. Deferral is not successful refresh
coverage and must remain visible in run/configuration reporting.
