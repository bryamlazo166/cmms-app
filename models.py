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


class LubricationPoint(db.Model):
    __tablename__ = 'lubrication_points'

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
