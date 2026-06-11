-- ============================================================================
-- Modulo "Requerimientos" (Backlog Tecnico)
-- ----------------------------------------------------------------------------
-- Necesidades reconocidas pero NO planificadas: compras especiales,
-- fabricaciones, mejoras/upgrades y repuestos estrategicos sin OT ni aviso.
-- Una requisicion (purchase_requests) puede originarse ahora de un Requirement
-- (compra sin OT): por eso work_order_id pasa a ser NULLABLE y se agrega la FK
-- requirement_id.
--
-- Idempotente para PostgreSQL/Supabase. La app tambien aplica estos cambios en
-- el arranque via _ENSURE_INDEXES_SQL en app.py; este script sirve para
-- despliegues controlados o entornos con CMMS_AUTO_CREATE_TABLES desactivado.
-- ============================================================================

-- 1) Tabla principal
CREATE TABLE IF NOT EXISTS requirements (
    id                SERIAL PRIMARY KEY,
    code              VARCHAR(20) UNIQUE NOT NULL,
    title             VARCHAR(150) NOT NULL,
    description       TEXT,
    req_type          VARCHAR(30) NOT NULL,   -- COMPRA_ESPECIAL | FABRICACION | MEJORA | REPUESTO_ESTRATEGICO
    priority          VARCHAR(20) NOT NULL DEFAULT 'MEDIA',  -- BAJA | MEDIA | ALTA
    status            VARCHAR(20) NOT NULL DEFAULT 'REGISTRADO',
                      -- REGISTRADO | EN_EVALUACION | APROBADO | EN_GESTION | CERRADO | RECHAZADO
    area_id           INTEGER REFERENCES areas(id),
    line_id           INTEGER REFERENCES lines(id),
    equipment_id      INTEGER REFERENCES equipments(id),
    estimated_cost    DOUBLE PRECISION,
    quantity          DOUBLE PRECISION,
    unit              VARCHAR(20),
    target_date       VARCHAR(20),
    requested_by      VARCHAR(100),
    justification     TEXT,
    notes             TEXT,
    created_at        TIMESTAMP DEFAULT NOW(),
    closed_at         TIMESTAMP,
    converted_to_type VARCHAR(20),            -- OT | REQ | MANUAL
    work_order_id     INTEGER REFERENCES work_orders(id)
);

CREATE INDEX IF NOT EXISTS ix_req_status       ON requirements(status);
CREATE INDEX IF NOT EXISTS ix_req_type         ON requirements(req_type);
CREATE INDEX IF NOT EXISTS ix_req_equipment_id ON requirements(equipment_id);

-- 2) purchase_requests: permitir origen "Requirement" (compra sin OT)
ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS requirement_id INTEGER REFERENCES requirements(id);
ALTER TABLE purchase_requests ALTER COLUMN work_order_id DROP NOT NULL;
CREATE INDEX IF NOT EXISTS ix_pr_requirement_id ON purchase_requests(requirement_id);
