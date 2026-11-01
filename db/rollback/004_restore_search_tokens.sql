-- Dropped item_nm/xml_fields values cannot be reconstructed by rollback.
DROP INDEX public.products_name_tokens_idx;
ALTER TABLE public.products DROP COLUMN name_tokens;
ALTER TABLE public.products ADD COLUMN item_nm text;
ALTER TABLE public.products ADD COLUMN xml_fields jsonb NOT NULL DEFAULT '{}'
    CHECK (jsonb_typeof(xml_fields)='object');
