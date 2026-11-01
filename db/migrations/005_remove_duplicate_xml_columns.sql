-- Retain alternate-field values before removing the redundant columns.
-- An existing canonical value (including an explicit empty string) wins.
UPDATE public.products SET
    manufacture_name = coalesce(manufacture_name, manufacturer_name),
    b_is_weighted = coalesce(b_is_weighted, bls_weighted),
    price_update_time = coalesce(price_update_time, price_update_date)
WHERE (manufacture_name IS NULL AND manufacturer_name IS NOT NULL)
   OR (b_is_weighted IS NULL AND bls_weighted IS NOT NULL)
   OR (price_update_time IS NULL AND price_update_date IS NOT NULL);
ALTER TABLE public.products DROP COLUMN manufacturer_name,
    DROP COLUMN bls_weighted, DROP COLUMN price_update_date;
