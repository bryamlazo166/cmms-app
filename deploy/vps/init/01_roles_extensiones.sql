-- Se ejecuta UNA vez, al crear el volumen de datos por primera vez.
-- Replica el layout de Supabase para que el restore del dump no falle:
--   * vector vive en schema public (igual que en Supabase)
--   * pgcrypto y uuid-ossp viven en schema extensions
--   * rol powerbi_reader existe (las politicas RLS lo referencian)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" SCHEMA extensions;

DO $$ BEGIN
    CREATE ROLE powerbi_reader NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Roles estandar de Supabase por si alguna politica futura los referencia
DO $$ BEGIN
    CREATE ROLE anon NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE ROLE authenticated NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE ROLE service_role NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
