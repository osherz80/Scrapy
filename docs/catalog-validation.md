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
