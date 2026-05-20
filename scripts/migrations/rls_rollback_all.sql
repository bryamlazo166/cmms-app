-- ============================================================================
-- ROLLBACK COMPLETO — Desactiva RLS en TODAS las tablas del esquema public.
--
-- Solo usar este script si, despues de activar RLS, la app dejo de funcionar
-- por algun motivo (no deberia, pero queda como red de seguridad).
--
-- Ejecutar en: Supabase SQL Editor -> New query -> pegar -> Run.
-- ============================================================================

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname = 'public'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I NO FORCE ROW LEVEL SECURITY',
            r.schemaname, r.tablename
        );
        EXECUTE format(
            'ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY',
            r.schemaname, r.tablename
        );
    END LOOP;
END $$;

-- Verificacion: lista tablas que aun tengan RLS activa (deberia salir vacio)
SELECT schemaname, tablename, rowsecurity, forcerowsecurity
FROM pg_tables
WHERE schemaname = 'public'
  AND rowsecurity = true
ORDER BY tablename;
