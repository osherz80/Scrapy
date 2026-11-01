-- XML text values replace normalized aliases. Existing lexical details that
-- were discarded by earlier versions cannot be reconstructed; refresh to refill.
CREATE TABLE public.products_xml_003 (
    chain_id text NOT NULL REFERENCES public.chains(id),
    price_update_time text,
    item_code text NOT NULL CHECK (item_code <> ''),
    last_sale_date_time text,
    item_type text,
    item_name text,
    manufacture_name text,
    manufacture_country text,
    manufacture_item_description text,
    unit_qty text,
    quantity text,
    unit_of_measure text,
    b_is_weighted text,
    qty_in_package text,
    item_price text,
    unit_of_measure_price text,
    allow_discount text,
    item_status text,
    item_nm text,
    manufacturer_name text,
    price_update_date text,
    is_weighted text,
    bls_weighted text,
    sample_count integer NOT NULL CHECK (sample_count BETWEEN 1 AND 3),
    subchain_id text,
    store_id text,
    xml_fields jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(xml_fields)='object'),
    updated_at timestamptz NOT NULL DEFAULT now() CHECK (isfinite(updated_at)),
    run_id uuid NOT NULL,
    PRIMARY KEY(chain_id,item_code),
    FOREIGN KEY(run_id,chain_id) REFERENCES public.refresh_run_chains(run_id,chain_id)
);
INSERT INTO public.products_xml_003 (
    chain_id,item_code,item_name,manufacture_name,item_price,quantity,unit_qty,
    b_is_weighted,price_update_time,sample_count,updated_at,run_id,xml_fields
)
SELECT chain_id,item_code,name,manufacturer,price::text,source_quantity::text,
    source_unit_qty,CASE WHEN is_weighted THEN '1' ELSE '0' END,item_price_updated_at::text,
    sample_count,updated_at,run_id,
    jsonb_strip_nulls(jsonb_build_object('item_code',item_code,'item_name',name,
        'manufacture_name',manufacturer,'item_price',price::text,
        'quantity',source_quantity::text,'unit_qty',source_unit_qty,
        'b_is_weighted',CASE WHEN is_weighted THEN '1' ELSE '0' END,
        'price_update_time',item_price_updated_at::text))
FROM public.products;
DROP TABLE public.products;
ALTER TABLE public.products_xml_003 RENAME TO products;
ALTER INDEX public.products_xml_003_pkey RENAME TO products_pkey;
CREATE INDEX products_item_code_idx ON public.products(item_code);
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
