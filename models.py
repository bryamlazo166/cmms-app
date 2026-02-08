from sqlalchemy import String, Integer, ForeignKey, Text, Boolean, Float, Date, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import db
from datetime import datetime, date

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
    
    # Link to Work Order (One-to-One or One-to-Many? usually One)
    work_order = relationship("WorkOrder", back_populates="notice", uselist=False)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class WorkOrder(db.Model):
    __tablename__ = 'work_orders'
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
