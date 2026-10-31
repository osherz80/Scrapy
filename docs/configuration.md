# Scraper configuration

Run commands from the scraper repository with Python 3.12.16. Install locked
dependencies using the README setup procedure. CLI and migration entry points
load only the scraper-root `.env`; exported process variables override its values.
No parent-folder search, variable interpolation, or credential logging occurs.
Explicitly injected test mappings bypass file loading. Integration tests require
an exported TEST_DATABASE_URL for an isolated ingestor_test-prefixed database;
they never fall back to DATABASE_URL.

| Setting | Requirement/default |
|---|---|
| DATABASE_URL | Direct Postgres URL; required for refresh/scheduled and administration |
| DATABASE_SSLROOTCERT | Project-local CA file; system trust when absent |
| ENABLED_CHAINS | Eight active chains; deferred Carrefour/Shufersal excluded |
| PROVIDER_TIMEOUT_SECONDS | 60 seconds per request |
| PROVIDER_MAX_DECOMPRESSED_BYTES | 100000000 bytes |
| REFRESH_STALE_HOURS | 48 hours |
| RUN_LEASE_SECONDS | 300 seconds maximum |
| HEARTBEAT_SECONDS | 30 seconds; must be below lease TTL |
| RUN_TIMEOUT_MINUTES | 45 minutes maximum |
| GITHUB_RUN_ID / GITHUB_RUN_ATTEMPT | Execution correlation; GitHub provides these |
| LOG_PROVIDER / LOG_LEVEL | console / info |
| LOG_ENV / APP_VERSION | Environment label / deployed commit or release identifier |

Keep `DATABASE_SSLROOTCERT=certs/supabase-ca.crt` in local `.env` or the launching
process. Remote connections verify the server certificate and hostname. Local
test SSL exemptions apply only to loopback ingestor_test databases.

GitHub Actions requires repository secrets DATABASE_URL and DATABASE_CA_CERT.
The latter contains the complete PEM certificate. The refresh step writes it to
Temp/database-ca.crt, validates the format and removes it on exit. Its path is
set automatically. Neither secret is passed to CI verification or source pilots.

The daily worker should use a LOGIN with only supermarket_ingestor group
membership. Admission/recovery use supermarket_control; consumers use
supermarket_search. Migration administration needs separate elevated credentials
when the worker URL is restricted. LOGIN passwords must be set through the
platform or an interactive administration tool; no password belongs in SQL files.
All application tables live in public; these role names are permission groups,
not separate schemas. Browser roles have no grants on scraper tables.
