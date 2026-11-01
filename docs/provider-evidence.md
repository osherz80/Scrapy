# Provider evaluation

Update 2026-11-01: Shufersal production support was added and passed a local
production-collection pilot. Physical roster mapping and complete listing
boundaries are now implemented for the nine active chains; see
[roster evidence](roster-mapping.md). Production uses audited portal protocols
through our bounded client; the SDK remains diagnostic-only because its
pagination/retry rules cannot enforce the production contract. Carrefour remains
disabled pending its identity contract. Hosted reachability remains unverified.

Status: bounded local trials completed on 2026-10-30 (eight initial chains) and
2026-11-01 (Shufersal). Nine chains passed initial catalog validation; Carrefour
has an explicit identity failure. None is claimed production-ready or verified
from a GitHub runner. Physical-branch eligibility remains unverified.

## Candidate and reproducibility

Trial `israeli-prices==0.2.0` first (MIT). The optional `probe` extra and committed
uv lock pin the candidate and all dependencies. Upstream source audit is pinned to
[fb42e1f7fa99ce420f4a9827229c2724f1d63778](https://github.com/rxradar/israeli-prices/tree/fb42e1f7fa99ce420f4a9827229c2724f1d63778).
PyPI metadata was checked on 2026-10-30; installed behavior must also be tested.
Candidate choice: retain the wrapped library for diagnostics and use audited
portal protocols for the nine passing local production sources. Keep failed
sources disabled for publication until their gates are resolved; do not
automatically replace a catalog with empty data.

## Integration findings

- Bytes-returning APIs can avoid disk. Destination arguments and parser paths
  enable filesystem operations; never use those modes here.
  [Public API](https://github.com/rxradar/israeli-prices/blob/fb42e1f7fa99ce420f4a9827229c2724f1d63778/src/israeli_prices/__init__.py).
- Default HTTP buffers full responses and makes up to three attempts. Replace it
  with bounded streaming and no automatic HTTP retry. Cerberus also reauthenticates
  internally, so budget all underlying requests and bypass its retrying branch
  download method. [HTTP](https://github.com/rxradar/israeli-prices/blob/fb42e1f7fa99ce420f4a9827229c2724f1d63778/src/israeli_prices/core/http.py),
  [Cerberus](https://github.com/rxradar/israeli-prices/blob/fb42e1f7fa99ce420f4a9827229c2724f1d63778/src/israeli_prices/chains/cerberus.py).
- The stock parser decompresses without a cap and uses standard ElementTree.
  Use bounded archive handling and an entity/DTD-disabled parser; validate catalog
  publication time separately. Do not use the stock parser in the live probe.
  [Parser](https://github.com/rxradar/israeli-prices/blob/fb42e1f7fa99ce420f4a9827229c2724f1d63778/src/israeli_prices/core/parse.py).
- File references omit subchain ID; price headers carry composite identity.
  Store number alone cannot identify a branch. Source dates need explicit
  Asia/Jerusalem interpretation. [Models](https://github.com/rxradar/israeli-prices/blob/fb42e1f7fa99ce420f4a9827229c2724f1d63778/src/israeli_prices/models.py).
- Paginated/truncated feasibility listings are not a complete physical-branch
  roster. Production eligibility, pagination and selection remain task 6 gates.

## Candidate mappings

These mappings are from source inspection, not live reachability evidence.

| Public ID / candidate slug | Portal family | Local / hosted result |
|---|---|---|
| shufersal | self-hosted | Production pilot passed 3/3 branches, 6,055 products; hosted not tested |
| carrefour | self-hosted | Local download/parse works, identity mismatch; hosted not tested |
| rami-levy | Cerberus | Local passed, 5,214 valid rows; hosted not tested |
| yochananof | Cerberus | Local passed, 11,774 valid rows; hosted not tested |
| osher-ad | Cerberus | Local passed, 6,127 valid rows; hosted not tested |
| victory | Laib | Local passed, 8,691 valid rows; hosted not tested |
| mahsanei-hashuk | Laib | Local passed, 12,382 valid rows; hosted not tested |
| hatzi-hinam | self-hosted | Local passed, 598 valid / 12 invalid rows; hosted not tested |
| tiv-taam | Cerberus | Local passed, 74 valid rows; hosted not tested |
| keshet-teamim | Cerberus | Local passed, 14,302 valid / 4 invalid rows; hosted not tested |

## Local run evidence

Command: `python -m ingestor.cli probe --max-branches 1`. Run ID
`86d80da8-0812-44fb-9aee-e63a2e9319a9`, 2026-10-30 11:20:07–11:21:22 UTC.
Duration: 75,359 ms; exit 1 accurately reports two failed chains. No raw catalog
was written to disk. Largest successful decompressed sample: 12,011,958 bytes
(Keshet Teamim); compressed 954,720 bytes. Byte sizes are payload sizes, not peak
process RAM. Peak RAM, free-tier limits and hosted execution are not measured yet.

Publication dates stayed distinct from ingestion time. Missing package pairs were
counted (e.g. Osher Ad 5,145 pairs out of 6,127 price/identity-valid rows). A pair
count does not prove recognized units or compatible packaging. Very small catalogs
(e.g. Tiv Taam 74 rows) require branch-format eligibility checks before sampling.

Carrefour source identity diagnostics found three independent mismatches:
filename store 416 -> XML store 134; 471 -> 530; 472 -> 903. XML chain ID matched.
Its current Stores file has 147 entries and lists 416, 471 and 472; its exposed
StoreID/BikoretNo fields did not supply the corresponding XML-ID mapping. No alias
was invented. Keep `IDENTITY_MISMATCH` until a verified mapping or corrected source
establishes the composite physical branch identity. A regression test preserves
this failure behavior.

Shufersal initially timed out after approximately 60 seconds before any branch
attempt. This did not prove geo-blocking or a permanent outage; later probes
showed the listing was reachable.

## Shufersal recovery (2026-11-01)

The diagnostic probe passed three branches (6,542 / 7,435 / 6,192 valid rows) in
about 7.6s. The production provider was then implemented directly against the
audited portal protocol rather than the SDK:

- `GET /FileObject/UpdateCategory` with `catID=2` (PriceFull) and `catID=5`
  (Stores), `storeId=0`, page 1..advertised-last. The portal exposes the last
  page in its navigation; stopping at the first empty page would silently bias
  branch sampling. A changed or non-contiguous listing fails as
  `INCOMPLETE_LISTING`.
- The full PriceFull inventory was 22 pages / 424 files at pilot time; the Stores
  listing has one file and no pagination.
- PriceFull and Stores links point to `pricesprodpublic.blob.core.windows.net`
  with short-lived SAS URLs, so Shufersal is the second family (with Hatzi Hinam)
  allowed to reach Azure blob hosts.
- Shufersal's Stores filename is `Stores7290027600007-000-20261101-020.gz`: it
  carries a date but an abbreviated trailing token instead of HHMMSS. The parser
  accepts the date for roster ordering; the XML's `LastUpdateDate` /
  `LastUpdateTime` remain the exact source time if needed. PriceFull names use
  the normal full timestamp.

Production pilot (`pilot --chains shufersal`, 2026-11-01): complete inventory in
~42s, 418 roster branches of which 389 had a PriceFull file, 3/3 sampled
catalogs validated with 4,611 / 3,277 / 3,204 rows, 6,055 aggregated products,
exit 0. No database writes and no raw files. Migration 006 enables Shufersal in
`public.chains`; hosted reachability is still unverified.

## Fallback assessment

Inspected OpenIsraeliSupermarkets source at
[f0c0aae31cc45231cc367467960223f935a192df](https://github.com/OpenIsraeliSupermarkets/israeli-supermarket-scarpers/tree/f0c0aae31cc45231cc367467960223f935a192df).
Its disk output is the default; an explicit bounded memory queue and nonpersistent
status handling would be required before importing its orchestrator. It is not
installed or adopted. Its Shufersal source uses the same portal/endpoint, omitting
the candidate's `storeId=0` parameter. A controlled endpoint comparison is recorded
separately; package-level fallback trial remains open. Switching libraries does not
by itself resolve Carrefour's conflicting publisher identifiers.

The fallback's Shufersal parameter variant also timed out locally: 60,656 ms,
`TIME_LIMIT`, no file downloaded. It did not provide evidence of a reachable
alternative endpoint. Further investigation belongs to source recovery/hosted
coverage rather than weakening the current timeout or adding a paid proxy.

## Safety verification

Decompression tests cover gzip/plain/ZIP exact limits, over-limit failure,
corrupt/truncated payloads, ambiguous ZIP contents and no disk extraction.
HTTP tests also cover single-attempt failures, response limits, session cookies,
blocked unapproved hosts/redirects, request budgets, expired deadlines and closing
an oversized stream without consuming the rest. The client requests identity HTTP
encoding and rejects other content encodings, so HTTP decompression cannot evade
the archive cap. Timeouts apply to network operations; a monotonic deadline is
checked before requests and between body chunks. A separate worker/job timeout
will enforce the overall production execution budget.
Secure parsing, local trials and hosted trials remain separate gates.
Raw portal payloads always remain in transient memory. Logs contain counts only.
