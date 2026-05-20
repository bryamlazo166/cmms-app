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

-- Verifica que quedo activada
SELECT tablename, rowsecurity, forcerowsecurity
FROM pg_tables
WHERE schemaname = 'public' AND tablename = 'audit_logs';

-- Esperado: rowsecurity = true, forcerowsecurity = true.


-- ┌─────────────────────────────────────────────────────────────────────────┐
-- │ ROLLBACK — Solo ejecutar si la app dejo de funcionar tras lo anterior  │
-- └─────────────────────────────────────────────────────────────────────────┘
--
-- ALTER TABLE public.audit_logs DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.audit_logs NO FORCE ROW LEVEL SECURITY;
