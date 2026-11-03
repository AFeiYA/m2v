# Supabase Database Security & RLS Migration

## Background & Architecture

This application uses a Python FastAPI backend connecting directly to PostgreSQL via `DATABASE_URL` (using SQLAlchemy / asyncpg). It does **not** rely on Supabase PostgREST Data API (`/rest/v1`) or client-side queries for application data.

By default, Supabase exposes tables created in the `public` schema to its REST/GraphQL APIs for the `anon` and `authenticated` roles. If Row Level Security (RLS) is disabled or unconfigured, anyone with the public Supabase Anon key could query tables directly.

This migration completely locks down the PostgREST / Data API surface:
1. Enables Row Level Security (`ENABLE ROW LEVEL SECURITY`) on every table in the `public` schema without defining any policies for `anon` or `authenticated`.
2. Revokes all permissions (`REVOKE ALL`) on all tables, sequences, and routines in `public` from `anon` and `authenticated`.
3. Alters default privileges so that any future tables created automatically deny access to `anon` and `authenticated`.

Because the Python backend connects via `DATABASE_URL` using the database owner/superuser role (`postgres`), it possesses the `BYPASSRLS` attribute in PostgreSQL and is completely unaffected by RLS.

---

## Migration Verification & Rollout Plan

### Step 1: Pre-flight Check on HF Space `DATABASE_URL`
Before executing the migration, inspect the `DATABASE_URL` configured in the Hugging Face Space secrets/environment:
* The connection string should use the `postgres` user, for example:
  `postgresql+asyncpg://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres`
  or direct:
  `postgresql+asyncpg://postgres:[password]@db.[project-ref].supabase.co:5432/postgres`
* Verify that the role has `BYPASSRLS`:
  ```sql
  SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'postgres';
  ```
  In Supabase, `postgres` has `rolbypassrls = true`.

### Step 2: Apply to Staging Project First
1. Open the Supabase Dashboard for the **staging** project -> **SQL Editor**.
2. Run the SQL script: `supabase/migrations/20261103000000_enable_rls_public_tables.sql`.
3. Run the verification queries included in the migration:
   ```sql
   -- Verify all public tables have RLS enabled (rowsecurity = true)
   SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public';

   -- Verify 0 rows returned for anon/authenticated
   SELECT grantee, table_name, privilege_type
   FROM information_schema.role_table_grants
   WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated');
   ```
4. Verify backend operations on staging:
   - User registration & login
   - Task creation & retrieval
   - Video export generation
   - Credit deduction & ledger writes

### Step 3: Apply to Production Projects (`m2v` and `m2vAsia`)
Once verified on staging:
1. Open the Supabase Dashboard for **m2v** -> **SQL Editor**, paste and execute the migration script. Run verification queries.
2. Open the Supabase Dashboard for **m2vAsia** -> **SQL Editor**, paste and execute the migration script. Run verification queries.
3. Monitor production logs on Hugging Face Space to confirm normal DB queries continue with zero interruption.
