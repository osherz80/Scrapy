# Provider evaluation

Status: static audit and safety prerequisites in progress. No chain is claimed
reachable or production-supported from this audit alone.

## Candidate and reproducibility

Trial `israeli-prices==0.2.0` first (MIT). The optional `probe` extra and committed
uv lock pin the candidate and all dependencies. Upstream source audit is pinned to
[fb42e1f7fa99ce420f4a9827229c2724f1d63778](https://github.com/rxradar/israeli-prices/tree/fb42e1f7fa99ce420f4a9827229c2724f1d63778).
PyPI metadata was checked on 2026-10-30; installed behavior must also be tested.
Fallback selection remains deferred until the live trial yields evidence.

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
| shufersal | self-hosted | Not tested |
| carrefour | self-hosted | Not tested |
| rami-levy | Cerberus | Not tested |
| yochananof | Cerberus | Not tested |
| osher-ad | Cerberus | Not tested |
| victory | Laib | Not tested |
| mahsanei-hashuk | Laib | Not tested |
| hatzi-hinam | self-hosted | Not tested |
| tiv-taam | Cerberus | Not tested |
| keshet-teamim | Cerberus | Not tested |

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
