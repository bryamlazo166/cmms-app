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


class RolePermission(db.Model):
    """Configurable permissions per role per module."""
    __tablename__ = 'role_permissions'
    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, default=True)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    can_export: Mapped[bool] = mapped_column(Boolean, default=False)

    def to_dict(self):
        return {
            "id": self.id, "role": self.role, "module": self.module,
            "can_view": self.can_view, "can_edit": self.can_edit, "can_export": self.can_export,
        }


# Taxonomy: Area -> Line -> Equipment -> System -> Component -> SparePart

class Area(db.Model):
    __tablename__ = 'areas'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    
    lines = relationship("Line", back_populates="area", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description}

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
    
    line = relationship("Line", back_populates="equipments")
    systems = relationship("System", back_populates="equipment", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "tag": self.tag, "description": self.description, "criticality": self.criticality, "line_id": self.line_id}

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
    
    def to_dict(self):
        return {"id": self.id, "name": self.name, "specialty": self.specialty, "contact_info": self.contact_info, "is_active": self.is_active}

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
    request_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # F.Solicitud - when created
    treatment_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # F.Tratada - when OT started
    planning_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # F.Programado - from OT scheduled
    maintenance_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ot_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default='Pendiente') # Pendiente, En Progreso, Cerrado, Anulado
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True) # Reason for annulment

    # Link to preventive source (lubrication/inspection/monitoring point)
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    
    # Relationships
    work_order = relationship("WorkOrder", backref="assigned_personnel")
    technician = relationship("Technician")
    
    def to_dict(self):
        return {
            "id": self.id,
            "work_order_id": self.work_order_id,
            "technician_id": self.technician_id,
            "technician_name": self.technician.name if self.technician else None,
            "specialty": self.specialty,
            "hours_assigned": self.hours_assigned,
            "hours_worked": self.hours_worked
        }


class OTMaterial(db.Model):
    """Materials (spare parts or tools) assigned to a work order"""
    __tablename__ = 'ot_materials'
    __table_args__ = (
        Index('ix_otm_work_order_id', 'work_order_id'),
        Index('ix_otm_item_type_id', 'item_type', 'item_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey('work_orders.id'), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'tool' or 'warehouse'
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)  # ID of tool or warehouse item
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    
    # Relationship
    work_order = relationship("WorkOrder", backref="assigned_materials")
    
    def to_dict(self):
        return {
            "id": self.id,
            "work_order_id": self.work_order_id,
            "item_type": self.item_type,
            "item_id": self.item_id,
            "quantity": self.quantity
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
            "is_active": self.is_active
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
            "is_active": self.is_active
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
    warehouse_item_id: Mapped[int] = mapped_column(ForeignKey('warehouse_items.id'), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default='MECANICO')
    # MECANICO | ELECTRICO | CONSUMIBLE
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(String(250), nullable=True)

    asset = relationship("RotativeAsset")
    warehouse_item = relationship("WarehouseItem")

    def to_dict(self):
        wi = self.warehouse_item
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "warehouse_item_id": self.warehouse_item_id,
            "item_code": wi.code if wi else None,
            "item_name": wi.name if wi else None,
            "item_stock": wi.stock if wi else None,
            "item_unit": wi.unit if wi else None,
            "category": self.category,
            "quantity": self.quantity,
            "notes": self.notes,
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


