-- ============================================================================
-- PASO 2 — Prueba en UNA sola tabla antes del despliegue masivo
--
-- Activa RLS solamente en la tabla `audit_logs` (tabla de bajo trafico).
-- Despues:
--   * Recarga la app Flask y haz una operacion normal (listar OTs, crear un
--     aviso, ver indicadores, etc.). Debe funcionar igual que antes.
--   * Si TODO funciona ok -> sigue al PASO 3 (enable_rls_public_schema.sql).
--   * Si algo falla -> ejecuta el bloque ROLLBACK al final de este archivo
--     y avisa.
-- ============================================================================

-- Activa RLS solo en audit_logs
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs FORCE ROW LEVEL SECURITY;

-- Verifica que quedo activada (forcerowsecurity vive en pg_class, no en pg_tables)
SELECT c.relname              AS tabla,
       c.relrowsecurity       AS rls_activa,
       c.relforcerowsecurity  AS force_activa
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname = 'audit_logs';

-- Esperado: rls_activa = true, force_activa = true.


-- ┌─────────────────────────────────────────────────────────────────────────┐
-- │ ROLLBACK — Solo ejecutar si la app dejo de funcionar tras lo anterior  │
-- └─────────────────────────────────────────────────────────────────────────┘
--
-- ALTER TABLE public.audit_logs DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.audit_logs NO FORCE ROW LEVEL SECURITY;
