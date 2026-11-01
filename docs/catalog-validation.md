# XML item collection and preservation

Production collection uses `xml_items.parse_xml_catalog` and
`aggregate_xml_catalogs`. It preserves source item text, empty elements and unknown
fields, with snake_case column names. Only ItemPrice is averaged across distinct
sampled branches. All other fields come from one deterministically selected
branch (newest catalog, then branch identity). Package disagreement no longer
removes a barcode; missing/invalid optional values are retained.

Raw PriceUpdateTime is text, not converted to UTC. Quantity='60.00', UnitQty='גרם',
QtyInPackage='12' and UnitOfMeasure='100 גרם' are independent original values.
QtyInPackage is not a weight/volume quantity. No unit/name/weighted conversion is
performed for persistence. The API must derive its consumer/search formats.

Download bounds, secure XML parsing, identity/complete-document validation and
three-slot sampling remain. Missing barcode/ambiguous or unsupported XML structure
fails a branch explicitly rather than publishing a partial interpretation. Duplicate
barcodes select their first occurrence per branch and are counted. Empty catalogs
fail. Numeric-invalid prices retain their selected source text rather than remove
the item; they are not silently treated as zero in an average.

Historical `parsing.py`, `aggregation.py` and `packaging.py` implement the earlier
normalized contract and retain unit coverage; production collection no longer
uses those transformations. Probe remains a legacy feasibility diagnostic. Use
pilot to exercise the actual production storage/aggregation path.
