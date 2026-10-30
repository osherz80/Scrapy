# Catalog validation and package identity

The production parser accepts decompressed XML bytes, an expected composite branch
identity, its source chain ID and a verified publication timestamp. It returns a
nonempty immutable `ParsedCatalog` only after reading the entire document. Tail
corruption, entities/DTD, conflicting headers, missing identity and source-identity
mismatches fail the branch. It shares the secure XML reader with the diagnostic
probe. Raw payloads remain in memory and product objects hide their fields in repr.

Product codes remain exact strings. Price and package quantities use Decimal;
parsing does not round prices. Invalid price/name/code rows are counted and skipped.
Production rows also require an explicit 0/1 weighted flag (including verified
published field aliases); absent or unknown flags are not guessed as false. Missing
optional manufacturer, dimensions or item price-change dates remain null.

Identical duplicate SKUs count once. Contradictory duplicate observations remove
that SKU from the branch and carry its code in `conflicting_codes`; aggregation
must exclude such codes across the entire run, including other branches. A branch
with no remaining valid product fails. No partial parsed rows are exposed as a
successful branch result.

Catalog publication and item price-change dates remain separate UTC values.
Naive source dates use Asia/Jerusalem. Ambiguous/nonexistent catalog-local times
fail instead of guessing an offset. Invalid optional item times become null.
Neither download time nor LastSaleDateTime supplies catalog freshness.

## Package normalization

Known mass/volume/count aliases normalize to g/ml/unit. Conversion by powers of
1000 is exact and does not round dimensions. The original quantity/unit pair stays
together: 1 litre -> canonical 1000 ml, source pair 1/litre; 1000 ml -> canonical
1000 ml, source pair 1000/ml. A 60 ml package remains 60 ml even if its comparison
price basis is 100 ml. No name parsing or density conversion is performed.

Unknown/missing dimensions have null canonical and conversion pairs. Unknown units
may be compared only through a complete agreeing published positive quantity/unit
signature. Empty signatures do not prove compatibility. Weighted and sold-by-unit
items, different sizes and mass-versus-volume packages are incompatible.

QtyInPackage is parsed transiently; zero does not invalidate an item or become a
zero-size package. Its provider-specific semantics are not yet verified, so it
does not multiply dimensions or change compatibility. Verified future semantics
must be added with provider evidence and conflict tests before use. UnitOfMeasure
is retained transiently as a comparison basis, never substituted for UnitQty.

Fixture coverage includes synthetic Tabasco cases reconstructed from the spec;
the exact original supplied XML is not claimed as a checked-in regression fixture.
An integration test proves a malformed branch is replaced before valid catalogs
reach package normalization and that no partial product/price appears in logs.

## Local source verification (2026-10-30)

One catalog per active chain was downloaded and discarded in memory, sequentially.
The production parser accepted all eight. Counts below reflect that particular
sample, not daily sampling, branch eligibility or permanent chain coverage.

| Chain | Products | Invalid rows | Duplicate rows | Conflicting SKUs | Missing source package pair |
|---|---:|---:|---:|---:|---:|
| rami-levy | 5215 | 0 | 0 | 0 | 0 |
| yochananof | 11774 | 0 | 0 | 0 | 2 |
| osher-ad | 5985 | 0 | 0 | 0 | 894 |
| victory | 8691 | 0 | 0 | 0 | 159 |
| mahsanei-hashuk | 12380 | 0 | 1 | 1 | 204 |
| hatzi-hinam | 598 | 12 | 0 | 0 | 338 |
| tiv-taam | 74 | 0 | 0 | 0 | 0 |
| keshet-teamim | 14302 | 4 | 0 | 0 | 1037 |

Source package-pair counts indicate missing positive quantity/unit fields, not
verified unit recognition. Publisher roster mapping and physical eligibility are
still open. The parser validation used header subchain/store identity after
checking listing store equivalence; it does not prove the complete-roster mapping.
Hosted execution, aggregation, SQL publication and resource capacity remain later
gates. Carrefour and Shufersal were not accessed in this verification.

## Chain reconciliation

`aggregate_catalogs` now reconciles 0..3 distinct validated branch catalogs.
Duplicate branch inputs, more than three branches, mixed public/source chains,
naive catalog timestamps and duplicate observations inside a supplied catalog
fail closed. Conflicted SKUs reported by any branch are excluded across the run.
Cross-branch package/weighted conflicts also exclude the entire SKU. Descriptive
name/manufacturer differences do not create new identities or fuzzy grouping.

The mean uses only actual positive observations and rounds once to four decimal
places using HALF_UP. Missing branch observations never become zeros. Arithmetic
uses a fresh Decimal context with enough precision for the source operands;
caller precision/rounding traps cannot alter results. To bound numeric work from
untrusted feeds, prices with more than 1000 coefficient digits or an exponent
outside -1000..1000 are rejected for that product (`NUMERIC_LIMIT`), never
approximated. Rounded nonpositive results and means outside numeric(14,4) are
also excluded and counted. Raw source prices are never persisted or logged.

Metadata is selected from the newest contributing catalog publication (the
observation time), then ascending composite branch ID. PriceUpdateTime describes
price change, so it is preserved but does not rank name/manufacturer observations.
The selected source quantity/unit pair remains coherent with normalized dimensions.
Products keep oldest/newest contributing catalog times separately; chain freshness
uses the oldest actual published product watermark, not the new ingestion time.

Unknown complete agreeing package signatures may yield search-only averages with
null conversion fields. A single unknown-package observation also remains
searchable. Multiple empty/ambiguous signatures are excluded. Product sample
counts stay 1..3, and leading-zero SKU strings stay distinct. Comparison unit
prices are not copied from branches: future API derivation must use the mean.

`AggregationResult.can_publish` is false for zero successful branches or zero
remaining rows. Publication code must check this before replacing any catalog;
an empty result is not permission to delete old data. Database enforcement and
rollback tests remain task 15.

## Backend normalization parity

The importer uses the backend normalizeQuery/tokenize rules from
[Neuton-Back da310c2](https://github.com/Neuton-AI/Neuton-Back/blob/da310c2178ba9034773c14ae2bf087668423beff/src/lib/supermarket/prices.ts).
Fifteen golden cases were generated with the audited pure JavaScript functions
using Node 24.14.0; provenance lives in `contracts/fixtures/normalization.json`.
They cover Hebrew punctuation/dagesh, decimal dots, Unicode whitespace, repeated
tokens and representative case conversion. Python uses explicit ECMAScript
whitespace and ASCII digit rules; generic Python strip/regex whitespace would
change behavior. This is fixture parity, not exhaustive parity across future
Unicode-version changes. The existing backend was read remotely and not modified.

## Collection composition

`collect_chain` connects complete inventory -> sampling/replacements -> bounded
archive handling -> full parsing -> reconciliation using an injected Provider.
The caller owns provider lifetime and run/lease control. It returns averaged
products plus attempted/successful branch IDs and counts, not retained branch
catalogs. Structured events contain timings and counts only. Incomplete inventory
fails before sampling; total source failure produces a nonpublishable result.
Fixture tests cover 0/1/2/3 successful branches and replacement of a failed branch.
The actual publisher roster/eligibility adapter is still open; this function is
not wired into the reserved refresh CLI or database worker yet.
