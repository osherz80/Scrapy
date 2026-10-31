# Publisher roster mapping

Local read-only evidence collected 2026-10-31. No Supabase connection, raw catalog
file or database publication was used. Carrefour and Shufersal were not accessed.

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

The roster/filename parsing layer is implemented and fixture-tested. Production
listing/adapter integration remains in progress: Cerberus requires explicit
reported-total/pagination checks, Laib supplies one array snapshot, and Hatzi Hinam
publishes pagination links. No completeness claim follows from the SDK's large
page request or its stop-on-repeated-page behavior. The normal refresh CLI remains
gated until this boundary is verified.
