from sqlalchemy import String, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import db

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
    description: Mapped[str] = mapped_column(Text, nullable=True)
    line_id: Mapped[int] = mapped_column(ForeignKey('lines.id'), nullable=False)
    
    line = relationship("Line", back_populates="equipments")
    systems = relationship("System", back_populates="equipment", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "tag": self.tag, "description": self.description, "line_id": self.line_id}

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
    
    system = relationship("System", back_populates="components")
    spare_parts = relationship("SparePart", back_populates="component", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description, "system_id": self.system_id}

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
