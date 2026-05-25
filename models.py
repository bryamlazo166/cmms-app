from typing import Optional
from sqlalchemy import String, Integer, ForeignKey, Text, Boolean, Float, Date, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import db
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash


# ── Authentication ─────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default='tecnico')
    # roles: admin | supervisor | tecnico
    full_name: Mapped[str] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # Flask-Login interface (manual — avoids UserMixin.is_active conflict)
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return bool(self.active)

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "full_name": self.full_name,
            "active": self.active,
        }


class Notification(db.Model):
    """In-app notifications for alerts and reminders."""
    __tablename__ = 'notifications'

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default='INFO')
    # VENCIDO | STOCK_BAJO | AVISO | OT | SISTEMA
    link: Mapped[str | None] = mapped_column(String(200), nullable=True)  # URL to navigate
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null = all users
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "category": self.category,
            "link": self.link,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(db.Model):
    """Registro de acciones criticas (auditoria de seguridad).

    Se guarda en cada evento sensible: login/logout (incluyendo fallos),
    cambios en usuarios o roles, eliminacion de OTs/avisos, exportaciones
    masivas, reset de BD, etc. NO se pretende ser un log exhaustivo de
    toda la actividad — solo eventos relevantes para auditoria.
    """
    __tablename__ = 'audit_logs'
    __table_args__ = (
        Index('ix_audit_timestamp', 'timestamp'),
        Index('ix_audit_user_id', 'user_id'),
        Index('ix_audit_action', 'action'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null si login fallido
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    # ej: LOGIN_OK, LOGIN_FAIL, LOGOUT, USER_CREATE, USER_UPDATE, USER_DELETE,
    # ROLE_CHANGE, PASSWORD_CHANGE, OT_DELETE, NOTICE_DELETE, EXPORT_MASS,
    # IMPORT_EXCEL, DB_RESET, PERMISSION_CHANGE, etc.
    module: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv4 / IPv6
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "module": self.module,
            "entity_id": self.entity_id,
            "detail": self.detail,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "success": self.success,
        }


class RolePermission(db.Model):
    """Configurable permissions per role per module — 8 flags granulares."""
    __tablename__ = 'role_permissions'
    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, default=True)
    can_create: Mapped[bool] = mapped_column(Boolean, default=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    can_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    can_export: Mapped[bool] = mapped_column(Boolean, default=False)
    can_import: Mapped[bool] = mapped_column(Boolean, default=False)
    can_close: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    # Flags granulares especificos del modulo "ordenes". En otros modulos
    # quedan a False y no se usan. Permiten controlar boton-por-boton
    # sin acoplarlos a los flags genericos edit/close.
    can_edit_ot: Mapped[bool] = mapped_column(Boolean, default=False)
    can_adjust_hours: Mapped[bool] = mapped_column(Boolean, default=False)

    def to_dict(self):
        return {
            "id": self.id, "role": self.role, "module": self.module,
            "can_view": self.can_view, "can_create": self.can_create,
            "can_edit": self.can_edit, "can_delete": self.can_delete,
            "can_export": self.can_export, "can_import": self.can_import,
            "can_close": self.can_close, "can_approve": self.can_approve,
            "can_edit_ot": self.can_edit_ot,
            "can_adjust_hours": self.can_adjust_hours,
        }


# Taxonomy: Area -> Line -> Equipment -> System -> Component -> SparePart

class Area(db.Model):
    __tablename__ = 'areas'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    # Si False, esta area NO entra en los calculos de indicadores ni
    # produccion vs mantenimiento (util para "BAJA / FUERA DE SERVICIO",
    # "UTILITIES" u otras areas que no producen).
    include_in_kpi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Orden en el flujo de proceso de la planta. Usado por la Hoja de
    # Coordinacion Diaria para agrupar y secuenciar las areas en el PDF:
    # COCCION (10) -> SECADO (20) -> MOLINO (30) -> CALDERAS (100). NULL = al
    # final, alfabetico. Se puede editar libremente sin afectar nada mas.
    process_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    lines = relationship("Line", back_populates="area", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description,
                "include_in_kpi": self.include_in_kpi,
                "process_order": self.process_order}

class Line(db.Model):
    __tablename__ = 'lines'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    area_id: Mapped[int] = mapped_column(ForeignKey('areas.id'), nullable=False)
    
    area = relationship("Area", back_populates="lines")
    equipments = relationship("Equipment", back_populates="line", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description, "area_id": self.area_id}

class Equipment(db.Model):
    __tablename__ = 'equipments'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    tag: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    criticality: Mapped[str | None] = mapped_column(String(20), nullable=True)  # Baja, Media, Alta
    line_id: Mapped[int] = mapped_column(ForeignKey('lines.id'), nullable=False)
    # Si False, este equipo NO entra en los calculos de indicadores ni de
    # produccion (util para hidrolavadoras, equipos auxiliares, equipos
    # dados de baja, etc.).
    include_in_kpi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Capacidad nominal en TM/mes — usada para ponderar disponibilidad.
    # Si esta NULL, el calculo cae al diccionario hardcoded EQUIPMENT_CAPACITY
    # (legacy). Llenar este campo permite quitar la dependencia del codigo.
    capacity_tm: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Jornada operativa: horas por dia y dias por semana en que el equipo
    # esta DISPONIBLE para operar. Default 24/7. Algunos equipos auxiliares
    # solo operan 16h/dia o 6 dias/semana.
    shift_hours_per_day: Mapped[float] = mapped_column(Float, nullable=False, default=24.0)
    work_days_per_week: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    # Rendimiento: % de materia prima ingresada que se convierte en producto
    # final. Ej: digestor 12000 TM/mes de capacidad de procesamiento, pero
    # rendimiento real ~30% → produce ~3600 TM/mes de harina.
    # Default 1.0 (sin perdida de proceso) para no afectar calculos legacy.
    yield_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Responsable por defecto del mantenimiento de este equipo:
    # 'INTERNO' = area de mantenimiento de la empresa
    # 'PROVEEDOR' = proveedor externo (FAPMETAL, etc.)
    # Cada punto preventivo (lub/insp/mon) puede sobrescribir esto via su
    # campo responsible_party_override; si esta NULL hereda del equipo.
    default_responsible_party: Mapped[str] = mapped_column(String(20), nullable=False, default='INTERNO')
    default_provider_id: Mapped[int | None] = mapped_column(ForeignKey('providers.id'), nullable=True)
    # Flujo de proceso de la planta: posicion secuencial dentro de la linea
    # (TH POZA=1, TH ALIMENTADOR=2, TRITURADOR=3...) y a que equipo aguas abajo
    # alimenta su producto. Permite auto-generar el diagrama de flujo en
    # /flujo-planta y calcular dependencias serie/paralelo para indicadores.
    process_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feeds_into_equipment_id: Mapped[int | None] = mapped_column(ForeignKey('equipments.id'), nullable=True)

    line = relationship("Line", back_populates="equipments")
    systems = relationship("System", back_populates="equipment", cascade="all, delete-orphan")
    default_provider = relationship("Provider", foreign_keys=[default_provider_id])
    feeds_into = relationship("Equipment", remote_side='Equipment.id', foreign_keys=[feeds_into_equipment_id])

    def to_dict(self):
        return {"id": self.id, "name": self.name, "tag": self.tag, "description": self.description,
                "criticality": self.criticality, "line_id": self.line_id,
                "include_in_kpi": self.include_in_kpi, "capacity_tm": self.capacity_tm,
                "shift_hours_per_day": self.shift_hours_per_day,
                "work_days_per_week": self.work_days_per_week,
                "yield_factor": self.yield_factor,
                "default_responsible_party": self.default_responsible_party,
                "default_provider_id": self.default_provider_id,
                "default_provider_name": self.default_provider.name if self.default_provider else None,
                "process_order": self.process_order,
                "feeds_into_equipment_id": self.feeds_into_equipment_id}


# Aristas adicionales del flujo de planta. La conexion principal va en
# Equipment.feeds_into_equipment_id (1:1 aguas abajo); esta tabla guarda las
# rutas alternativas: bypass por compuerta, derivaciones a equipos paralelos,
# etc. Se renderizan en /flujo-planta como lineas punteadas.
class EquipmentFlowEdge(db.Model):
    __tablename__ = 'equipment_flow_edges'
    id: Mapped[int] = mapped_column(primary_key=True)
    from_equipment_id: Mapped[int] = mapped_column(ForeignKey('equipments.id'), nullable=False)
    to_equipment_id: Mapped[int] = mapped_column(ForeignKey('equipments.id'), nullable=False)
    # BYPASS = compuerta que salta el equipo siguiente cuando esta detenido.
    # ALTERNATE = ruta paralela permanentemente disponible.
    edge_type: Mapped[str] = mapped_column(String(20), nullable=False, default='BYPASS')
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    from_equipment = relationship("Equipment", foreign_keys=[from_equipment_id])
    to_equipment = relationship("Equipment", foreign_keys=[to_equipment_id])

    def to_dict(self):
        return {
            "id": self.id,
            "from_equipment_id": self.from_equipment_id,
            "to_equipment_id": self.to_equipment_id,
            "from_tag": self.from_equipment.tag if self.from_equipment else None,
            "to_tag": self.to_equipment.tag if self.to_equipment else None,
            "edge_type": self.edge_type,
            "note": self.note,
            "is_active": self.is_active,
        }


class System(db.Model):
    __tablename__ = 'systems'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    equipment_id: Mapped[int] = mapped_column(ForeignKey('equipments.id'), nullable=False)
    
    equipment = relationship("Equipment", back_populates="systems")
    components = relationship("Component", back_populates="system", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "equipment_id": self.equipment_id}

class Component(db.Model):
    __tablename__ = 'components'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    system_id: Mapped[int] = mapped_column(ForeignKey('systems.id'), nullable=False)
    criticality: Mapped[str | None] = mapped_column(String(50), nullable=True, default='Media')
    
    system = relationship("System", back_populates="components")
    spare_parts = relationship("SparePart", back_populates="component", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description, "system_id": self.system_id, "criticality": self.criticality}

class SparePart(db.Model):
    __tablename__ = 'spare_parts'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=True)
    brand: Mapped[str] = mapped_column(String(50), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    component_id: Mapped[int] = mapped_column(ForeignKey('components.id'), nullable=False)
    
    component = relationship("Component", back_populates="spare_parts")

    def to_dict(self):
        return {
            "id": self.id, 
            "name": self.name, 
            "code": self.code, 
            "brand": self.brand, 
            "quantity": self.quantity,
            "component_id": self.component_id
        }


# ── Technical Specs (key-value) for Equipment & Component ────────────────────

class EquipmentSpec(db.Model):
    __tablename__ = 'equipment_specs'
    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey('equipments.id'), nullable=False)
    key_name: Mapped[str] = mapped_column(String(120), nullable=False)
    value_text: Mapped[str] = mapped_column(String(250), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    equipment = relationship("Equipment", backref="specs")

    def to_dict(self):
        return {"id": self.id, "equipment_id": self.equipment_id, "key_name": self.key_name, "value_text": self.value_text, "unit": self.unit, "order_index": self.order_index}


class ComponentSpec(db.Model):
    __tablename__ = 'component_specs'
    id: Mapped[int] = mapped_column(primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey('components.id'), nullable=False)
    key_name: Mapped[str] = mapped_column(String(120), nullable=False)
    value_text: Mapped[str] = mapped_column(String(250), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    component = relationship("Component", backref="specs")

    def to_dict(self):
        return {"id": self.id, "component_id": self.component_id, "key_name": self.key_name, "value_text": self.value_text, "unit": self.unit, "order_index": self.order_index}


# ── Document Links (Google Drive, etc) ───────────────────────────────────────

class DocumentLink(db.Model):
    __tablename__ = 'document_links'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # equipment, component, rotative_asset
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # plano, manual, informe, otro
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "entity_type": self.entity_type, "entity_id": self.entity_id, "title": self.title, "url": self.url, "doc_type": self.doc_type, "created_at": self.created_at.isoformat() if self.created_at else None}


# ── Failure Catalog (Catalogo de Fallas) ──────────────────────────────────────

class FailureCatalog(db.Model):
    __tablename__ = 'failure_catalog'
    id: Mapped[int] = mapped_column(primary_key=True)
    failure_mode: Mapped[str] = mapped_column(String(100), nullable=False)
    failure_category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "failure_mode": self.failure_mode,
            "failure_category": self.failure_category,
            "description": self.description,
            "recommended_action": self.recommended_action,
            "is_active": self.is_active,
            "usage_count": self.usage_count,
        }


