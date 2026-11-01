-- Preserve all item_name values; derive only the search token array.
ALTER TABLE public.products DROP COLUMN item_nm, DROP COLUMN xml_fields;
ALTER TABLE public.products ADD COLUMN name_tokens text[] NOT NULL DEFAULT '{}'
    CHECK (array_position(name_tokens,NULL) IS NULL);
UPDATE public.products SET name_tokens = array_remove(regexp_split_to_array(regexp_replace(translate(lower(coalesce(item_name,'') COLLATE "und-x-icu"),'''"׳״ּ',''),'(?<![0-9])\.|\.(?![0-9])',' ','g'),U&'[\0009\000a\000b\000c\000d\0020\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\2028\2029\202f\205f\3000\feff,-]+'),'');
CREATE INDEX products_name_tokens_idx ON public.products USING gin(name_tokens);
