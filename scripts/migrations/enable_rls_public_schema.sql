-- ============================================================================
-- enable_rls_public_schema.sql
--
-- Habilita Row Level Security (RLS) en TODAS las tablas del esquema `public`
-- de Supabase, sin crear politicas. Resultado:
--
--   * La API REST de Supabase (anon / authenticated) queda BLOQUEADA en todas
--     las tablas — no puede leer, insertar, actualizar ni borrar nada.
--   * La conexion directa a PostgreSQL que usa la app Flask (DATABASE_URL con
--     usuario `postgres`) sigue funcionando porque el rol `postgres` tiene
--     `BYPASSRLS = true` por defecto en Supabase.
--
-- Este script es idempotente: ejecutarlo varias veces no causa efectos
-- adicionales.
--
-- Como ejecutar:
--   1) Entrar al panel de Supabase del proyecto cmms-industrial
--   2) Menu lateral -> SQL Editor -> New query
--   3) Pegar este script completo y presionar "Run"
--   4) Verificar el resultado: la consulta final debe mostrar 0 filas
--      (ninguna tabla quedo con RLS deshabilitado).
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
            'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
            r.schemaname, r.tablename
        );
        -- FORCE evita que el propietario de la tabla pueda saltarse RLS via
        -- PostgREST si Supabase rota credenciales. El rol `postgres` igual
        -- bypassa por su atributo BYPASSRLS.
        EXECUTE format(
            'ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',
            r.schemaname, r.tablename
        );
    END LOOP;
END $$;

-- ── Verificacion: lista tablas que aun NO tengan RLS (deberia salir vacio) ──
SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
  AND rowsecurity = false
ORDER BY tablename;
