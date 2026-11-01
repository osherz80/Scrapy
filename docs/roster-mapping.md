# Publisher roster mapping

Local read-only evidence collected 2026-10-31. No Supabase connection, raw catalog
file or database publication was used. Carrefour and Shufersal were not accessed.
Shufersal was subsequently verified separately on 2026-11-01; see
[provider evidence](provider-evidence.md).

The first appendix of the [published transparency regulation](https://www.chamber.org.il/media/147842/7442.pdf)
defines store types 1 physical, 2 online, 3 physical/online. Physical and combined
branches qualify; online-only and unknown classifications are excluded. The
[regulator's XML guidance](https://www.chamber.org.il/media/148016/1002.pdf) names
the ChainId/SubChainId/StoreId/StoreType fields. These sources ground the field
mapping; this is not a claim about current legal obligations.

| Chain | Roster entries | Type 1 | Type 2 | Type 3 | Unknown |
|---|---:|---:|---:|---:|---:|
| rami-levy | 99 | 98 | 1 | 0 | 0 |
| yochananof | 51 | 50 | 1 | 0 | 0 |
| osher-ad | 24 | 24 | 0 | 0 | 0 |
| victory | 70 | 67 | 1 | 1 | 1 |
| mahsanei-hashuk | 71 | 64 | 4 | 3 | 0 |
| hatzi-hinam | 13 | 12 | 1 | 0 | 0 |
| tiv-taam | 54 | 47 | 7 | 0 | 0 |
| keshet-teamim | 28 | 23 | 3 | 2 | 0 |

All current rosters use nested SubChains/SubChain/Stores. Mahsanei HaShuk has five
groups, including two distinct groups bearing subchain 003. A parser must scope
subchain fields to each group without rejecting disjoint stores sharing that ID.
Duplicate composite store identities and conflicting fields fail the whole roster.

Catalog/roster checks found these explicit differences:

- Yochananof: roster 001/073, filename and XML 000/073.
- Tiv Taam: roster 001/156, filename and XML 000/156.
- Keshet: roster 001/104, filename omits subchain, XML 1/104.
- Rami Levy, Osher Ad, Victory, Mahsanei HaShuk and Hatzi Hinam matched the sampled
  roster composite identity directly, retaining numeric padding as published.

Branch IDs are numeric fields: padding-equivalent subchain/store IDs compare
equally. Chain IDs and product codes remain exact strings. Different numeric IDs
remain different; 001 versus 000 requires a documented, chain-specific adapter
mapping, not a global parser exception. Source catalog identity must still match
the mapped branch at every sampled download.

The physical Tiv Taam sample contained 12,568 rows, unlike the earlier 74-row
diagnostic. Eligibility comes from Stores metadata, never catalog size heuristics.
Keshet filenames commonly omit subchain and use a 12-digit minute timestamp;
Laib Stores files use a 14-digit timestamp plus a repeated six-digit time suffix.

The production adapter now validates Cerberus filtered totals across all pages,
rejecting changing totals, empty intermediate pages, repeated names and fractional
counts. Laib supplies one array snapshot; duplicate names or unexpected envelopes
fail closed. Hatzi Hinam follows advertised pagination links and rejects repeated
or incomplete pages. All routes use the bounded client with one HTTP attempt,
including authentication, no automatic re-login, and no filesystem writes.

The SDK remains an optional diagnostic dependency. The production boundary uses
the audited portal protocols directly because the SDK's large page request,
reauthentication retry and stop-on-repeated-page rules cannot prove this contract.
No new runtime dependency was introduced. Missing filename subchains are matched
only when the complete roster has one unique store-number match; explicit
subchains never use this fallback. Download URLs must belong to that inventory.

Complete inventory checks found the following physical branches with discoverable
full catalogs: Rami Levy 97, Yochananof 47, Osher Ad 24, Victory 65, Mahsanei HaShuk
66, Hatzi Hinam 12, Tiv Taam 47, Keshet 22. These are point-in-time local counts,
not promises of hosted reachability or fixed publisher inventories.

A bounded, read-only collection run then sampled three branches per chain using
seed 0, parsed full catalogs, and reconciled in memory. All 24 attempts succeeded;
no branch replacements or database writes occurred.

| Chain | Reconciled products | Invalid rows | Conflicting SKUs excluded | Seconds |
|---|---:|---:|---:|---:|
| rami-levy | 16,388 | 0 | 3 | 18.38 |
| yochananof | 13,716 | 0 | 3 | 10.02 |
| osher-ad | 4,030 | 0 | 3,863 | 7.30 |
| victory | 10,564 | 0 | 146 | 11.75 |
| mahsanei-hashuk | 13,713 | 0 | 170 | 14.26 |
| hatzi-hinam | 14,699 | 38 | 817 | 7.83 |
| tiv-taam | 21,706 | 0 | 10 | 11.88 |
| keshet-teamim | 16,723 | 0 | 263 | 26.22 |

Conflicts follow the existing conservative packaging/duplicate rules; unknown
dimensions were not guessed to increase coverage. True source dates were retained.
Raw data lived only in transient memory. Supabase/hosted execution and capacity
remain separate gates. Default CLI composition now selects this provider and the
existing DATABASE_URL direct-session factory. It has been tested against disposable
PostgreSQL with fixture sources; no live Supabase refresh has been performed.
