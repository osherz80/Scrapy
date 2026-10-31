CREATE SCHEMA IF NOT EXISTS supermarket;
REVOKE ALL ON SCHEMA supermarket FROM PUBLIC;

DO $$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['supermarket_search', 'supermarket_control', 'supermarket_ingestor']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', role_name);
        ELSIF EXISTS (
            SELECT 1 FROM pg_roles WHERE rolname = role_name AND
                (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls
                 OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member = pg_roles.oid))
        ) THEN
            RAISE EXCEPTION 'Application group role has unexpected elevated attributes';
        END IF;
    END LOOP;
END $$;

CREATE FUNCTION supermarket.distinct_values(values_array text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT SET search_path = pg_catalog
AS $$ SELECT cardinality(values_array) = (SELECT count(DISTINCT value) FROM unnest(values_array) AS t(value)) $$;
REVOKE ALL ON FUNCTION supermarket.distinct_values(text[]) FROM PUBLIC;

CREATE TABLE supermarket.chains (
    id text PRIMARY KEY,
    display_name text NOT NULL CHECK (btrim(display_name) <> ''),
    enabled boolean NOT NULL DEFAULT true,
    current_run_id uuid,
    catalog_updated_at timestamptz CHECK (isfinite(catalog_updated_at)),
    source_updated_at timestamptz CHECK (isfinite(source_updated_at)),
    product_count integer NOT NULL DEFAULT 0 CHECK (product_count >= 0)
);

CREATE TABLE supermarket.refresh_runs (
    id uuid PRIMARY KEY,
    origin text NOT NULL CHECK (origin IN ('SCHEDULED', 'MANUAL')),
    status text NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL_FAILED', 'FAILED')),
    requested_chains text[] NOT NULL CHECK (
        cardinality(requested_chains) BETWEEN 1 AND 10 AND array_ndims(requested_chains) = 1
        AND supermarket.distinct_values(requested_chains)
        AND requested_chains <@ ARRAY['shufersal', 'carrefour', 'rami-levy', 'yochananof', 'osher-ad',
            'victory', 'mahsanei-hashuk', 'hatzi-hinam', 'tiv-taam', 'keshet-teamim']::text[]
    ),
    created_at timestamptz NOT NULL DEFAULT now() CHECK (isfinite(created_at)),
    started_at timestamptz CHECK (isfinite(started_at)),
    finished_at timestamptz CHECK (isfinite(finished_at)),
    github_run_id text,
    dispatch_state text NOT NULL DEFAULT 'PENDING'
        CHECK (dispatch_state IN ('PENDING', 'ACKNOWLEDGED', 'UNCERTAIN', 'REJECTED', 'NOT_REQUIRED')),
    error_code text CHECK (error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    CHECK (status <> 'PENDING' OR started_at IS NULL),
    CHECK (status <> 'RUNNING' OR started_at IS NOT NULL),
    CHECK ((status IN ('SUCCEEDED', 'PARTIAL_FAILED', 'FAILED')) = (finished_at IS NOT NULL)),
    CHECK (started_at IS NULL OR started_at >= created_at),
    CHECK (finished_at IS NULL OR finished_at >= coalesce(started_at, created_at))
);

CREATE TABLE supermarket.refresh_run_chains (
    run_id uuid NOT NULL REFERENCES supermarket.refresh_runs(id) ON DELETE CASCADE,
    chain_id text NOT NULL REFERENCES supermarket.chains(id),
    status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 9),
    successful_branch_count integer NOT NULL DEFAULT 0 CHECK (successful_branch_count BETWEEN 0 AND 3),
    sampled_branch_ids jsonb NOT NULL DEFAULT '[]' CHECK (
        jsonb_typeof(sampled_branch_ids) = 'array' AND jsonb_array_length(sampled_branch_ids) <= 9
        AND octet_length(sampled_branch_ids::text) <= 4096
    ),
    product_count integer NOT NULL DEFAULT 0 CHECK (product_count >= 0),
    invalid_row_count integer NOT NULL DEFAULT 0 CHECK (invalid_row_count >= 0),
    conflict_count integer NOT NULL DEFAULT 0 CHECK (conflict_count >= 0),
    source_updated_at timestamptz CHECK (isfinite(source_updated_at)),
    error_code text CHECK (error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    error_message text CHECK (length(error_message) <= 512),
    started_at timestamptz CHECK (isfinite(started_at)),
    finished_at timestamptz CHECK (isfinite(finished_at)),
    PRIMARY KEY (run_id, chain_id),
    CHECK (successful_branch_count <= attempt_count),
    CHECK (status <> 'RUNNING' OR started_at IS NOT NULL),
    CHECK ((status IN ('SUCCEEDED', 'FAILED')) = (finished_at IS NOT NULL)),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
    CHECK (status <> 'SUCCEEDED' OR (successful_branch_count > 0 AND product_count > 0))
);

ALTER TABLE supermarket.chains ADD CONSTRAINT chains_current_run_fk
    FOREIGN KEY (current_run_id, id) REFERENCES supermarket.refresh_run_chains(run_id, chain_id);

CREATE TABLE supermarket.products (
    chain_id text NOT NULL REFERENCES supermarket.chains(id),
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
    FOREIGN KEY (run_id, chain_id) REFERENCES supermarket.refresh_run_chains(run_id, chain_id),
    CHECK (source_updated_at <= newest_source_updated_at),
    CHECK ((package_quantity IS NULL) = (package_unit IS NULL)),
    CHECK ((source_quantity IS NULL) = (source_unit_qty IS NULL)),
    CHECK ((package_quantity IS NULL) = (source_quantity IS NULL))
);
CREATE INDEX products_item_code_idx ON supermarket.products(item_code);
CREATE INDEX products_name_tokens_idx ON supermarket.products USING gin(name_tokens);
CREATE INDEX refresh_runs_status_created_idx ON supermarket.refresh_runs(status, created_at);
CREATE INDEX refresh_run_chains_chain_started_idx ON supermarket.refresh_run_chains(chain_id, started_at DESC);

CREATE TABLE supermarket.chain_leases (
    chain_id text PRIMARY KEY REFERENCES supermarket.chains(id),
    run_id uuid NOT NULL,
    owner_token uuid NOT NULL,
    expires_at timestamptz NOT NULL CHECK (isfinite(expires_at)),
    heartbeat_at timestamptz NOT NULL DEFAULT now() CHECK (isfinite(heartbeat_at)),
    FOREIGN KEY (run_id, chain_id) REFERENCES supermarket.refresh_run_chains(run_id, chain_id),
    CHECK (expires_at > heartbeat_at)
);

CREATE TABLE supermarket.schedule_claims (
    local_date date PRIMARY KEY CHECK (isfinite(local_date)),
    run_id uuid NOT NULL REFERENCES supermarket.refresh_runs(id) ON DELETE CASCADE
);

INSERT INTO supermarket.chains(id, display_name, enabled) VALUES
    ('shufersal', 'Shufersal', false), ('carrefour', 'Carrefour', false),
    ('rami-levy', 'Rami Levy', true), ('yochananof', 'Yochananof', true),
    ('osher-ad', 'Osher Ad', true), ('victory', 'Victory', true),
    ('mahsanei-hashuk', 'Mahsanei HaShuk', true), ('hatzi-hinam', 'Hatzi Hinam', true),
    ('tiv-taam', 'Tiv Taam', true), ('keshet-teamim', 'Keshet Teamim', true);

REVOKE ALL ON ALL TABLES IN SCHEMA supermarket FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA supermarket FROM PUBLIC;
GRANT USAGE ON SCHEMA supermarket TO supermarket_search, supermarket_control, supermarket_ingestor;
GRANT SELECT ON supermarket.chains, supermarket.products TO supermarket_search;
GRANT SELECT ON supermarket.chains TO supermarket_control;
GRANT SELECT, INSERT, UPDATE, DELETE ON supermarket.refresh_runs, supermarket.refresh_run_chains,
    supermarket.chain_leases, supermarket.schedule_claims TO supermarket_control, supermarket_ingestor;
GRANT SELECT ON supermarket.chains TO supermarket_ingestor;
GRANT UPDATE(current_run_id, catalog_updated_at, source_updated_at, product_count)
    ON supermarket.chains TO supermarket_ingestor;
GRANT SELECT, INSERT, UPDATE, DELETE ON supermarket.products TO supermarket_ingestor;
GRANT EXECUTE ON FUNCTION supermarket.distinct_values(text[]) TO supermarket_control, supermarket_ingestor;

-- Supabase default grants must not make the private schema browser-accessible.
DO $$
DECLARE role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA supermarket FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA supermarket FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA supermarket FROM %I', role_name);
        END IF;
    END LOOP;
END $$;
