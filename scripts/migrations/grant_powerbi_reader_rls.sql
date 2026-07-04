-- ============================================================================
-- grant_powerbi_reader_rls.sql
--
-- Crea una politica RLS de SOLO LECTURA para el rol `powerbi_reader` en todas
-- las tablas del esquema `public`.
--
-- Contexto: enable_rls_public_schema.sql habilito RLS sin politicas para
-- bloquear la API REST de Supabase (roles anon/authenticated). Efecto
-- colateral: el rol `powerbi_reader` (usado por el DSN ODBC de Power BI,
-- sin BYPASSRLS) empezo a recibir 0 filas en cada SELECT y los dashboards
-- quedaron vacios.
--
-- Este script agrega la politica `powerbi_read` (FOR SELECT TO powerbi_reader
-- USING (true)) tabla por tabla:
--   * Power BI vuelve a leer datos (solo SELECT; no puede escribir).
--   * anon / authenticated siguen bloqueados: no tienen ninguna politica.
--
-- Idempotente: usa DROP POLICY IF EXISTS antes de crear.
--
-- Como ejecutar:
--   Supabase -> SQL Editor -> pegar y Run
--   (o via la conexion directa postgres de la app)
-- ============================================================================

DO $$
DECLARE
    t record;
BEGIN
    FOR t IN
        SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS powerbi_read ON public.%I', t.tablename);
        EXECUTE format(
            'CREATE POLICY powerbi_read ON public.%I FOR SELECT TO powerbi_reader USING (true)',
            t.tablename
        );
    END LOOP;
END $$;

-- Verificacion: debe devolver una fila por tabla del esquema public
SELECT schemaname, tablename, policyname, roles
FROM pg_policies
WHERE schemaname = 'public' AND policyname = 'powerbi_read'
ORDER BY tablename;
