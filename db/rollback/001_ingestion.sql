-- Destructive: removes the application's current catalogs and operational state.
-- Deliberately retain the schema/migration history and cluster-wide NOLOGIN roles.
DROP TABLE supermarket.products;
DROP TABLE supermarket.chain_leases;
DROP TABLE supermarket.schedule_claims;
ALTER TABLE supermarket.chains DROP CONSTRAINT chains_current_run_fk;
DROP TABLE supermarket.refresh_run_chains;
DROP TABLE supermarket.refresh_runs;
DROP TABLE supermarket.chains;
DROP FUNCTION supermarket.distinct_values(text[]);
REVOKE ALL ON SCHEMA supermarket FROM supermarket_search, supermarket_control, supermarket_ingestor;
