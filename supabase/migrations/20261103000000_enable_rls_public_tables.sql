-- ==============================================================================
-- Migration: Enable Row Level Security (RLS) on all public tables & revoke API access
-- Purpose: Protect Supabase public schema from PostgREST/Data API exposure.
-- Note: Python FastAPI backend accesses PostgreSQL directly via DATABASE_URL
--       connecting as the 'postgres' role (or table owner), which bypasses RLS (BYPASSRLS).
-- ==============================================================================

-- 1. Enable RLS dynamically on all existing tables in schema 'public'
DO $$
DECLARE
    tbl RECORD;
BEGIN
    FOR tbl IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', tbl.tablename);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated;', tbl.tablename);
        RAISE NOTICE 'Enabled RLS and revoked anon/authenticated access on public.%', tbl.tablename;
    END LOOP;
END $$;

-- 2. Explicit safeguards for known application tables (in case of schema variations)
ALTER TABLE IF EXISTS public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.video_exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.export_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.credit_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.credit_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.credit_lots ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.credit_allocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.alignment_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.song_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.version_trash ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.render_admission_mutex ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.motion_render_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.motion_export_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.billing_mutex ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.billing_checkouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.billing_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.billing_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.billing_events ENABLE ROW LEVEL SECURITY;

-- 3. Bulk revoke all permissions on tables, sequences, and routines in public schema
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL ROUTINES IN SCHEMA public FROM anon, authenticated;

-- 4. Prevent future tables created in schema 'public' from inheriting public API access
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON ROUTINES FROM anon, authenticated;

-- ==============================================================================
-- Verification queries (can be executed after migration to confirm):
--
-- 1. Check that all tables in public schema have RLS enabled (rowsecurity = true):
--    SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public';
--
-- 2. Check that neither 'anon' nor 'authenticated' has any grants in public schema (should return 0 rows):
--    SELECT grantee, table_name, privilege_type
--    FROM information_schema.role_table_grants
--    WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated');
--
-- 3. Confirm that current connection user (postgres) possesses BYPASSRLS / SUPERUSER:
--    SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;
-- ==============================================================================