class Provider(db.Model):
    __tablename__ = 'providers'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_info: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True) # Soft Delete
    
    work_orders = relationship("WorkOrder", back_populates="provider")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "specialty": self.specialty, "contact_info": self.contact_info, "is_active": self.is_active}


class Technician(db.Model):
    __tablename__ = 'technicians'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(100), nullable=True)  # MECANICO, ELECTRICO
    contact_info: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # Soft Delete (Baja/Alta)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Vinculado a User

    def to_dict(self):
        return {"id": self.id, "name": self.name, "specialty": self.specialty, "contact_info": self.contact_info, "is_active": self.is_active, "user_id": self.user_id}

class MaintenanceNotice(db.Model):
    __tablename__ = 'maintenance_notices'
    __table_args__ = (
        Index('ix_notices_status', 'status'),
        Index('ix_notices_equipment_id', 'equipment_id'),
        Index('ix_notices_area_id', 'area_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True) # AV-XXXX
    
    # Reporter Info
    reporter_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reporter_type: Mapped[str | None] = mapped_column(String(50), nullable=True) 
    
    # Provider Info
    provider_id: Mapped[int | None] = mapped_column(ForeignKey('providers.id'), nullable=True)
    provider = relationship("Provider")
    specialty: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shift: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    # Hierarchy Links
    area_id: Mapped[int | None] = mapped_column(ForeignKey('areas.id'), nullable=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey('lines.id'), nullable=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey('equipments.id'), nullable=True)
    system_id: Mapped[int | None] = mapped_column(ForeignKey('systems.id'), nullable=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey('components.id'), nullable=True)
    
    # Details
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    criticality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    request_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # F.Solicitud - when created in CMMS
    # reported_at: hora en que producción avisó realmente (puede ser anterior a
    # request_date si el aviso llegó por WhatsApp/verbal y se registró tarde).
    # Si NULL, el cálculo de tiempo de respuesta cae a request_date (retrocompat).
    reported_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # report_channel: canal por el que producción reportó (SISTEMA, WHATSAPP,
    # VERBAL, RADIO, CORREO). Útil para analizar adopción del CMMS.
    report_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    treatment_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # F.Tratada - when OT started
    planning_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # F.Programado - from OT scheduled
    closed_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # F.Fin - cuando se cerró el aviso
    maintenance_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ot_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default='Pendiente') # Pendiente, En Progreso, Cerrado, Anulado
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True) # Reason for annulment

    # Scope: classifies whether this notice belongs to the inventoried plant tree
    # PLAN        = work on a tree-inventoried equipment, counts in equipment KPIs
    # FUERA_PLAN  = work on real equipment not yet added to the tree (promotable later)
    # GENERAL     = generic activity (painting, cleaning, support, etc.) — never an equipment
    scope: Mapped[str] = mapped_column(String(20), default='PLAN', nullable=False)
    free_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Failure analysis
    failure_mode: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    failure_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    blockage_object: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Metal, Piedra, Cadena, Madera, Alambre, Perno, Acero Inoxidable, Bronce, Otro

    # Link to preventive source (lubrication/inspection/monitoring point)
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Link to rotative asset
    rotative_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Link to Work Order (One-to-One or One-to-Many? usually One)
    work_order = relationship("WorkOrder", back_populates="notice", uselist=False)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class WorkOrder(db.Model):
    __tablename__ = 'work_orders'
    __table_args__ = (
        Index('ix_wo_status', 'status'),
        Index('ix_wo_equipment_id', 'equipment_id'),
        Index('ix_wo_notice_id', 'notice_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True) # OT-XXXX
    
    notice_id: Mapped[int | None] = mapped_column(ForeignKey('maintenance_notices.id'), nullable=True)
    notice = relationship("MaintenanceNotice", back_populates="work_order")
    
    provider_id: Mapped[int | None] = mapped_column(ForeignKey('providers.id'), nullable=True)
    provider = relationship("Provider", back_populates="work_orders")
    
    # Hierarchy FKs for standalone OT or copy from notice
    area_id: Mapped[int | None] = mapped_column(ForeignKey('areas.id'), nullable=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey('lines.id'), nullable=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey('equipments.id'), nullable=True)
    system_id: Mapped[int | None] = mapped_column(ForeignKey('systems.id'), nullable=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey('components.id'), nullable=True)
    
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_mode: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Modo de Falla
    maintenance_type: Mapped[str | None] = mapped_column(String(50), nullable=True) # Preventivo, Correctivo
    
    # Planning
    status: Mapped[str] = mapped_column(String(50), default='Abierta') # Abierta, Programada, En Progreso, Cerrada
    technician_id: Mapped[str | None] = mapped_column(String(100), nullable=True) # Tech Name or ID
    scheduled_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estimated_duration: Mapped[float | None] = mapped_column(nullable=True) # Hours
    tech_count: Mapped[int] = mapped_column(Integer, default=1)
    
    # Execution
    real_start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    real_end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    execution_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    real_duration: Mapped[float | None] = mapped_column(nullable=True)

    # Downtime tracking — for availability KPIs
    caused_downtime: Mapped[bool] = mapped_column(Boolean, default=False)
    downtime_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Link to preventive source (lubrication/inspection/monitoring point)
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # source_type: lubrication | inspection | monitoring
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Link to rotative asset (the physical device being worked on)
    rotative_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Shutdown / Parada de planta
    shutdown_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Report tracking
    report_required: Mapped[bool] = mapped_column(Boolean, default=False)
    report_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # PENDIENTE | RECIBIDO
    report_due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    report_received_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Link al informe tecnico (Google Drive, OneDrive, S3, etc.). El bot de
    # Telegram lo devuelve cuando se le pide el informe de la OT.
    report_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Conformidad de servicio (proveedores). Cuando mantenimiento firma el
    # formato dando OK al servicio del proveedor, se sube el PDF/imagen aqui.
    # La presencia de conformity_doc_url indica que ya se envio a logistica
    # para pago. Sin URL = pendiente de conformidad.
    conformity_doc_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    conformity_uploaded_at: Mapped[str | None] = mapped_column(String(20), nullable=True)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ============= NEW: TOOLS & WAREHOUSE =============

class Tool(db.Model):
    """Master catalog of tools available for maintenance work"""
    __tablename__ = 'tools'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # HRR-001
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Manual, Eléctrica, Medición
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default='Disponible')  # Disponible, En Uso, Mantenimiento
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Where stored
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class WarehouseItem(db.Model):
    """Inventory of spare parts and materials in warehouse"""
    __tablename__ = 'warehouse_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # REP-001
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Repuesto, Consumible, Lubricante
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)  # Current quantity
    min_stock: Mapped[int] = mapped_column(Integer, default=0)  # Alert threshold
    unit: Mapped[str] = mapped_column(String(20), default='pza')  # pza, kg, lt, m
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Shelf/Bin location
    unit_cost: Mapped[float | None] = mapped_column(Float, nullable=True)  # Cost per unit
    
    # New Fields
    family: Mapped[str | None] = mapped_column(String(100), nullable=True) # Agrupador
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True) # Marca
    manufacturer_code: Mapped[str | None] = mapped_column(String(100), nullable=True) # Codigo Fabricante
    criticality: Mapped[str | None] = mapped_column(String(20), default='Media') # Baja, Media, Alta
    average_cost: Mapped[float | None] = mapped_column(Float, nullable=True) # Costo Promedio
    
    # Inventory Management Parameters
    lead_time: Mapped[int | None] = mapped_column(Integer, default=0) # Days to replenish
    abc_class: Mapped[str | None] = mapped_column(String(5), default='C') # A, B, C
    xyz_class: Mapped[str | None] = mapped_column(String(5), default='Z') # X, Y, Z
    safety_stock: Mapped[int | None] = mapped_column(Integer, default=0)
    rop: Mapped[int | None] = mapped_column(Integer, default=0) # Reorder Point
    max_stock: Mapped[int | None] = mapped_column(Integer, default=0)
    min_order_qty: Mapped[int | None] = mapped_column(Integer, default=1)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    movements = relationship("WarehouseMovement", back_populates="item", cascade="all, delete-orphan")

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class WarehouseMovement(db.Model):
    """History of stock movements (Kardex)"""
    __tablename__ = 'warehouse_movements'
    __table_args__ = (
        Index('ix_wm_item_id', 'item_id'),
        Index('ix_wm_reference_id', 'reference_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey('warehouse_items.id'), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False) # + for IN, - for OUT
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False) # IN, OUT, ADJUST, RETURN
    date: Mapped[str] = mapped_column(String(20), nullable=False) # ISO Date
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True) # Work Order ID or other ref
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True) # Description/Reason

    item = relationship("WarehouseItem", back_populates="movements")

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}



