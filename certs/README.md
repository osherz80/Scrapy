# Database CA certificate

Download your database CA certificate from Supabase Dashboard → Database Settings
→ SSL Configuration → Download Certificate. Save it here as `supabase-ca.crt`.
Certificate files in this directory are ignored by Git.

Add `DATABASE_SSLROOTCERT=certs/supabase-ca.crt` to the scraper-root `.env`, or set
the same variable in the launching process. Keep the existing `DATABASE_URL`.
Both workers and migrations use the CA with `verify-full`; verification is never
disabled. Hosted workers need the certificate provisioned inside their checkout
and the corresponding variable set too.

See https://supabase.com/docs/guides/database/connecting-to-postgres#ssl.
