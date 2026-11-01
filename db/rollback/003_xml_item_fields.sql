-- Legacy schema cannot represent arbitrary XML values. Conversion/constraint
-- failure aborts this rollback atomically; no rows are silently discarded.
CREATE TABLE public.products_old_003 (
    chain_id text NOT NULL REFERENCES public.chains(id),
    item_code text NOT NULL CHECK (item_code <> ''),
    name text NOT NULL CHECK (btrim(name) <> ''),
    manufacturer text,
    currency text NOT NULL DEFAULT 'ILS' CHECK (currency = 'ILS'),
    price numeric(14,4) NOT NULL CHECK (price > 0 AND price < 'Infinity'::numeric),
    package_quantity numeric CHECK (package_quantity > 0 AND package_quantity < 'Infinity'::numeric),
    package_unit text CHECK (package_unit IN ('g', 'ml', 'unit')),
    source_quantity numeric CHECK (source_quantity > 0 AND source_quantity < 'Infinity'::numeric),
    source_unit_qty text CHECK (btrim(source_unit_qty) <> ''),
    item_price_updated_at timestamptz CHECK (isfinite(item_price_updated_at)),
    is_weighted boolean NOT NULL,
    sample_count integer NOT NULL CHECK (sample_count BETWEEN 1 AND 3),
    source_updated_at timestamptz NOT NULL CHECK (isfinite(source_updated_at)),
    newest_source_updated_at timestamptz NOT NULL CHECK (isfinite(newest_source_updated_at)),
    updated_at timestamptz NOT NULL DEFAULT now() CHECK (isfinite(updated_at)),
    run_id uuid NOT NULL,
    normalized_name text NOT NULL,
    name_tokens text[] NOT NULL CHECK (array_position(name_tokens, NULL) IS NULL),
    compatibility_metadata jsonb NOT NULL DEFAULT '{}' CHECK (
        jsonb_typeof(compatibility_metadata) = 'object'
        AND octet_length(compatibility_metadata::text) <= 4096
    ),
    PRIMARY KEY (chain_id, item_code),
    FOREIGN KEY (run_id, chain_id) REFERENCES public.refresh_run_chains(run_id, chain_id),
    CHECK (source_updated_at <= newest_source_updated_at),
    CHECK ((package_quantity IS NULL) = (package_unit IS NULL)),
    CHECK ((source_quantity IS NULL) = (source_unit_qty IS NULL)),
    CHECK ((package_quantity IS NULL) = (source_quantity IS NULL))
);
CREATE INDEX products_old_item_code_idx ON public.products_old_003(item_code);
CREATE INDEX products_name_tokens_idx ON public.products_old_003 USING gin(name_tokens);

INSERT INTO public.products_old_003 (
chain_id,item_code,name,manufacturer,price,is_weighted,sample_count,
source_updated_at,newest_source_updated_at,updated_at,run_id,normalized_name,name_tokens,
compatibility_metadata)
SELECT p.chain_id,p.item_code,coalesce(p.item_name,p.item_nm),
    coalesce(p.manufacture_name,p.manufacturer_name),p.item_price::numeric,
    CASE p.b_is_weighted WHEN '0' THEN false WHEN '1' THEN true ELSE NULL END,
    p.sample_count,coalesce(c.source_updated_at,p.updated_at),
    coalesce(c.source_updated_at,p.updated_at),p.updated_at,p.run_id,
    coalesce(p.item_name,p.item_nm),ARRAY[]::text[],p.xml_fields
FROM public.products p JOIN public.chains c ON c.id=p.chain_id;
DROP TABLE public.products;
ALTER TABLE public.products_old_003 RENAME TO products;
ALTER INDEX public.products_old_003_pkey RENAME TO products_pkey;
ALTER INDEX public.products_old_item_code_idx RENAME TO products_item_code_idx;
REVOKE ALL ON public.products FROM PUBLIC, supermarket_search, supermarket_control, supermarket_ingestor;
GRANT SELECT ON public.products TO supermarket_search;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.products TO supermarket_ingestor;
DO $$ DECLARE role_name text; BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
            EXECUTE format('REVOKE ALL ON public.products FROM %I',role_name);
        END IF;
    END LOOP;
END $$;