class OTPersonnel(db.Model):
    """Personnel assigned to a work order with hours"""
    __tablename__ = 'ot_personnel'
    __table_args__ = (
        Index('ix_otp_work_order_id', 'work_order_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey('work_orders.id'), nullable=False)
    technician_id: Mapped[int | None] = mapped_column(ForeignKey('technicians.id'), nullable=True)
    specialty: Mapped[str | None] = mapped_column(String(50), nullable=True)  # MECANICO, ELECTRICO, etc.
    hours_assigned: Mapped[float] = mapped_column(Float, default=0)  # Planned hours
    hours_worked: Mapped[float | None] = mapped_column(Float, nullable=True)  # Actual hours
    attended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # NULL=sin confirmar, True=asistio, False=no vino
    replacement_for_id: Mapped[int | None] = mapped_column(ForeignKey('ot_personnel.id'), nullable=True)  # si reemplaza a otro

    # Relationships
    work_order = relationship("WorkOrder", backref="assigned_personnel")
    technician = relationship("Technician")
    replacement_for = relationship("OTPersonnel", remote_side="OTPersonnel.id", foreign_keys=[replacement_for_id])

    def to_dict(self):
        return {
            "id": self.id,
            "work_order_id": self.work_order_id,
            "technician_id": self.technician_id,
            "technician_name": self.technician.name if self.technician else None,
            "specialty": self.specialty,
            "hours_assigned": self.hours_assigned,
            "hours_worked": self.hours_worked,
            "attended": self.attended,
            "replacement_for_id": self.replacement_for_id,
            "replacement_for_name": (self.replacement_for.technician.name if self.replacement_for and self.replacement_for.technician else None),
        }


class PhotoAttachment(db.Model):
    """Photos attached to notices or work orders."""
    __tablename__ = 'photo_attachments'

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # notice | work_order
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(200), nullable=True)
    original_size_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compressed_size_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "url": self.url,
            "caption": self.caption,
            "original_size_kb": self.original_size_kb,
            "compressed_size_kb": self.compressed_size_kb,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OTLogEntry(db.Model):
    """Activity log / bitacora for work orders."""
    __tablename__ = 'ot_log_entries'

    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey('work_orders.id'), nullable=False)
    log_date: Mapped[str] = mapped_column(String(20), nullable=False)
    log_type: Mapped[str] = mapped_column(String(20), nullable=False, default='NOTA')
    # NOTA | AVANCE | MATERIAL | INFORME | PROVEEDOR | CIERRE
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    work_order = relationship("WorkOrder")

    def to_dict(self):
        return {
            "id": self.id,
            "work_order_id": self.work_order_id,
            "log_date": self.log_date,
            "log_type": self.log_type,
            "author": self.author,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OTMaterial(db.Model):
    """Materials (spare parts, consumibles or tools) assigned to a work order"""
    __tablename__ = 'ot_materials'
    __table_args__ = (
        Index('ix_otm_work_order_id', 'work_order_id'),
        Index('ix_otm_item_type_id', 'item_type', 'item_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey('work_orders.id'), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'tool', 'warehouse', 'free'
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # None for free-text items
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    # New execution fields
    subtype: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # 'herramienta'|'consumible'|'repuesto'
    item_name_free: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # name for free-text items
    unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_installed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=True)

    # Relationship
    work_order = relationship("WorkOrder", backref="assigned_materials")

    def to_dict(self):
        return {
            "id": self.id,
            "work_order_id": self.work_order_id,
            "item_type": self.item_type,
            "item_id": self.item_id,
            "quantity": self.quantity,
            "subtype": self.subtype,
            "item_name_free": self.item_name_free,
            "unit": self.unit,
            "is_installed": self.is_installed if self.is_installed is not None else True,
        }


# ============= NEW: PURCHASING =============

class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    po_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='EMITIDA')
    issue_date: Mapped[date | None] = mapped_column(Date, default=date.today)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Codigo de Requisicion (RQ) interno de la empresa — el que asigna SAP /
    # ERP / sistema interno cuando se crea la requisicion oficial. Permite dar
    # seguimiento cruzado entre el codigo del CMMS (po_code = OC-XXX) y el RQ
    # de la empresa.
    external_rq_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    requests = relationship("PurchaseRequest", back_populates="purchase_order")

    def to_dict(self):
        reqs = []
        if self.requests:
             for r in self.requests:
                 reqs.append({
                     'id': r.id,
                     'req_code': r.req_code,
                     'item_type': r.item_type,
                     'quantity': r.quantity,
                     'status': r.status,
                     'description': r.description,
                     'spare_part_name': r.spare_part.name if r.spare_part else None,
                     'warehouse_item_name': r.warehouse_item.name if r.warehouse_item else None
                 })
        
        return {
            'id': self.id,
            'po_code': self.po_code,
            'provider_name': self.provider_name,
            'status': self.status,
            'issue_date': self.issue_date.isoformat() if self.issue_date else None,
            'delivery_date': self.delivery_date.isoformat() if self.delivery_date else None,
            'external_rq_code': self.external_rq_code,
            'external_notes': self.external_notes,
            'requests': reqs
        }

class PurchaseRequest(db.Model):
    __tablename__ = 'purchase_requests'
    __table_args__ = (
        Index('ix_pr_work_order_id', 'work_order_id'),
        Index('ix_pr_purchase_order_id', 'purchase_order_id'),
        Index('ix_pr_status', 'status'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    req_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    
    work_order_id: Mapped[int] = mapped_column(ForeignKey('work_orders.id'), nullable=False)
    work_order = relationship("WorkOrder", backref="purchase_requests")
    
    item_type: Mapped[str] = mapped_column(String(20), nullable=False) # 'MATERIAL', 'SERVICIO'
    
    # Linked items
    spare_part_id: Mapped[int | None] = mapped_column(ForeignKey('spare_parts.id'), nullable=True)
    spare_part = relationship("SparePart")
    
    warehouse_item_id: Mapped[int | None] = mapped_column(ForeignKey('warehouse_items.id'), nullable=True)
    warehouse_item = relationship("WarehouseItem")
    
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    
    status: Mapped[str] = mapped_column(String(20), default='PENDIENTE') # PENDIENTE, APROBADO, EN_ORDEN, RECIBIDO, CANCELADO
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    purchase_order_id: Mapped[int | None] = mapped_column(ForeignKey('purchase_orders.id'), nullable=True)
    purchase_order = relationship("PurchaseOrder", back_populates="requests")

    def to_dict(self):
        return {
            'id': self.id,
            'req_code': self.req_code,
            'work_order_id': self.work_order_id,
            'ot_code': self.work_order.code if self.work_order else None,
            'item_type': self.item_type,
            'spare_part_id': self.spare_part_id,
            'spare_part_name': self.spare_part.name if self.spare_part else None,
            'warehouse_item_id': self.warehouse_item_id,
            'warehouse_item_name': self.warehouse_item.name if self.warehouse_item else None,
            'description': self.description,
            'quantity': self.quantity,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'purchase_order_id': self.purchase_order_id,
            'po_code': self.purchase_order.po_code if self.purchase_order else None
        }


class LubricationPoint(db.Model):
    __tablename__ = 'lubrication_points'
    __table_args__ = (
        Index('ix_lp_equipment_id', 'equipment_id'),
        Index('ix_lp_is_active', 'is_active'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Hierarchy links
    area_id: Mapped[int | None] = mapped_column(ForeignKey('areas.id'), nullable=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey('lines.id'), nullable=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey('equipments.id'), nullable=True)
    system_id: Mapped[int | None] = mapped_column(ForeignKey('systems.id'), nullable=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey('components.id'), nullable=True)

    lubricant_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity_nominal: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_unit: Mapped[str] = mapped_column(String(20), nullable=False, default='L')

    frequency_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    warning_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    last_service_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    next_due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    semaphore_status: Mapped[str] = mapped_column(String(20), nullable=False, default='PENDIENTE')
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Override de responsabilidad. NULL = hereda de Equipment.default_responsible_party.
    # Solo llenar cuando ESTE punto especifico tiene un responsable distinto al
    # default del equipo (ej: el equipo es del proveedor pero esta lubricacion
    # diaria la hace mantenimiento interno).
    responsible_party_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_id_override: Mapped[int | None] = mapped_column(ForeignKey('providers.id'), nullable=True)

    area = relationship("Area")
    line = relationship("Line")
    equipment = relationship("Equipment")
    system = relationship("System")
    component = relationship("Component")
    executions = relationship("LubricationExecution", back_populates="point", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "area_id": self.area_id,
            "line_id": self.line_id,
            "equipment_id": self.equipment_id,
            "system_id": self.system_id,
            "component_id": self.component_id,
            "area_name": self.area.name if self.area else None,
            "line_name": self.line.name if self.line else None,
            "equipment_name": self.equipment.name if self.equipment else None,
            "system_name": self.system.name if self.system else None,
            "component_name": self.component.name if self.component else None,
            "lubricant_name": self.lubricant_name,
            "quantity_nominal": self.quantity_nominal,
            "quantity_unit": self.quantity_unit,
            "frequency_days": self.frequency_days,
            "warning_days": self.warning_days,
            "last_service_date": self.last_service_date,
            "next_due_date": self.next_due_date,
            "semaphore_status": self.semaphore_status,
            "is_active": self.is_active,
            "responsible_party_override": self.responsible_party_override,
            "provider_id_override": self.provider_id_override,
            # Responsable efectivo (resuelve override -> default del equipo -> INTERNO)
            "effective_responsible_party": (
                self.responsible_party_override
                or (self.equipment.default_responsible_party if self.equipment else 'INTERNO')
            ),
            "effective_provider_id": (
                self.provider_id_override
                if self.responsible_party_override
                else (self.equipment.default_provider_id if self.equipment else None)
            ),
        }


class LubricationExecution(db.Model):
    __tablename__ = 'lubrication_executions'

    id: Mapped[int] = mapped_column(primary_key=True)
    point_id: Mapped[int] = mapped_column(ForeignKey('lubrication_points.id'), nullable=False)
    execution_date: Mapped[str] = mapped_column(String(20), nullable=False)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False, default='SERVICIO')
    quantity_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_unit: Mapped[str] = mapped_column(String(20), nullable=False, default='L')
    executed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    leak_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    anomaly_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_notice_id: Mapped[int | None] = mapped_column(ForeignKey('maintenance_notices.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    point = relationship("LubricationPoint", back_populates="executions")
    created_notice = relationship("MaintenanceNotice")

    def to_dict(self):
        return {
            "id": self.id,
            "point_id": self.point_id,
            "point_name": self.point.name if self.point else None,
            "execution_date": self.execution_date,
            "action_type": self.action_type,
            "quantity_used": self.quantity_used,
            "quantity_unit": self.quantity_unit,
            "executed_by": self.executed_by,
            "leak_detected": self.leak_detected,
            "anomaly_detected": self.anomaly_detected,
            "comments": self.comments,
            "created_notice_id": self.created_notice_id,
            "created_notice_code": self.created_notice.code if self.created_notice else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class MonitoringPoint(db.Model):
    __tablename__ = 'monitoring_points'
    __table_args__ = (
        Index('ix_mp_equipment_id', 'equipment_id'),
        Index('ix_mp_is_active', 'is_active'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    measurement_type: Mapped[str] = mapped_column(String(60), nullable=False, default='VIBRACION')
    axis: Mapped[str | None] = mapped_column(String(20), nullable=True)  # VERTICAL, HORIZONTAL, N/A
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default='mm/s')
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Hierarchy links
    area_id: Mapped[int | None] = mapped_column(ForeignKey('areas.id'), nullable=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey('lines.id'), nullable=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey('equipments.id'), nullable=True)
    system_id: Mapped[int | None] = mapped_column(ForeignKey('systems.id'), nullable=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey('components.id'), nullable=True)

    # Limits and frequency
    normal_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    normal_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    alarm_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    alarm_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    frequency_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    warning_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    last_measurement_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    next_due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    semaphore_status: Mapped[str] = mapped_column(String(20), nullable=False, default='PENDIENTE')
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Override de responsabilidad (NULL = hereda del Equipment)
    responsible_party_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_id_override: Mapped[int | None] = mapped_column(ForeignKey('providers.id'), nullable=True)

    area = relationship("Area")
    line = relationship("Line")
    equipment = relationship("Equipment")
    system = relationship("System")
    component = relationship("Component")
    readings = relationship("MonitoringReading", back_populates="point", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "measurement_type": self.measurement_type,
            "axis": self.axis,
            "unit": self.unit,
            "notes": self.notes,
            "area_id": self.area_id,
            "line_id": self.line_id,
            "equipment_id": self.equipment_id,
            "system_id": self.system_id,
            "component_id": self.component_id,
            "area_name": self.area.name if self.area else None,
            "line_name": self.line.name if self.line else None,
            "equipment_name": self.equipment.name if self.equipment else None,
            "system_name": self.system.name if self.system else None,
            "component_name": self.component.name if self.component else None,
            "normal_min": self.normal_min,
            "normal_max": self.normal_max,
            "alarm_min": self.alarm_min,
            "alarm_max": self.alarm_max,
            "frequency_days": self.frequency_days,
            "warning_days": self.warning_days,
            "last_measurement_date": self.last_measurement_date,
            "next_due_date": self.next_due_date,
            "semaphore_status": self.semaphore_status,
            "is_active": self.is_active,
            "responsible_party_override": self.responsible_party_override,
            "provider_id_override": self.provider_id_override,
            "effective_responsible_party": (
                self.responsible_party_override
                or (self.equipment.default_responsible_party if self.equipment else 'INTERNO')
            ),
            "effective_provider_id": (
                self.provider_id_override
                if self.responsible_party_override
                else (self.equipment.default_provider_id if self.equipment else None)
            ),
        }


class MonitoringReading(db.Model):
    __tablename__ = 'monitoring_readings'

    id: Mapped[int] = mapped_column(primary_key=True)
    point_id: Mapped[int] = mapped_column(ForeignKey('monitoring_points.id'), nullable=False)
    reading_date: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    executed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(250), nullable=True)
    is_regularization: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_notice_id: Mapped[int | None] = mapped_column(ForeignKey('maintenance_notices.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    point = relationship("MonitoringPoint", back_populates="readings")
    created_notice = relationship("MaintenanceNotice")

    def to_dict(self):
        return {
            "id": self.id,
            "point_id": self.point_id,
            "point_name": self.point.name if self.point else None,
            "reading_date": self.reading_date,
            "value": self.value,
            "unit": self.point.unit if self.point else None,
            "executed_by": self.executed_by,
            "notes": self.notes,
            "photo_url": self.photo_url,
            "is_regularization": self.is_regularization,
            "created_notice_id": self.created_notice_id,
            "created_notice_code": self.created_notice.code if self.created_notice else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class RotativeAsset(db.Model):
    __tablename__ = 'rotative_assets'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='Disponible')  # Disponible, Instalado, En Taller, Baja
    install_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    area_id: Mapped[int | None] = mapped_column(ForeignKey('areas.id'), nullable=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey('lines.id'), nullable=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey('equipments.id'), nullable=True)
    system_id: Mapped[int | None] = mapped_column(ForeignKey('systems.id'), nullable=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey('components.id'), nullable=True)

    area = relationship("Area")
    line = relationship("Line")
    equipment = relationship("Equipment")
    system = relationship("System")
    component = relationship("Component")
    history = relationship("RotativeAssetHistory", back_populates="asset", cascade="all, delete-orphan")
    specs = relationship("RotativeAssetSpec", back_populates="asset", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "brand": self.brand,
            "model": self.model,
            "serial_number": self.serial_number,
            "status": self.status,
            "install_date": self.install_date,
            "notes": self.notes,
            "is_active": self.is_active,
            "area_id": self.area_id,
            "line_id": self.line_id,
            "equipment_id": self.equipment_id,
            "system_id": self.system_id,
            "component_id": self.component_id,
            "area_name": self.area.name if self.area else None,
            "line_name": self.line.name if self.line else None,
            "equipment_name": self.equipment.name if self.equipment else None,
            "system_name": self.system.name if self.system else None,
            "component_name": self.component.name if self.component else None
        }



class RotativeAssetSpec(db.Model):
    __tablename__ = 'rotative_asset_specs'

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey('rotative_assets.id'), nullable=False)
    key_name: Mapped[str] = mapped_column(String(120), nullable=False)
    value_text: Mapped[str] = mapped_column(String(250), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    asset = relationship("RotativeAsset", back_populates="specs")

    def to_dict(self):
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "key_name": self.key_name,
            "value_text": self.value_text,
            "unit": self.unit,
            "order_index": self.order_index,
            "is_active": self.is_active,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
# ── Inspection Routes / Rondas de Inspección ──────────────────────────────────

class InspectionRoute(db.Model):
    __tablename__ = 'inspection_routes'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey('areas.id'), nullable=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey('lines.id'), nullable=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey('equipments.id'), nullable=True)
    frequency_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    warning_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_execution_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    next_due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    semaphore_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Override de responsabilidad (NULL = hereda del Equipment)
    responsible_party_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_id_override: Mapped[int | None] = mapped_column(ForeignKey('providers.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    area = relationship("Area")
    line = relationship("Line")
    equipment = relationship("Equipment")
    items = relationship("InspectionItem", back_populates="route", cascade="all, delete-orphan",
                         order_by="InspectionItem.order_index")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "area_id": self.area_id,
            "line_id": self.line_id,
            "equipment_id": self.equipment_id,
            "area_name": self.area.name if self.area else None,
            "line_name": self.line.name if self.line else None,
            "equipment_name": self.equipment.name if self.equipment else None,
            "frequency_days": self.frequency_days,
            "warning_days": self.warning_days,
            "last_execution_date": self.last_execution_date,
            "next_due_date": self.next_due_date,
            "semaphore_status": self.semaphore_status,
            "is_active": self.is_active,
            "item_count": len(self.items) if self.items else 0,
            "responsible_party_override": self.responsible_party_override,
            "provider_id_override": self.provider_id_override,
            "effective_responsible_party": (
                self.responsible_party_override
                or (self.equipment.default_responsible_party if self.equipment else 'INTERNO')
            ),
            "effective_provider_id": (
                self.provider_id_override
                if self.responsible_party_override
                else (self.equipment.default_provider_id if self.equipment else None)
            ),
        }


class InspectionItem(db.Model):
    __tablename__ = 'inspection_items'

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey('inspection_routes.id'), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False, default='CHECK')
    # item_type: CHECK (OK/NO OK) | MEDICION (numeric value) | TEXTO (free text)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)       # for MEDICION
    alarm_min: Mapped[float | None] = mapped_column(Float, nullable=True)     # for MEDICION
    alarm_max: Mapped[float | None] = mapped_column(Float, nullable=True)     # for MEDICION
    criteria: Mapped[str | None] = mapped_column(String(300), nullable=True)  # acceptance criteria
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    route = relationship("InspectionRoute", back_populates="items")

    def to_dict(self):
        return {
            "id": self.id,
            "route_id": self.route_id,
            "description": self.description,
            "item_type": self.item_type,
            "unit": self.unit,
            "alarm_min": self.alarm_min,
            "alarm_max": self.alarm_max,
            "criteria": self.criteria,
            "order_index": self.order_index,
            "is_active": self.is_active,
        }


class InspectionExecution(db.Model):
    __tablename__ = 'inspection_executions'

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey('inspection_routes.id'), nullable=False)
    execution_date: Mapped[str] = mapped_column(String(20), nullable=False)
    executed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    overall_result: Mapped[str] = mapped_column(String(20), nullable=False, default='OK')
    # overall_result: OK | CON_HALLAZGOS | NO_EJECUTADA
    findings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_notice_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    route = relationship("InspectionRoute")

    def to_dict(self):
        route = self.route
        return {
            "id": self.id,
            "route_id": self.route_id,
            "route_code": route.code if route else None,
            "route_name": route.name if route else None,
            "execution_date": self.execution_date,
            "executed_by": self.executed_by,
            "overall_result": self.overall_result,
            "findings_count": self.findings_count,
            "comments": self.comments,
            "created_notice_id": self.created_notice_id,
        }


class InspectionResult(db.Model):
    __tablename__ = 'inspection_results'

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey('inspection_executions.id'), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey('inspection_items.id'), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    # For CHECK: OK | NO_OK
    # For MEDICION: OK | ALARMA
    value: Mapped[float | None] = mapped_column(Float, nullable=True)         # numeric for MEDICION
    text_value: Mapped[str | None] = mapped_column(String(300), nullable=True)  # for TEXTO
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)

    execution = relationship("InspectionExecution")
    item = relationship("InspectionItem")

    def to_dict(self):
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "item_id": self.item_id,
            "item_description": self.item.description if self.item else None,
            "item_type": self.item.item_type if self.item else None,
            "result": self.result,
            "value": self.value,
            "text_value": self.text_value,
            "observation": self.observation,
        }


# ── Activity Tracking / Seguimiento de Actividades ─────────────────────────────

class Activity(db.Model):
    __tablename__ = 'activities'

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False, default='OTRO')
    # FABRICACION | COMPRA | REUNION | PROYECTO | PARADA | OTRO
    responsible: Mapped[str | None] = mapped_column(String(120), nullable=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default='MEDIA')
    # ALTA | MEDIA | BAJA
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='ABIERTA')
    # ABIERTA | EN_PROGRESO | COMPLETADA | CANCELADA
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    completion_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey('equipments.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    equipment = relationship("Equipment")
    milestones = relationship("Milestone", back_populates="activity", cascade="all, delete-orphan",
                              order_by="Milestone.order_index")

    def to_dict(self):
        ms = [m for m in (self.milestones or []) if m.is_active]
        done = sum(1 for m in ms if m.status == 'COMPLETADO')
        total = len(ms)
        next_ms = next((m for m in ms if m.status != 'COMPLETADO'), None)
        return {
            "id": self.id,
            "title": self.title,
            "activity_type": self.activity_type,
            "responsible": self.responsible,
            "priority": self.priority,
            "status": self.status,
            "description": self.description,
            "start_date": self.start_date,
            "target_date": self.target_date,
            "completion_date": self.completion_date,
            "equipment_id": self.equipment_id,
            "equipment_name": self.equipment.name if self.equipment else None,
            "milestones_done": done,
            "milestones_total": total,
            "progress": round((done / total) * 100) if total > 0 else 0,
            "next_milestone": next_ms.description if next_ms else None,
            "next_milestone_date": next_ms.target_date if next_ms else None,
        }


class Milestone(db.Model):
    __tablename__ = 'milestones'

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey('activities.id'), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    target_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    completion_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='PENDIENTE')
    # PENDIENTE | EN_PROGRESO | COMPLETADO
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    activity = relationship("Activity", back_populates="milestones")

    def to_dict(self):
        return {
            "id": self.id,
            "activity_id": self.activity_id,
            "description": self.description,
            "target_date": self.target_date,
            "completion_date": self.completion_date,
            "status": self.status,
            "comment": self.comment,
            "order_index": self.order_index,
        }


class RotativeAssetBOM(db.Model):
    """Bill of Materials — spare parts linked to a rotative asset."""
    __tablename__ = 'rotative_asset_bom'

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey('rotative_assets.id'), nullable=False)
    warehouse_item_id: Mapped[int | None] = mapped_column(ForeignKey('warehouse_items.id'), nullable=True)
    free_text: Mapped[str | None] = mapped_column(String(200), nullable=True)  # When no warehouse item
    category: Mapped[str] = mapped_column(String(30), nullable=False, default='MECANICO')
    # MECANICO | ELECTRICO | CONSUMIBLE
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(String(250), nullable=True)

    asset = relationship("RotativeAsset")
    warehouse_item = relationship("WarehouseItem")

    def to_dict(self):
        wi = self.warehouse_item
        ft = getattr(self, 'free_text', None)
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "warehouse_item_id": self.warehouse_item_id,
            "free_text": ft,
            "item_code": wi.code if wi else None,
            "item_name": wi.name if wi else (ft or None),
            "item_stock": wi.stock if wi else None,
            "item_unit": wi.unit if wi else None,
            "category": self.category,
            "quantity": self.quantity,
            "notes": self.notes,
            "is_linked": wi is not None,
        }


class RotativeAssetHistory(db.Model):
    __tablename__ = 'rotative_asset_history'

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey('rotative_assets.id'), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)  # INSTALACION, RETIRO, CAMBIO_ESTADO, ACTUALIZACION
    event_date: Mapped[str] = mapped_column(String(20), nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    area_id: Mapped[int | None] = mapped_column(ForeignKey('areas.id'), nullable=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey('lines.id'), nullable=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey('equipments.id'), nullable=True)
    system_id: Mapped[int | None] = mapped_column(ForeignKey('systems.id'), nullable=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey('components.id'), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    asset = relationship("RotativeAsset", back_populates="history")
    area = relationship("Area")
    line = relationship("Line")
    equipment = relationship("Equipment")
    system = relationship("System")
    component = relationship("Component")

    def to_dict(self):
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "asset_code": self.asset.code if self.asset else None,
            "asset_name": self.asset.name if self.asset else None,
            "event_type": self.event_type,
            "event_date": self.event_date,
            "comments": self.comments,
            "area_id": self.area_id,
            "line_id": self.line_id,
            "equipment_id": self.equipment_id,
            "system_id": self.system_id,
            "component_id": self.component_id,
            "area_name": self.area.name if self.area else None,
            "line_name": self.line.name if self.line else None,
            "equipment_name": self.equipment.name if self.equipment else None,
            "system_name": self.system.name if self.system else None,
            "component_name": self.component.name if self.component else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


# ── Thickness Inspection / Inspección de Espesores por Ultrasonido ───────────

class ThicknessPoint(db.Model):
    """Catálogo de puntos de medición de espesor para cada equipo.

    Cada equipo tiene ~90 puntos catalogados (paletas, refuerzos, ejes, chaqueta, tapas).
    Se crea 1 sola vez por equipo y luego se reutiliza en cada inspección.
    """
    __tablename__ = 'thickness_points'
    __table_args__ = (
        Index('ix_thk_pt_equip', 'equipment_id'),
        Index('ix_thk_pt_group', 'equipment_id', 'group_name'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey('equipments.id'), nullable=False)
    component_id: Mapped[Optional[int]] = mapped_column(ForeignKey('components.id'), nullable=True)
    group_name: Mapped[str] = mapped_column(String(40), nullable=False)
    # PALETA, REFUERZO, EJE, CHAQUETA, TAPA_MOTRIZ, TAPA_CONDUCIDA
    section: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1..5
    position: Mapped[str] = mapped_column(String(30), nullable=False)
    # A/B/C, X/Y/Z, EJE_CENTRAL, SUPERIOR/DERECHO/INFERIOR/IZQUIERDO, P1..P10
    nominal_thickness: Mapped[float] = mapped_column(Float, nullable=False, default=25.4)
    alarm_thickness: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    scrap_thickness: Mapped[float] = mapped_column(Float, nullable=False, default=8.0)
    last_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='NORMAL')
    # NORMAL, ALERTA, CRITICO
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    equipment = relationship("Equipment")
    component = relationship("Component")

    def to_dict(self):
        return {
            "id": self.id,
            "equipment_id": self.equipment_id,
            "component_id": self.component_id,
            "group_name": self.group_name,
            "section": self.section,
            "position": self.position,
            "nominal_thickness": self.nominal_thickness,
            "alarm_thickness": self.alarm_thickness,
            "scrap_thickness": self.scrap_thickness,
            "last_value": self.last_value,
            "last_date": self.last_date,
            "status": self.status,
            "is_active": self.is_active,
            "order_index": self.order_index,
        }


class ThicknessInspection(db.Model):
    """Inspección completa de espesores para un equipo en una fecha determinada."""
    __tablename__ = 'thickness_inspections'
    __table_args__ = (
        Index('ix_thk_insp_equip', 'equipment_id'),
        Index('ix_thk_insp_date', 'inspection_date'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey('equipments.id'), nullable=False)
    inspection_date: Mapped[str] = mapped_column(String(20), nullable=False)
    next_due_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    frequency_days: Mapped[int] = mapped_column(Integer, default=60)
    inspector_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='COMPLETA')
    # PROGRAMADA, EN_CURSO, COMPLETA
    semaphore_status: Mapped[str] = mapped_column(String(20), default='VERDE')
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    critical_points: Mapped[int] = mapped_column(Integer, default=0)
    alert_points: Mapped[int] = mapped_column(Integer, default=0)
    observations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Link al PDF escaneado en Drive o storage externo
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    equipment = relationship("Equipment")

    def to_dict(self):
        return {
            "id": self.id,
            "equipment_id": self.equipment_id,
            "equipment_name": self.equipment.name if self.equipment else None,
            "equipment_tag": self.equipment.tag if self.equipment else None,
            "inspection_date": self.inspection_date,
            "next_due_date": self.next_due_date,
            "frequency_days": self.frequency_days,
            "inspector_name": self.inspector_name,
            "status": self.status,
            "semaphore_status": self.semaphore_status,
            "total_points": self.total_points,
            "critical_points": self.critical_points,
            "alert_points": self.alert_points,
            "observations": self.observations,
            "pdf_url": self.pdf_url,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ThicknessReading(db.Model):
    """Lectura individual de un punto en una inspección."""
    __tablename__ = 'thickness_readings'
    __table_args__ = (
        Index('ix_thk_rd_insp', 'inspection_id'),
        Index('ix_thk_rd_pt', 'point_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey('thickness_inspections.id'), nullable=False)
    point_id: Mapped[int] = mapped_column(ForeignKey('thickness_points.id'), nullable=False)
    value_mm: Mapped[float] = mapped_column(Float, nullable=False)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    is_alert: Mapped[bool] = mapped_column(Boolean, default=False)

    inspection = relationship("ThicknessInspection", backref="readings")
    point = relationship("ThicknessPoint")

    def to_dict(self):
        return {
            "id": self.id,
            "inspection_id": self.inspection_id,
            "point_id": self.point_id,
            "value_mm": self.value_mm,
            "is_critical": self.is_critical,
            "is_alert": self.is_alert,
        }


# ── Shutdown / Parada de Planta ───────────────────────────────────────────────

class Shutdown(db.Model):
    """Programa de parada de planta (generalmente domingos)."""
    __tablename__ = 'shutdowns'
    __table_args__ = (
        Index('ix_shutdown_date', 'shutdown_date'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[Optional[str]] = mapped_column(String(30), unique=True, nullable=True)
    # Código automático: PP-YYYY-MM-NNN (PP = Parada Planta, correlativo mensual)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    shutdown_date: Mapped[str] = mapped_column(String(20), nullable=False)
    shutdown_type: Mapped[str] = mapped_column(String(20), default='TOTAL')
    # TOTAL, PARCIAL
    start_time: Mapped[str] = mapped_column(String(10), default='07:00')
    end_time: Mapped[str] = mapped_column(String(10), default='19:00')
    overtime: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default='PLANIFICADA')
    # PLANIFICADA, EN_CURSO, COMPLETADA, CANCELADA
    is_planned: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # True  = Parada planificada (mtto programado, parada mayor planeada).
    # False = Parada por averia / no planeada (falla obligo a parar y se
    #         aprovecho para hacer trabajos adicionales).
    # Esta bandera es la que decide si las OTs Correctivas vinculadas a la
    # parada cuentan o no en Disponibilidad Inherente del flujo de planta.
    production_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Requerimientos a producción (equipo limpio, retirar pallets, etc.)
    observations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    areas = relationship("ShutdownArea", backref="shutdown", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "shutdown_date": self.shutdown_date,
            "shutdown_type": self.shutdown_type,
            "is_planned": self.is_planned,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "overtime": self.overtime,
            "status": self.status,
            "production_requirements": self.production_requirements,
            "observations": self.observations,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "areas": [a.to_dict() for a in self.areas] if self.areas else [],
        }


class ShutdownArea(db.Model):
    """Áreas involucradas en una parada."""
    __tablename__ = 'shutdown_areas'
    id: Mapped[int] = mapped_column(primary_key=True)
    shutdown_id: Mapped[int] = mapped_column(ForeignKey('shutdowns.id'), nullable=False)
    area_id: Mapped[int] = mapped_column(ForeignKey('areas.id'), nullable=False)

    area = relationship("Area")

    def to_dict(self):
        return {
            "id": self.id,
            "shutdown_id": self.shutdown_id,
            "area_id": self.area_id,
            "area_name": self.area.name if self.area else None,
        }


class ShutdownTemplate(db.Model):
    """Plantilla reutilizable de tareas para parada de planta.
    Agrupa N items, cada uno con un patron de aplicacion a equipos. Al
    aplicarla a una parada se generan N OTs (una por cada equipo objetivo).
    """
    __tablename__ = 'shutdown_templates'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    items = relationship(
        "ShutdownTemplateItem", back_populates="template",
        cascade="all, delete-orphan",
        order_by="ShutdownTemplateItem.order_index, ShutdownTemplateItem.id",
    )

    def to_dict(self, with_items=False):
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "item_count": len(self.items) if self.items else 0,
        }
        if with_items:
            d["items"] = [it.to_dict() for it in (self.items or [])]
        return d


class ShutdownTemplateItem(db.Model):
    """Tarea individual dentro de una plantilla. Define el patron de aplicacion
    para expandirse a multiples OTs cuando se aplica a una parada.

    application_mode controla como se resuelven los equipos objetivo:
      - 'specific_equipment' → un solo equipo (target_equipment_id)
      - 'tag_pattern'        → equipos cuyo tag matchea regex (target_tag_pattern)
      - 'area'               → todos los equipos del area_id
      - 'line'               → todos los equipos del line_id
    """
    __tablename__ = 'shutdown_template_items'
    __table_args__ = (
        Index('ix_shutdown_tpl_item_tpl', 'template_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey('shutdown_templates.id'), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    description: Mapped[str] = mapped_column(String(300), nullable=False)
    # Puede contener placeholders {tag} o {name} que se reemplazan por el equipo
    # objetivo al generar la OT. Ej: "Empaquetadura prensa estopa motriz {tag}"

    maintenance_type: Mapped[str] = mapped_column(String(30), default='Preventivo')
    estimated_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tech_count: Mapped[int] = mapped_column(Integer, default=1)
    specialty: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    component_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Nombre fuzzy del componente (resuelto via _smart_component_match al aplicar)

    application_mode: Mapped[str] = mapped_column(String(30), default='specific_equipment')
    target_equipment_id: Mapped[Optional[int]] = mapped_column(ForeignKey('equipments.id'), nullable=True)
    target_area_id: Mapped[Optional[int]] = mapped_column(ForeignKey('areas.id'), nullable=True)
    target_line_id: Mapped[Optional[int]] = mapped_column(ForeignKey('lines.id'), nullable=True)
    target_tag_pattern: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Regex (Python re): '^D[1-9]$' para D1..D9, '^TH\\d+$' para todos los TH

    # Solo aplica con application_mode='specific_equipment' — al elegir
    # cascada Area->Linea->Equipo->Sistema->Componente directamente, se
    # generan OTs precisas sin necesitar el matcher fuzzy.
    target_system_id: Mapped[Optional[int]] = mapped_column(ForeignKey('systems.id'), nullable=True)
    target_component_id: Mapped[Optional[int]] = mapped_column(ForeignKey('components.id'), nullable=True)

    template = relationship("ShutdownTemplate", back_populates="items")
    target_equipment = relationship("Equipment")
    target_area = relationship("Area")
    target_line = relationship("Line")
    target_system = relationship("System")
    target_component = relationship("Component")

    def to_dict(self):
        return {
            "id": self.id,
            "template_id": self.template_id,
            "order_index": self.order_index,
            "description": self.description,
            "maintenance_type": self.maintenance_type,
            "estimated_duration": self.estimated_duration,
            "tech_count": self.tech_count,
            "specialty": self.specialty,
            "component_name": self.component_name,
            "application_mode": self.application_mode,
            "target_equipment_id": self.target_equipment_id,
            "target_equipment_tag": self.target_equipment.tag if self.target_equipment else None,
            "target_equipment_name": self.target_equipment.name if self.target_equipment else None,
            "target_area_id": self.target_area_id,
            "target_area_name": self.target_area.name if self.target_area else None,
            "target_line_id": self.target_line_id,
            "target_line_name": self.target_line.name if self.target_line else None,
            "target_tag_pattern": self.target_tag_pattern,
            "target_system_id": self.target_system_id,
            "target_system_name": self.target_system.name if self.target_system else None,
            "target_component_id": self.target_component_id,
            "target_component_name_resolved": self.target_component.name if self.target_component else None,
        }


# ============= PROGRAMA NOCTURNO SEMANAL =============

class WeeklyPlan(db.Model):
    """Programa semanal de mantenimiento preventivo (turno noche).

    Un plan por semana con 2 técnicos × 12 h = 24 h-h por noche (ajustable).
    El proveedor lo ejecuta mediante un link público tokenizado.
    """
    __tablename__ = 'weekly_plans'
    __table_args__ = (
        Index('ix_wplan_week_start', 'week_start'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    # PN-YYYY-WW (Programa Nocturno, año, semana ISO)
    week_start: Mapped[str] = mapped_column(String(20), nullable=False)  # 'YYYY-MM-DD' lunes
    week_end: Mapped[str] = mapped_column(String(20), nullable=False)    # 'YYYY-MM-DD' domingo
    provider_id: Mapped[int | None] = mapped_column(ForeignKey('providers.id'), nullable=True)
    tech_count: Mapped[int] = mapped_column(Integer, default=2)
    hours_per_night: Mapped[float] = mapped_column(Float, default=12.0)
    status: Mapped[str] = mapped_column(String(20), default='BORRADOR')
    # BORRADOR | PUBLICADO | EN_CURSO | CERRADO
    public_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # Token URL-safe para que el proveedor acceda sin login
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    provider = relationship("Provider")
    items = relationship("WeeklyPlanItem", backref="plan", cascade="all, delete-orphan")

    def to_dict(self, include_items=False):
        d = {
            "id": self.id,
            "code": self.code,
            "week_start": self.week_start,
            "week_end": self.week_end,
            "provider_id": self.provider_id,
            "provider_name": self.provider.name if self.provider else None,
            "tech_count": self.tech_count,
            "hours_per_night": self.hours_per_night,
            "weekly_capacity_hours": round(self.tech_count * self.hours_per_night * 7, 2),
            "status": self.status,
            "public_token": self.public_token,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_items:
            d["items"] = [it.to_dict() for it in self.items]
        return d


class WeeklyPlanItem(db.Model):
    """Tarea específica dentro del programa nocturno.

    Cada ítem vincula a un punto preventivo (lub/insp/mon) que se debe
    ejecutar en un día y área específicos de la semana.
    Al marcarlo como EJECUTADO se crea una OT con source_type/source_id
    y se actualiza automáticamente la próxima fecha del punto origen.
    """
    __tablename__ = 'weekly_plan_items'
    __table_args__ = (
        Index('ix_wpi_plan', 'plan_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('weekly_plans.id'), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Lun, 6=Dom
    area_id: Mapped[int | None] = mapped_column(ForeignKey('areas.id'), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    # Origen del preventivo (lubrication | inspection | monitoring | custom)
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Denormalizado para velocidad de render (evita joins constantes)
    source_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    equipment_tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_hours: Mapped[float] = mapped_column(Float, default=1.0)

    status: Mapped[str] = mapped_column(String(20), default='PLANIFICADO')
    # PLANIFICADO | EJECUTADO | OMITIDO
    executed_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    executed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    execution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    work_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # OT que se crea automáticamente al marcarlo como ejecutado

    area = relationship("Area")

    def to_dict(self):
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "day_of_week": self.day_of_week,
            "area_id": self.area_id,
            "area_name": self.area.name if self.area else None,
            "order_index": self.order_index,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_code": self.source_code,
            "source_name": self.source_name,
            "equipment_tag": self.equipment_tag,
            "description": self.description,
            "estimated_hours": self.estimated_hours,
            "status": self.status,
            "executed_at": self.executed_at,
            "executed_by": self.executed_by,
            "execution_notes": self.execution_notes,
            "work_order_id": self.work_order_id,
        }


# ============= PRODUCTION GOALS (Módulo Confiabilidad de Producción) =============

class ProductionGoal(db.Model):
    """Meta y rendimiento mensual de producción por área.

    Producción entrega dos números por mes/área:
      - monthly_avg_yield_tons  → TM de harina procesada producidas en promedio
      - monthly_target_tons     → meta mensual TM
    Con eso se calculan:
      - tons_per_hour           = yield / operating_hours_month
      - tons_lost               = Σ(downtime_hours × tons_per_hour) de OTs con paro
      - sacks_lost              = (tons_lost × 1000) / 50
      - required_availability   = (target / tons_per_hour) / operating_hours × 100
    """
    __tablename__ = 'production_goals'
    __table_args__ = (
        Index('ix_prod_goal_period_area', 'goal_period', 'area_id'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_period: Mapped[str] = mapped_column(String(7), nullable=False)  # 'YYYY-MM'
    area_id: Mapped[int | None] = mapped_column(ForeignKey('areas.id'), nullable=True)
    monthly_avg_yield_tons: Mapped[float] = mapped_column(Float, nullable=False)
    monthly_target_tons: Mapped[float] = mapped_column(Float, nullable=False)
    operating_hours_month: Mapped[float] = mapped_column(Float, default=720.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    area = relationship("Area")

    def to_dict(self):
        return {
            "id": self.id,
            "goal_period": self.goal_period,
            "area_id": self.area_id,
            "area_name": self.area.name if self.area else None,
            "monthly_avg_yield_tons": self.monthly_avg_yield_tons,
            "monthly_target_tons": self.monthly_target_tons,
            "operating_hours_month": self.operating_hours_month,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Hammer Batches / Lotes de Martillos (FAPMETAL) ────────────────────────────
# Modela los 3 lotes fisicos de martillos que rotan entre los molinos y el
# proveedor de rellenado (FAPMETAL). En cualquier momento dado: 2 lotes
# instalados (uno por molino) y 1 lote en transito (en FAPMETAL siendo
# rellenado, o ya rellenado en stock esperando proximo cambio).

class HammerBatch(db.Model):
    __tablename__ = 'hammer_batches'
    __table_args__ = (
        Index('ix_hb_state', 'state'),
        Index('ix_hb_is_active', 'is_active'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    # Estados:
    #   INSTALADO_M1, INSTALADO_M2, EN_FAPMETAL,
    #   RELLENADO_EN_STOCK, DESCARTADO
    state: Mapped[str] = mapped_column(String(30), nullable=False, default='RELLENADO_EN_STOCK')
    hammers_count: Mapped[int] = mapped_column(Integer, nullable=False, default=72)
    refill_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    purchased_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    discarded_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey('providers.id'), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    provider = relationship("Provider")
    movements = relationship(
        "HammerBatchMovement",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="HammerBatchMovement.event_date.desc()",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "state": self.state,
            "hammers_count": self.hammers_count,
            "refill_count": self.refill_count,
            "purchased_at": self.purchased_at,
            "discarded_at": self.discarded_at,
            "provider_id": self.provider_id,
            "provider_name": self.provider.name if self.provider else None,
            "notes": self.notes,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class HammerBatchMovement(db.Model):
    __tablename__ = 'hammer_batch_movements'
    __table_args__ = (
        Index('ix_hbm_batch_id', 'batch_id'),
        Index('ix_hbm_event_date', 'event_date'),
        Index('ix_hbm_event_type', 'event_type'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('hammer_batches.id'), nullable=False)
    # Tipos:
    #   INSTALAR_M1, RETIRAR_M1, INSTALAR_M2, RETIRAR_M2,
    #   ENVIAR_FAPMETAL, RECIBIR_RELLENADO, DESCARTAR, ALTA
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    event_date: Mapped[str] = mapped_column(String(20), nullable=False)
    state_from: Mapped[str | None] = mapped_column(String(30), nullable=True)
    state_to: Mapped[str | None] = mapped_column(String(30), nullable=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey('work_orders.id'), nullable=True)
    hammers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)

    batch = relationship("HammerBatch", back_populates="movements")
    work_order = relationship("WorkOrder")

    def to_dict(self):
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "batch_code": self.batch.code if self.batch else None,
            "event_type": self.event_type,
            "event_date": self.event_date,
            "state_from": self.state_from,
            "state_to": self.state_to,
            "work_order_id": self.work_order_id,
            "work_order_code": self.work_order.code if self.work_order else None,
            "hammers_count": self.hammers_count,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
        }


# ── Bot Usage / Telemetria del bot Telegram ───────────────────────────────────
# Cada llamada a Whisper (transcripcion) o DeepSeek (chat) se registra acá con
# tokens, latencia y costo estimado USD. Sirve para detectar abuso, anomalias,
# y darle visibilidad real al gasto en IA (que de otro modo es invisible).

class BotTelegramUser(db.Model):
    """Usuarios autorizados del bot Telegram con nombre asociado al chat_id.

    Reemplaza a la whitelist por variable de entorno (TELEGRAM_ALLOWED_CHAT_IDS):
    el admin gestiona altas/bajas desde /admin/telegram-users.
    El `nombre` se usa como reporter_name al crear avisos desde el bot.
    `rol` queda preparado para futuro gating (admin | reporter), pero hoy
    solo discrimina visualmente en el tablero.
    """
    __tablename__ = 'bot_telegram_users'

    chat_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rol: Mapped[str] = mapped_column(String(20), nullable=False, default='reporter')
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notas: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)

    def to_dict(self):
        return {
            "chat_id": self.chat_id,
            "nombre": self.nombre,
            "area": self.area,
            "rol": self.rol,
            "activo": self.activo,
            "notas": self.notas,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
        }


class BotUsage(db.Model):
    __tablename__ = 'bot_usage'
    __table_args__ = (
        Index('ix_bu_created_at', 'created_at'),
        Index('ix_bu_chat_id', 'chat_id'),
        Index('ix_bu_service', 'service'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service: Mapped[str] = mapped_column(String(20), nullable=False)  # whisper | deepseek
    model_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_cached: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='success')  # success | error | timeout
    error_msg: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "service": self.service,
            "model_name": self.model_name,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_cached": self.tokens_cached,
            "audio_bytes": self.audio_bytes,
            "audio_duration_s": self.audio_duration_s,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "status": self.status,
            "error_msg": self.error_msg,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
