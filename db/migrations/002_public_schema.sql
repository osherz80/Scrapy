-- Move existing objects without discarding data, constraints, indexes or ACLs.
ALTER TABLE IF EXISTS supermarket.chains SET SCHEMA public;
ALTER TABLE IF EXISTS supermarket.products SET SCHEMA public;
ALTER TABLE IF EXISTS supermarket.refresh_runs SET SCHEMA public;
ALTER TABLE IF EXISTS supermarket.refresh_run_chains SET SCHEMA public;
ALTER TABLE IF EXISTS supermarket.chain_leases SET SCHEMA public;
ALTER TABLE IF EXISTS supermarket.schedule_claims SET SCHEMA public;
ALTER TABLE IF EXISTS supermarket.schema_migrations SET SCHEMA public;
ALTER FUNCTION supermarket.distinct_values(text[]) SET SCHEMA public;
GRANT USAGE ON SCHEMA public TO supermarket_search, supermarket_control, supermarket_ingestor;
DROP SCHEMA supermarket;
