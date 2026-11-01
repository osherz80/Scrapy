-- Reintroduce optional aliases. Their previous separate values cannot be
-- reconstructed; canonical columns retain all merged values.
ALTER TABLE public.products ADD COLUMN manufacturer_name text,
    ADD COLUMN bls_weighted text, ADD COLUMN price_update_date text;
