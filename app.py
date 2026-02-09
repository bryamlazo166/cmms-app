import os
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
import pandas as pd
from database import db
from datetime import datetime
import datetime as dt
from dotenv import load_dotenv

load_dotenv()

from models import (
    Area, Line, Equipment, System, Component, SparePart, MaintenanceNotice, 
    WorkOrder, Provider, Technician, Tool, WarehouseItem, OTPersonnel, 
    OTMaterial, WarehouseMovement, PurchaseOrder, PurchaseRequest
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Database Config
db_url = os.getenv('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///cmms_v2.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
print(f"----> APPLICATION STARTING ON PORT 5006 <----")
print(f"----> DATABASE: {'SUPABASE (PostgreSQL)' if db_url else 'LOCAL (SQLite)'} <----")

db.init_app(app)

# @app.route('/')
# def index():
#     return render_template('index.html')

@app.route('/configuracion')
def taxonomy_page():
    return render_template('taxonomy.html')

@app.route('/api/dashboard-stats', methods=['GET'])
def dashboard_stats():
    try:
        # 1. KPIs
        total_ots_open = WorkOrder.query.filter(WorkOrder.status != 'Cerrada').count()
        total_ots_closed = WorkOrder.query.filter_by(status='Cerrada').count()
        notices_pending = MaintenanceNotice.query.filter_by(status='Pendiente').count()
        active_techs = Technician.query.filter_by(is_active=True).count()
        
        # 2. OTs by Status (Chart)
        status_counts = db.session.query(WorkOrder.status, db.func.count(WorkOrder.status)).group_by(WorkOrder.status).all()
        status_data = {s: c for s, c in status_counts}
        
        # 3. OTs by Type (Chart)
        type_counts = db.session.query(WorkOrder.maintenance_type, db.func.count(WorkOrder.maintenance_type)).group_by(WorkOrder.maintenance_type).all()
        type_data = {t: c for t, c in type_counts}
        
        # 4. Top Failure Modes (from Notices)
        # Using simple SQL query for this might be easier or Python processing if small DB
        notices = MaintenanceNotice.query.filter(MaintenanceNotice.maintenance_type != None).all()
        # Count manually since failure_mode is on linked OT... actually wait, failure_mode is on WorkOrder now.
        
        # Top Failure Modes from WorkOrders
        failures = db.session.query(WorkOrder.failure_mode, db.func.count(WorkOrder.failure_mode))\
            .filter(WorkOrder.failure_mode != None, WorkOrder.failure_mode != "")\
            .group_by(WorkOrder.failure_mode)\
            .order_by(db.func.count(WorkOrder.failure_mode).desc())\
            .limit(5).all()
            
        failure_data = [{'mode': f, 'count': c} for f, c in failures]
        
        # 5. Recent Activity (Last 5 OTs)
        recent_ots = WorkOrder.query.order_by(WorkOrder.id.desc()).limit(5).all()
        recent_data = [{
            'code': ot.code,
            'desc': ot.description,
            'status': ot.status,
            'date': ot.scheduled_date
        } for ot in recent_ots]

        return jsonify({
            'kpi': {
                'open_ots': total_ots_open,
                'closed_ots': total_ots_closed,
                'pending_notices': notices_pending,
                'active_techs': active_techs
            },
            'charts': {
                'status': status_data,
                'types': type_data,
                'failures': failure_data
            },
            'recent': recent_data
        })
    except Exception as e:
        logger.error(f"Dashboard Stats Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    return redirect(url_for('notices_page'))

@app.route('/avisos')
def notices_page():
    return render_template('notices.html')

@app.route('/ordenes')
def work_orders_page():
    return render_template('work_orders.html')

@app.route('/almacen')
def warehouse_page():
    return render_template('warehouse.html')

@app.route('/reportes')
def reports_page():
    return render_template('reports.html')


@app.route('/herramientas')
def tools_page():
    return render_template('tools.html')

@app.route('/compras')
def purchasing_page():
    return render_template('purchasing.html')



@app.route('/api/providers', methods=['GET', 'POST'])
def handle_providers():
    if request.method == 'POST':
        return create_entry(Provider, request.json, ['name'])
    
    # Return only active providers
    providers = Provider.query.filter_by(is_active=True).all()
    return jsonify([p.to_dict() for p in providers])

@app.route('/api/providers/<int:id>', methods=['PUT', 'DELETE'])
def handle_provider_id(id):
    if request.method == 'PUT':
        return update_entry(Provider, id, request.json)
    
    # Soft Delete implementation
    try:
        provider = Provider.query.get(id)
        if not provider:
            return jsonify({"error": "Provider not found"}), 404
        
        provider.is_active = False
        db.session.commit()
        return jsonify({"message": "Provider deactivated"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# --- TECHNICIAN ENDPOINTS ---
@app.route('/api/technicians', methods=['GET', 'POST'])
def handle_technicians():
    if request.method == 'POST':
        return create_entry(Technician, request.json, ['name'])
    
    # Return only active by default, or all if requested
    show_all = request.args.get('all', 'false').lower() == 'true'
    if show_all:
        technicians = Technician.query.all()
    else:
        technicians = Technician.query.filter_by(is_active=True).all()
    return jsonify([t.to_dict() for t in technicians])

@app.route('/api/technicians/<int:id>', methods=['PUT', 'DELETE'])
def handle_technician_id(id):
    if request.method == 'PUT':
        return update_entry(Technician, id, request.json)
    
    # Soft Delete (toggle active status)
    try:
        tech = Technician.query.get(id)
        if not tech:
            return jsonify({"error": "Technician not found"}), 404
        
        tech.is_active = not tech.is_active  # Toggle
        db.session.commit()
        return jsonify({"message": f"Technician {'activated' if tech.is_active else 'deactivated'}"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# --- TOOLS ENDPOINTS ---
@app.route('/api/tools', methods=['GET', 'POST'])
def handle_tools():
    if request.method == 'POST':
        try:
            data = request.json
            # Generate code
            last = Tool.query.order_by(Tool.id.desc()).first()
            next_id = (last.id if last else 0) + 1
            data['code'] = f"HRR-{next_id:03d}"
            
            tool = Tool(**data)
            db.session.add(tool)
            db.session.commit()
            return jsonify(tool.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    # GET - return active tools
    show_all = request.args.get('all', 'false').lower() == 'true'
    if show_all:
        tools = Tool.query.all()
    else:
        tools = Tool.query.filter_by(is_active=True).all()
    return jsonify([t.to_dict() for t in tools])

@app.route('/api/tools/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def handle_tool_id(id):
    tool = Tool.query.get_or_404(id)
    
    if request.method == 'GET':
        return jsonify(tool.to_dict())
    
    if request.method == 'PUT':
        data = request.json
        for key, value in data.items():
            if hasattr(tool, key):
                setattr(tool, key, value)
        db.session.commit()
        return jsonify(tool.to_dict())
    
    # DELETE - soft delete
    tool.is_active = not tool.is_active
    db.session.commit()
    return jsonify({"message": f"Tool {'activated' if tool.is_active else 'deactivated'}"})

# --- WAREHOUSE ENDPOINTS ---
@app.route('/api/warehouse', methods=['GET', 'POST'])
def handle_warehouse():
    if request.method == 'POST':
        try:
            data = request.json
            # Generate code
            last = WarehouseItem.query.order_by(WarehouseItem.id.desc()).first()
            next_id = (last.id if last else 0) + 1
            data['code'] = f"REP-{next_id:04d}"
            
            # Sanitization for models
            valid_keys = {c.name for c in WarehouseItem.__table__.columns}
            clean_data = {k: v for k, v in data.items() if k in valid_keys}

            item = WarehouseItem(**clean_data)
            db.session.add(item)
            db.session.commit()
            return jsonify(item.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    # GET
    show_all = request.args.get('all')
    query = WarehouseItem.query
    if not show_all:
        query = query.filter_by(is_active=True)
    
    items = query.all()
    return jsonify([i.to_dict() for i in items])

@app.route('/api/warehouse/<int:id>', methods=['PUT', 'DELETE'])
def handle_warehouse_id(id):
    try:
        item = WarehouseItem.query.get(id)
        if not item:
            return jsonify({"error": "Item not found"}), 404
            
        if request.method == 'DELETE':
            item.is_active = not item.is_active # Toggle
            db.session.commit()
            return jsonify({"message": "Status toggled"}), 200
            
        if request.method == 'PUT':
            data = request.json
            for k, v in data.items():
                if hasattr(item, k):
                    setattr(item, k, v)
            db.session.commit()
            return jsonify(item.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/warehouse/export', methods=['GET'])
def export_warehouse_excel():
    try:
        items = WarehouseItem.query.all()
        data = []
        
        for i in items:
            data.append({
                'ID': i.id,
                'Código': i.code,
                'Nombre': i.name,
                'Descripción': i.description,
                'Familia': i.family,
                'Marca': i.brand,
                'Categoría': i.category,
                'Stock Actual': i.stock,
                'Unidad': i.unit,
                'Ubicación': i.location,
                'Criticidad': i.criticality,
                'Costo Promedio': i.average_cost,
                'Costo Unitario': i.unit_cost,
                'ABC': i.abc_class,
                'XYZ': i.xyz_class,
                'Lead Time (Días)': i.lead_time,
                'Stock Seguridad': i.safety_stock,
                'Punto Reorden (ROP)': i.rop,
                'Stock Máximo': i.max_stock,
                'Lote Mínimo': i.min_order_qty,
                'Activo': 'Sí' if i.is_active else 'No'
            })
            
        df = pd.DataFrame(data)
        
        from io import BytesIO
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Inventario')
            
        output.seek(0)
        
        from flask import send_file
        return send_file(output, download_name="Inventario_Maestro_CMMS.xlsx", as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        logger.error(f"Warehouse Export Failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/warehouse/export-kardex', methods=['GET'])
def export_kardex_excel():
    try:
        movements = WarehouseMovement.query.order_by(WarehouseMovement.date.desc()).all()
        data = []
        
        for m in movements:
            item_code = m.item.code if m.item else 'Unknown'
            item_name = m.item.name if m.item else 'Unknown'
            
            data.append({
                'Fecha': m.date,
                'Tipo': m.movement_type,
                'Item': f"{item_code} - {item_name}",
                'Cantidad': m.quantity,
                'Razón': m.reason,
                'Referencia': m.reference_id
            })
            
        df = pd.DataFrame(data)
        
        from io import BytesIO
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Kardex')
            
        output.seek(0)
        
        from flask import send_file
        return send_file(output, download_name="Kardex_CMMS.xlsx", as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        logger.error(f"Kardex Export Failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/warehouse/calculate', methods=['POST'])
def calculate_inventory_params():
    """
    Recalculate ABC/XYZ and ROP for all items provided (or all active).
    ABC: Based on Usage Value (Qty * Cost).
    XYZ: Based on Coefficient of Variation.
    ROP: (AvgDailyUsage * LeadTime) + SafetyStock.
    """
    try:
        import pandas as pd
        import numpy as np
        from datetime import datetime
        
        # 1. Fetch Data
        items = WarehouseItem.query.filter_by(is_active=True).all()
        movements = WarehouseMovement.query.filter(WarehouseMovement.movement_type.in_(['OUT', 'ADJUST'])).all()
        
        # Create DF
        mov_data = []
        for m in movements:
            mov_data.append({
                'item_id': m.item_id,
                'qty': abs(m.quantity),
                'date': m.date[:10] # YYYY-MM-DD
            })
        
        df = pd.DataFrame(mov_data)
        
        updates_log = []

        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            # 12-month window
            start_date = pd.Timestamp.now() - pd.DateOffset(months=12)
            df = df[df['date'] >= start_date]
        
        # Helper for ABC/XYZ
        # Calculate Total Usage per Item
        if not df.empty:
             usage_per_item = df.groupby('item_id')['qty'].sum()
        else:
             usage_per_item = pd.Series()

        # Calculate Monthly Variability for XYZ
        xyz_map = {}
        if not df.empty:
            df['month'] = df['date'].dt.to_period('M')
            monthly_usage = df.groupby(['item_id', 'month'])['qty'].sum().reset_index()
            stats = monthly_usage.groupby('item_id')['qty'].agg(['mean', 'std'])
            stats['cv'] = stats['std'] / stats['mean']
            
            for item_id, row in stats.iterrows():
                cv = row['cv']
                if pd.isna(cv) or cv < 0.2: xyz = 'X'
                elif cv < 0.5: xyz = 'Y'
                else: xyz = 'Z'
                xyz_map[item_id] = xyz
        
        # Sort for ABC
        # Need cost
        item_usage_vals = []
        for item in items:
            total_qty = usage_per_item.get(item.id, 0)
            val = total_qty * (item.average_cost if item.average_cost else (item.unit_cost or 0))
            item_usage_vals.append({'item': item, 'val': val, 'qty': total_qty})
            
        # Sort desc
        item_usage_vals.sort(key=lambda x: x['val'], reverse=True)
        total_value_inventory = sum(x['val'] for x in item_usage_vals)
        
        cum_val = 0
        for entry in item_usage_vals:
            item = entry['item']
            val = entry['val']
            qty = entry['qty']
            
            cum_val += val
            pct = cum_val / total_value_inventory if total_value_inventory > 0 else 0
            
            # ABC Logic
            if pct <= 0.80: abc = 'A'
            elif pct <= 0.95: abc = 'B'
            else: abc = 'C'
            
            # XYZ Logic
            xyz = xyz_map.get(item.id, 'Z') # Default Z if no history
            
            # ROP Calculation
            # 1. Avg Daily Usage
            avg_daily = qty / 365.0
            lead_time = item.lead_time or 0
            
            # Safety Stock (Simple Formula if 0)
            # SS = Z * Sigma * sqrt(L). Assuming simplified: 50% of Lead Time Demand if not set?
            # Let's keep existing SS if set, else suggest
            ss = item.safety_stock
            if ss == 0 and avg_daily > 0:
                 ss = int(avg_daily * lead_time * 0.5) # Fallback heuristic
            
            rop = (avg_daily * lead_time) + ss
            
            # Update Item
            item.abc_class = abc
            item.xyz_class = xyz
            item.safety_stock = int(ss)
            item.rop = int(np.ceil(rop))
            
            updates_log.append(f"{item.code}: {abc}{xyz} ROP={item.rop}")
            
        db.session.commit()
        return jsonify({"message": "Calculations OK", "log": updates_log}), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# --- OT PERSONNEL ENDPOINTS ---
@app.route('/api/work_orders/<int:ot_id>/personnel', methods=['GET', 'POST'])
def handle_ot_personnel(ot_id):
    if request.method == 'POST':
        try:
            data = request.json
            
            # Handle array format: { personnel: [{...}, {...}] }
            if 'personnel' in data:
                personnel_list = data['personnel']
                logger.info(f"Processing personnel list: {len(personnel_list)} items")
                
                # Clear existing personnel for this OT
                OTPersonnel.query.filter_by(work_order_id=ot_id).delete()
                
                # Add new personnel
                for p in personnel_list:
                    # Ensure technician_id is properly converted to int or None
                    tech_id = p.get('technician_id')
                    try:
                        if tech_id is not None:
                            tech_id = int(tech_id)
                    except (ValueError, TypeError):
                        tech_id = None
                    
                    # Ensure hours is float
                    try:
                        h_val = p.get('hours', p.get('hours_assigned', 8))
                        hours = float(h_val) if h_val is not None else 8.0
                    except:
                        hours = 8.0
                    
                    person = OTPersonnel(
                        work_order_id=ot_id,
                        technician_id=tech_id,
                        specialty=p.get('specialty') or None,
                        hours_assigned=hours
                    )
                    db.session.add(person)
                
                db.session.commit()
                return jsonify({"message": f"Saved {len(personnel_list)} personnel"}), 201
            
            else:
                # Handle single object format (legacy)
                data['work_order_id'] = ot_id
                if 'hours' in data:
                    data['hours_assigned'] = data.pop('hours')
                
                # Remove keys that might cause issues if they sneaked in
                data.pop('personnel', None) 
                
                personnel = OTPersonnel(**data)
                db.session.add(personnel)
                db.session.commit()
                return jsonify(personnel.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Error saving personnel: {e}\n{error_details}")
            return jsonify({"error": str(e), "details": error_details}), 500
    
    # GET - return personnel for this OT
    try:
        personnel = OTPersonnel.query.filter_by(work_order_id=ot_id).all()
        return jsonify([p.to_dict() for p in personnel])
    except Exception as e:
        import traceback
        logger.error(f"Error loading personnel for OT {ot_id}: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/work_orders/<int:ot_id>/personnel/<int:id>', methods=['PUT', 'DELETE'])
def handle_ot_personnel_id(ot_id, id):
    personnel = OTPersonnel.query.get_or_404(id)
    
    if request.method == 'PUT':
        data = request.json
        for key, value in data.items():
            if hasattr(personnel, key):
                setattr(personnel, key, value)
        db.session.commit()
        return jsonify(personnel.to_dict())
    
    # DELETE
    db.session.delete(personnel)
    db.session.commit()
    return jsonify({"message": "Personnel removed"})

# --- OT MATERIALS ENDPOINTS ---
@app.route('/api/work_orders/<int:ot_id>/materials', methods=['GET', 'POST'])
def handle_ot_materials(ot_id):
    if request.method == 'POST':
        try:
            data = request.json
            data['work_order_id'] = ot_id
            
            # Safety Checks
            if not data.get('item_id'):
                return jsonify({"error": "Item ID is required"}), 400
            
            try:
                qty = int(data.get('quantity', 1))
                if qty <= 0: raise ValueError
            except:
                return jsonify({"error": "Quantity must be a positive integer"}), 400

            # Inventory Logic
            if data['item_type'] == 'warehouse':
                item = WarehouseItem.query.get(data['item_id'])
                
                if not item:
                    return jsonify({"error": "Item not found"}), 404
                    
                if item.stock < qty:
                    return jsonify({"error": f"Stock insuficiente. Disponible: {item.stock}"}), 400
                    
                # Deduct Stock
                item.stock -= qty
                
                # Record Movement
                move = WarehouseMovement(
                    item_id=item.id,
                    quantity=-qty,
                    movement_type='OUT',
                    date=datetime.now().isoformat(),
                    reference_id=ot_id,
                    reason=f"Uso en OT-{ot_id}"
                )
                db.session.add(move)
            
            elif data['item_type'] == 'tool':
                # Validate it exists in Warehouse but DO NOT deduct stock
                item = WarehouseItem.query.get(data['item_id'])
                if not item:
                    return jsonify({"error": "Herramienta no encontrada en Almacén"}), 404
                # No stock deduction for tools

            material = OTMaterial(**data)
            db.session.add(material)
            db.session.commit()
            return jsonify(material.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    # GET - return materials for this OT
    materials = OTMaterial.query.filter_by(work_order_id=ot_id).all()
    
    # Enrich with item names
    result = []
    for m in materials:
        data = m.to_dict()
        # Always fetch from WarehouseItem now (Unified Catalog)
        item = WarehouseItem.query.get(m.item_id)
        data['item_name'] = item.name if item else 'Unknown'
        data['item_code'] = item.code if item else ''
        data['item_category'] = item.category if item else ''
        
        result.append(data)
    
    return jsonify(result)

@app.route('/api/work_orders/<int:ot_id>/materials/<int:id>', methods=['PUT', 'DELETE'])
def handle_ot_material_id(ot_id, id):
    material = OTMaterial.query.get_or_404(id)
    
    if request.method == 'PUT':
        data = request.json
        for key, value in data.items():
            if hasattr(material, key):
                setattr(material, key, value)
        db.session.commit()
        return jsonify(material.to_dict())
    
    # DELETE
    # DELETE with Stock Return
    if material.item_type == 'warehouse':
        item = WarehouseItem.query.get(material.item_id)
        if item:
            qty = material.quantity
            item.stock += qty # Return stock
            
            # Record Movement
            move = WarehouseMovement(
                item_id=item.id,
                quantity=qty,
                movement_type='RETURN',
                date=datetime.now().isoformat(),
                reference_id=ot_id,
                reason=f"Devolución de OT-{ot_id}"
            )
            db.session.add(move)

    db.session.delete(material)
    db.session.commit()
    return jsonify({"message": "Material removed"})

@app.route('/api/work-orders', methods=['GET', 'POST'])
def handle_work_orders():
    if request.method == 'POST':
        try:
            data = request.json
            
            # SANITIZATION: Only keep fields that exist in Model
            valid_keys = {c.name for c in WorkOrder.__table__.columns}
            clean_data = {k: v for k, v in data.items() if k in valid_keys}
            
            # Convert empty strings to None
            for k, v in clean_data.items():
                if isinstance(v, str) and v.strip() == "":
                    clean_data[k] = None
            
            # Generate Code
            last = WorkOrder.query.order_by(WorkOrder.id.desc()).first()
            next_id = (last.id if last else 0) + 1
            clean_data['code'] = f"OT-{next_id:04d}"
            
            # Create work order
            wo = WorkOrder(**clean_data)
            db.session.add(wo)
            db.session.flush()  # Get the ID
            
            # If created from notice, update notice status
            if clean_data.get('notice_id'):
                notice = MaintenanceNotice.query.get(clean_data['notice_id'])
                if notice:
                    notice.status = 'En Tratamiento'
                    notice.ot_number = wo.code
            
            db.session.commit()
            return jsonify(wo.to_dict()), 201
            
        except Exception as e:
            db.session.rollback()
            import traceback
            traceback.print_exc()
            logger.error(f"Error creating work order: {e}")
            return jsonify({"error": str(e)}), 500
    
    entries = WorkOrder.query.all()
    # Enrich with hierarchy names
    results = []
    for wo in entries:
        data = wo.to_dict()
        
        # Helper to safely get name
        def get_name(obj): return obj.name if obj else '-'
        
        # Resolve relations
        area = Area.query.get(wo.area_id) if wo.area_id else None
        line = Line.query.get(wo.line_id) if wo.line_id else None
        equip = Equipment.query.get(wo.equipment_id) if wo.equipment_id else None
        system = System.query.get(wo.system_id) if wo.system_id else None
        component = Component.query.get(wo.component_id) if wo.component_id else None
        
        data['area_name'] = get_name(area)
        data['line_name'] = get_name(line)
        data['equipment_name'] = get_name(equip)
        data['system_name'] = get_name(system)
        data['component_name'] = get_name(component)
        
        # Determine Criticality
        crit = '-'
        if component and component.criticality: crit = component.criticality
        elif equip and equip.criticality: crit = equip.criticality
        # Check notice linked criticality if not found in asset
        if crit == '-' and wo.notice and wo.notice.criticality:
            crit = wo.notice.criticality
            
        data['criticality'] = crit
        
        results.append(data)

    return jsonify(results)

@app.route('/api/export-ots', methods=['GET'])
def export_work_orders_excel():
    try:
        entries = WorkOrder.query.all()
        data = []
        
        for wo in entries:
            # Helper for names
            def get_name(obj): return obj.name if obj else '-'
            
            area = Area.query.get(wo.area_id) if wo.area_id else None
            line = Line.query.get(wo.line_id) if wo.line_id else None
            equip = Equipment.query.get(wo.equipment_id) if wo.equipment_id else None
            sys = System.query.get(wo.system_id) if wo.system_id else None
            comp = Component.query.get(wo.component_id) if wo.component_id else None
            
            # Provider
            provider_name = '-'
            if wo.provider_id:
                p = Provider.query.get(wo.provider_id)
                if p: provider_name = p.name
            
            # Notice Code
            notice_code = '-'
            if wo.notice_id:
                n = MaintenanceNotice.query.get(wo.notice_id)
                if n: notice_code = n.code
            
            data.append({
                'Código': wo.code,
                'Aviso Relacionado': notice_code,
                'Área': get_name(area),
                'Línea': get_name(line),
                'Equipo': get_name(equip),
                'TAG Equipo': equip.tag if equip else '-',
                'Sistema': get_name(sys),
                'Componente': get_name(comp),
                'Criticidad': comp.criticality if comp and comp.criticality else (equip.criticality if equip else '-'),
                'Descripción OT': wo.description,
                'Modo de Falla': wo.failure_mode,
                'Tipo Mtto': wo.maintenance_type,
                'Estado': wo.status,
                'Técnico Principal': wo.technician_id,
                'Cant. Técnicos': wo.tech_count,
                'Proveedor': provider_name,
                'Fecha Programada': wo.scheduled_date,
                'Duración Est. (Hr)': wo.estimated_duration,
                'Fecha Inicio Real': wo.real_start_date,
                'Fecha Fin Real': wo.real_end_date,
                'Duración Real (Hr)': wo.real_duration,
                'Comentarios Ejecución': wo.execution_comments
            })
            
        df = pd.DataFrame(data)
        
        from io import BytesIO
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='OrdenesTrabajo')
            
        output.seek(0)
        
        from flask import send_file
        return send_file(output, download_name="Reporte_OTs_Completo.xlsx", as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        logger.error(f"OT Export Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/work-orders/<int:id>', methods=['PUT', 'DELETE'])
def handle_wot_id(id):
    try:
        if request.method == 'PUT':
            data = request.json
            logger.info(f"Updating OT {id} with data: {data}")
            
            # First update the work order
            wo = WorkOrder.query.get(id)
            if not wo:
                return jsonify({"error": "Work Order not found"}), 404
            
            for key, value in data.items():
                if hasattr(wo, key):
                    if isinstance(value, str) and value.strip() == "":
                        value = None
                    setattr(wo, key, value)
            
            # If WO is being closed, sync to associated notice
            if data.get('status') == 'Cerrada' and wo.notice_id:
                notice = MaintenanceNotice.query.get(wo.notice_id)
                if notice:
                    notice.status = 'Cerrado'
                    notice.ot_number = wo.code
            
            # AUTO-LEARNING: Update Component's criticality if provided
            # This allows the system to "learn" the criticality for future notices
            criticality_value = data.get('priority') or data.get('criticality')
            if criticality_value and wo.component_id:
                comp = Component.query.get(wo.component_id)
                if comp:
                    comp.criticality = criticality_value
                    logger.info(f"Updated Component {comp.id} criticality to '{criticality_value}'")
            
            db.session.commit()
            return jsonify(wo.to_dict())
            
        return delete_entry(WorkOrder, id)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating OT {id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



@app.route('/api/notices', methods=['GET', 'POST'])
@app.route('/api/notices', methods=['GET', 'POST'])
def handle_notices():
    if request.method == 'POST':
        try:
            data = request.json
            logger.info(f"Received notice data: {data}")
            
            # SANITIZATION: Only keep fields that exist in Model
            valid_keys = {c.name for c in MaintenanceNotice.__table__.columns}
            clean_data = {k: v for k, v in data.items() if k in valid_keys}
            
            # Convert empty strings to None
            for k, v in clean_data.items():
                if isinstance(v, str) and v.strip() == "":
                    clean_data[k] = None
                    
            logger.info(f"Cleaned notice data: {clean_data}")
                    
            # Generate Code
            last = MaintenanceNotice.query.order_by(MaintenanceNotice.id.desc()).first()
            next_id = (last.id if last else 0) + 1
            clean_data['code'] = f"AV-{next_id:04d}"

            # --- DUPLICATE DETECTION LOGIC ---
            is_duplicate = False
            duplicate_reason = ""
            
            target_equip = clean_data.get('equipment_id')
            if target_equip:
                # 1. Check for Active Notices (Pendiente, En Progreso, En Tratamiento)
                existing_notice = MaintenanceNotice.query.filter(
                    MaintenanceNotice.equipment_id == target_equip,
                    MaintenanceNotice.status.in_(['Pendiente', 'En Progreso', 'En Tratamiento'])
                ).first()
                
                if existing_notice:
                    is_duplicate = True
                    duplicate_reason = f"Aviso previo activo ({existing_notice.code})"

                # 2. Check for Active Work Orders (Abierta, Programada, En Progreso)
                if not is_duplicate:
                    existing_ot = WorkOrder.query.filter(
                        WorkOrder.equipment_id == target_equip,
                        WorkOrder.status.in_(['Abierta', 'Programada', 'En Progreso'])
                    ).first()
                    
                    if existing_ot:
                        is_duplicate = True
                        duplicate_reason = f"OT activa asociada ({existing_ot.code})"
            
            if is_duplicate:
                clean_data['status'] = 'Duplicado'
                original_desc = clean_data.get('description', '') or ''
                clean_data['description'] = f"[POSIBLE DUPLICADO: {duplicate_reason}] {original_desc}"
                logger.warning(f"Notice marked as duplicate: {duplicate_reason}")

            new_entry = MaintenanceNotice(**clean_data)
            db.session.add(new_entry)
            db.session.commit()
            
            resp_data = new_entry.to_dict()
            if is_duplicate:
                resp_data['is_duplicate'] = True
                resp_data['duplicate_reason'] = duplicate_reason
                
            return jsonify(resp_data), 201
        except Exception as e:
            db.session.rollback()
            import traceback
            traceback.print_exc()
            logger.error(f"Error creating notice: {e}")
            return jsonify({"error": str(e)}), 500
    
    entries = MaintenanceNotice.query.all()
    results = []
    
    # Pre-fetch cache to avoid N+1 if possible, but for simplicity we'll do direct lookups first or simple caching
    # Better: just resolve per item.
    
    for notice in entries:
        data = notice.to_dict()
        
        # Resolve Equipment ID
        equip_id = None
        if notice.equipment_id:
            equip_id = notice.equipment_id
        elif notice.system_id:
            # We need to import System/Component/Equipment if not available globally. 
            # Assuming they are available as they are models.
            try:
                sys = System.query.get(notice.system_id)
                if sys: equip_id = sys.equipment_id
            except: pass
        elif notice.component_id:
            try:
                comp = Component.query.get(notice.component_id)
                if comp:
                    sys = System.query.get(comp.system_id)
                    if sys: equip_id = sys.equipment_id
            except: pass
            
        # Calculate Failure Count (Corrective + Closed)
        failure_count = 0
        if equip_id:
            try:
                failure_count = WorkOrder.query.filter_by(
                    equipment_id=equip_id,
                    maintenance_type='Correctivo',
                    status='Cerrada'
                ).count()
            except Exception as e:
                logger.error(f"Error counting failures for equip {equip_id}: {e}")
        
                logger.error(f"Error counting failures for equip {equip_id}: {e}")
        
        data['failure_count'] = failure_count
        
        # Include Failure Mode from linked OT if exists
        data['failure_mode'] = '-'
        if notice.work_order:
             data['failure_mode'] = notice.work_order.failure_mode or '-'
             
        results.append(data)

    return jsonify(results)

@app.route('/api/notices/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def handle_notice_id(id):
    if request.method == 'GET':
        notice = MaintenanceNotice.query.get(id)
        if not notice:
            return jsonify({"error": "Notice not found"}), 404
        return jsonify(notice.to_dict())
    if request.method == 'PUT':
        return update_entry(MaintenanceNotice, id, request.json)
    return delete_entry(MaintenanceNotice, id)

@app.route('/api/initialize', methods=['POST'])
def initialize_db():
    try:
        with app.app_context():
            db.drop_all() # CLEAN SLATE
            db.create_all()
            logger.info("Database (re)initialized successfully.")
        return jsonify({"message": "DB reset success"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- GENERIC CRUD HELPERS ---
# --- GENERIC CRUD HELPERS ---
def create_entry(Model, data, required_fields):
    try:
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing {field}"}), 400
        
        new_entry = Model(**data)
        db.session.add(new_entry)
        db.session.commit()
        return jsonify(new_entry.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        logger.error(f"Error creating {Model.__name__}: {e}")
        return jsonify({"error": str(e)}), 500

def get_entries(Model):
    entries = Model.query.all()
    return jsonify([e.to_dict() for e in entries])

def update_entry(Model, id, data):
    try:
        # Use .get() instead of get_or_404 to control the response
        entry = Model.query.get(id)
        if not entry:
            return jsonify({"error": f"{Model.__name__} with ID {id} not found"}), 404
            
        for key, value in data.items():
            if hasattr(entry, key):
                # Convert empty strings to None for nullable fields
                if isinstance(value, str) and value.strip() == "":
                    value = None
                setattr(entry, key, value)
        db.session.commit()
        return jsonify(entry.to_dict())
    except Exception as e:
        db.session.rollback()
        logger.error(f"Update Error: {e}")
        return jsonify({"error": str(e)}), 500

def delete_entry(Model, id):
    try:
        entry = Model.query.get(id)
        if not entry:
            return jsonify({"error": f"{Model.__name__} with ID {id} not found"}), 404

        db.session.delete(entry)
        db.session.commit()
        return jsonify({"message": "Deleted successfully"})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Delete Error: {e}")
        return jsonify({"error": str(e)}), 500

# --- ENDPOINTS ---

@app.route('/api/areas', methods=['GET', 'POST'])
def handle_areas():
    if request.method == 'POST':
        return create_entry(Area, request.json, ['name'])
    return get_entries(Area)

@app.route('/api/areas/<int:id>', methods=['PUT', 'DELETE'])
def handle_area_id(id):
    if request.method == 'PUT':
        return update_entry(Area, id, request.json)
    return delete_entry(Area, id)

@app.route('/api/lines', methods=['GET', 'POST'])
def handle_lines():
    if request.method == 'POST':
        return create_entry(Line, request.json, ['name', 'area_id'])
    return get_entries(Line)

@app.route('/api/lines/<int:id>', methods=['PUT', 'DELETE'])
def handle_line_id(id):
    if request.method == 'PUT':
        return update_entry(Line, id, request.json)
    return delete_entry(Line, id)

@app.route('/api/equipments', methods=['GET', 'POST'])
def handle_equipments():
    if request.method == 'POST':
        return create_entry(Equipment, request.json, ['name', 'tag', 'line_id'])
    return get_entries(Equipment)

@app.route('/api/equipments/<int:id>', methods=['PUT', 'DELETE'])
def handle_equipment_id(id):
    if request.method == 'PUT':
        return update_entry(Equipment, id, request.json)
    return delete_entry(Equipment, id)

@app.route('/api/systems', methods=['GET', 'POST'])
def handle_systems():
    if request.method == 'POST':
        return create_entry(System, request.json, ['name', 'equipment_id'])
    return get_entries(System)

@app.route('/api/systems/<int:id>', methods=['PUT', 'DELETE'])
def handle_system_id(id):
    if request.method == 'PUT':
        return update_entry(System, id, request.json)
    return delete_entry(System, id)

@app.route('/api/warehouse/movements', methods=['POST'])
def handle_warehouse_movements():
    try:
        data = request.json
        # Expects: item_id, quantity, type (IN/ADJUST), reason
        item_id = data.get('item_id')
        qty = int(data.get('quantity', 0))
        m_type = data.get('movement_type', 'IN')
        reason = data.get('reason', 'Ingreso Manual')
        
        if not item_id or qty <= 0:
             return jsonify({"error": "Invalid data"}), 400
             
        item = WarehouseItem.query.get(item_id)
        if not item:
            return jsonify({"error": "Item not found"}), 404
            
        # Update Stock
        if m_type == 'IN':
            item.stock += qty
        elif m_type == 'OUT':
             item.stock -= qty
        
        # Record
        move = WarehouseMovement(
            item_id=item_id,
            quantity=qty if m_type == 'IN' else -qty,
            movement_type=m_type,
            date=datetime.now().isoformat(),
            reason=reason
        )
        db.session.add(move)
        db.session.commit()
        return jsonify(move.to_dict()), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/warehouse/<int:id>/movements', methods=['GET'])
def handle_item_movements(id):
    moves = WarehouseMovement.query.filter_by(item_id=id).order_by(WarehouseMovement.id.desc()).all()
    return jsonify([m.to_dict() for m in moves])


@app.route('/api/components', methods=['GET', 'POST'])
def handle_components():
    if request.method == 'POST':
        return create_entry(Component, request.json, ['name', 'system_id'])
    return get_entries(Component)

@app.route('/api/components/<int:id>', methods=['PUT', 'DELETE'])
def handle_component_id(id):
    if request.method == 'PUT':
        return update_entry(Component, id, request.json)
    return delete_entry(Component, id)

@app.route('/api/spare-parts', methods=['GET', 'POST'])
def handle_spare_parts():
    if request.method == 'POST':
        # name, code, brand, quantity, component_id
        return create_entry(SparePart, request.json, ['name', 'component_id'])
    return get_entries(SparePart)

@app.route('/api/spare-parts/<int:id>', methods=['PUT', 'DELETE'])
def handle_spare_part_id(id):
    if request.method == 'PUT':
        return update_entry(SparePart, id, request.json)
    return delete_entry(SparePart, id)

@app.route('/api/upload-excel', methods=['POST'])
def upload_excel():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        # Load Excel using Pandas
        xls = pd.ExcelFile(file)
        
        # 1. AREAS
        if 'Areas' in xls.sheet_names:
            df = pd.read_excel(xls, 'Areas')
            df = df.where(pd.notnull(df), None) # Replace NaN with None
            for _, row in df.iterrows():
                if row['Name'] and not Area.query.filter_by(name=str(row['Name'])).first():
                    db.session.add(Area(name=str(row['Name']), description=row.get('Description', '') or ''))
            db.session.commit()
            
        # 2. LINES (Requires Area Name)
        if 'Lines' in xls.sheet_names:
            df = pd.read_excel(xls, 'Lines')
            df = df.where(pd.notnull(df), None)
            for _, row in df.iterrows():
                area = Area.query.filter_by(name=str(row['AreaName'])).first()
                if area and row['Name'] and not Line.query.filter_by(name=str(row['Name']), area_id=area.id).first():
                    db.session.add(Line(name=str(row['Name']), description=row.get('Description', '') or '', area=area))
            db.session.commit()

        # 3. EQUIPMENTS (Requires Area Name -> Line Name)
        if 'Equipments' in xls.sheet_names:
            df = pd.read_excel(xls, 'Equipments')
            df = df.where(pd.notnull(df), None)
            for _, row in df.iterrows():
                # Find Area first
                area_name = row.get('AreaName')
                line_name = row.get('LineName')
                
                # If AreaName is provided, use it to filter lines strictly
                line_query = Line.query
                if area_name:
                    area = Area.query.filter_by(name=str(area_name)).first()
                    if area:
                        line_query = line_query.filter_by(area_id=area.id)
                    else:
                        continue # Area not found, skip
                
                line = line_query.filter_by(name=str(line_name)).first()
                
                if line and row['Name'] and not Equipment.query.filter_by(name=str(row['Name']), line_id=line.id).first():
                    db.session.add(Equipment(name=str(row['Name']), tag=str(row['Tag']), description=row.get('Description', '') or '', line=line))
            db.session.commit()
            
        # 4. SYSTEMS (Requires Area -> Line -> Equipment)
        if 'Systems' in xls.sheet_names:
            df = pd.read_excel(xls, 'Systems')
            df = df.where(pd.notnull(df), None)
            for _, row in df.iterrows():
                # Hierarchy lookup
                area_name = row.get('AreaName')
                line_name = row.get('LineName')
                equip_name = row.get('EquipmentName')
                
                equip_query = Equipment.query.join(Line).join(Area)
                
                if area_name:
                    equip_query = equip_query.filter(Area.name == str(area_name))
                if line_name:
                    equip_query = equip_query.filter(Line.name == str(line_name))
                    
                equip = equip_query.filter(Equipment.name == str(equip_name)).first()
                
                if equip and row['Name'] and not System.query.filter_by(name=str(row['Name']), equipment_id=equip.id).first():
                    db.session.add(System(name=str(row['Name']), equipment=equip))
            db.session.commit()

        # 5. COMPONENTS (Requires Area -> Line -> Equip -> System)
        if 'Components' in xls.sheet_names:
            df = pd.read_excel(xls, 'Components')
            df = df.where(pd.notnull(df), None)
            for _, row in df.iterrows():
                area_name = row.get('AreaName')
                line_name = row.get('LineName')
                equip_name = row.get('EquipmentName')
                sys_name = row.get('SystemName')
                
                sys_query = System.query.join(Equipment).join(Line).join(Area)
                
                if area_name: sys_query = sys_query.filter(Area.name == str(area_name))
                if line_name: sys_query = sys_query.filter(Line.name == str(line_name))
                if equip_name: sys_query = sys_query.filter(Equipment.name == str(equip_name))
                
                system = sys_query.filter(System.name == str(sys_name)).first()
                
                if system and row['Name'] and not Component.query.filter_by(name=str(row['Name']), system_id=system.id).first():
                    db.session.add(Component(name=str(row['Name']), description=row.get('Description', '') or '', system=system))
            db.session.commit()

        # 6. SPARE PARTS (Requires ... -> Component)
        if 'SpareParts' in xls.sheet_names:
            df = pd.read_excel(xls, 'SpareParts')
            df = df.where(pd.notnull(df), None)
            for _, row in df.iterrows():
                # Full hierarchy for maximum safety
                area_name = row.get('AreaName')
                line_name = row.get('LineName')
                equip_name = row.get('EquipmentName')
                sys_name = row.get('SystemName')
                comp_name = row.get('ComponentName')
                
                comp_query = Component.query.join(System).join(Equipment).join(Line).join(Area)
                
                if area_name: comp_query = comp_query.filter(Area.name == str(area_name))
                if line_name: comp_query = comp_query.filter(Line.name == str(line_name))
                if equip_name: comp_query = comp_query.filter(Equipment.name == str(equip_name))
                if sys_name: comp_query = comp_query.filter(System.name == str(sys_name))
                
                comp = comp_query.filter(Component.name == str(comp_name)).first()
                
                if comp and row['Name']:
                    db.session.add(SparePart(
                        name=str(row['Name']), 
                        code=str(row.get('Code', '') or ''), 
                        brand=str(row.get('Brand', '') or ''), 
                        quantity=int(row.get('Quantity', 0) or 0),
                        component=comp
                    ))
            db.session.commit()
            
        return jsonify({"message": "Masive Load Successful with strict hierarchy checks"}), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Excel Upload Failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/bulk-paste', methods=['POST'])
def bulk_paste():
    try:
        data = request.json
        entity_type = data.get('entity_type')
        raw_data = data.get('raw_data')

        if not entity_type or not raw_data:
            return jsonify({"error": "Missing entity_type or raw_data"}), 400

        from io import StringIO
        # Read as TSV (Excel copy-paste default)
        df = pd.read_csv(StringIO(raw_data), sep='\t')
        df = df.where(pd.notnull(df), None) # Replace NaN with None

        # 1. AREAS
        if entity_type == 'Areas':
            for _, row in df.iterrows():
                if row.get('Name') and not Area.query.filter_by(name=str(row['Name'])).first():
                    db.session.add(Area(name=str(row['Name']), description=row.get('Description', '') or ''))
            db.session.commit()

        # 2. LINES
        elif entity_type == 'Lines':
            for _, row in df.iterrows():
                area = Area.query.filter_by(name=str(row.get('AreaName'))).first()
                if area and row.get('Name') and not Line.query.filter_by(name=str(row['Name']), area_id=area.id).first():
                    db.session.add(Line(name=str(row['Name']), description=row.get('Description', '') or '', area=area))
            db.session.commit()

        # 3. EQUIPMENTS
        elif entity_type == 'Equipments':
            for _, row in df.iterrows():
                area_name = row.get('AreaName')
                line_name = row.get('LineName')
                
                line_query = Line.query
                if area_name:
                    area = Area.query.filter_by(name=str(area_name)).first()
                    if area:
                        line_query = line_query.filter_by(area_id=area.id)
                    else:
                        continue
                
                line = line_query.filter_by(name=str(line_name)).first()
                if line and row.get('Name') and not Equipment.query.filter_by(name=str(row['Name']), line_id=line.id).first():
                    db.session.add(Equipment(name=str(row['Name']), tag=str(row.get('Tag')), description=row.get('Description', '') or '', line=line))
            db.session.commit()

        # 4. SYSTEMS
        elif entity_type == 'Systems':
            for _, row in df.iterrows():
                area_name = row.get('AreaName')
                line_name = row.get('LineName')
                equip_name = row.get('EquipmentName')
                
                equip_query = Equipment.query.join(Line).join(Area)
                if area_name: equip_query = equip_query.filter(Area.name == str(area_name))
                if line_name: equip_query = equip_query.filter(Line.name == str(line_name))
                
                equip = equip_query.filter(Equipment.name == str(equip_name)).first()
                
                if equip and row.get('Name') and not System.query.filter_by(name=str(row['Name']), equipment_id=equip.id).first():
                    db.session.add(System(name=str(row['Name']), equipment=equip))
            db.session.commit()

        # 5. COMPONENTS
        elif entity_type == 'Components':
            for _, row in df.iterrows():
                area_name = row.get('AreaName')
                line_name = row.get('LineName')
                equip_name = row.get('EquipmentName')
                sys_name = row.get('SystemName')
                
                sys_query = System.query.join(Equipment).join(Line).join(Area)
                if area_name: sys_query = sys_query.filter(Area.name == str(area_name))
                if line_name: sys_query = sys_query.filter(Line.name == str(line_name))
                if equip_name: sys_query = sys_query.filter(Equipment.name == str(equip_name))
                
                system = sys_query.filter(System.name == str(sys_name)).first()
                
                if system and row.get('Name') and not Component.query.filter_by(name=str(row['Name']), system_id=system.id).first():
                    db.session.add(Component(name=str(row['Name']), description=row.get('Description', '') or '', system=system))
            db.session.commit()

        # 6. SPARE PARTS
        elif entity_type == 'SpareParts':
            for _, row in df.iterrows():
                area_name = row.get('AreaName')
                line_name = row.get('LineName')
                equip_name = row.get('EquipmentName')
                sys_name = row.get('SystemName')
                comp_name = row.get('ComponentName')
                
                comp_query = Component.query.join(System).join(Equipment).join(Line).join(Area)
                if area_name: comp_query = comp_query.filter(Area.name == str(area_name))
                if line_name: comp_query = comp_query.filter(Line.name == str(line_name))
                if equip_name: comp_query = comp_query.filter(Equipment.name == str(equip_name))
                if sys_name: comp_query = comp_query.filter(System.name == str(sys_name))
                
                comp = comp_query.filter(Component.name == str(comp_name)).first()
                
                if comp and row.get('Name'):
                    db.session.add(SparePart(
                        name=str(row['Name']), 
                        code=str(row.get('Code', '') or ''), 
                        brand=str(row.get('Brand', '') or ''), 
                        quantity=int(row.get('Quantity', 0) or 0),
                        component=comp
                    ))
            db.session.commit()
        else:
            return jsonify({"error": "Invalid Entity Type"}), 400

        return jsonify({"message": f"Bulk Paste for {entity_type} Successful"}), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Bulk Paste Failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/bulk-paste-hierarchy', methods=['POST'])
def bulk_paste_hierarchy():
    try:
        data = request.json
        raw_data = data.get('raw_data')

        if not raw_data:
            return jsonify({"error": "Faltan datos (raw_data)"}), 400

        from io import StringIO
        # Parse TSV assuming columns:
        # Area, Line, Equipment, System, Component, [SparePart], [Code], [Brand], [Qty]
        # Or just mapped by index if simpler, but let's assume standard 6-level columns
        # Flexible approach: Read text, assume columns in order of hierarchy
        
        lines = raw_data.strip().split('\n')
        if not lines:
             return jsonify({"error": "No hay datos"}), 400
             
        # Detect clear valid lines
        processed_count = 0
        
        for line in lines:
            line = line.strip()
            if not line: continue
            
            parts = [p.strip() for p in line.split('\t')]
            # Expected order: Area, Line, Equip, System, Comp, Spare, [Code, Brand, Qty]
            # Minimum needs to be at least Area to be valid, but for hierarchy usually up to whatever level defined.
            # User said "copiar de un excel los 5 niveles" -> actually 6 with SparePart
            
            # Safe get helpers
            def get_val(idx): return parts[idx] if idx < len(parts) and parts[idx] else None
            
            area_name = get_val(0)
            line_name = get_val(1)
            equip_name = get_val(2)
            sys_name = get_val(3)
            comp_name = get_val(4)
            spare_name = get_val(5)
            
            # Optional Spare details
            spare_code = get_val(6) or ''
            spare_brand = get_val(7) or ''
            try:
                spare_qty = int(get_val(8)) if get_val(8) else 0
            except:
                spare_qty = 0

            # 1. Area
            if not area_name: continue
            area = Area.query.filter_by(name=area_name).first()
            if not area:
                area = Area(name=area_name)
                db.session.add(area)
                db.session.flush() # get ID
            
            # 2. Line
            if not line_name: continue
            line_obj = Line.query.filter_by(name=line_name, area_id=area.id).first()
            if not line_obj:
                line_obj = Line(name=line_name, area=area)
                db.session.add(line_obj)
                db.session.flush()
                
            # 3. Equipment
            if not equip_name: continue
            equip = Equipment.query.filter_by(name=equip_name, line_id=line_obj.id).first()
            if not equip:
                equip = Equipment(name=equip_name, tag=f"{equip_name[:3].upper()}-{line_name[:3].upper()}", line=line_obj) # Auto-tag if not provided
                db.session.add(equip)
                db.session.flush()
            
            # 4. System
            if not sys_name: continue
            system = System.query.filter_by(name=sys_name, equipment_id=equip.id).first()
            if not system:
                system = System(name=sys_name, equipment=equip)
                db.session.add(system)
                db.session.flush()
            
            # 5. Component
            if not comp_name: continue
            comp = Component.query.filter_by(name=comp_name, system_id=system.id).first()
            if not comp:
                comp = Component(name=comp_name, system=system)
                db.session.add(comp)
                db.session.flush()
                
            # 6. Spare Part
            if spare_name:
                spare = SparePart.query.filter_by(name=spare_name, component_id=comp.id).first()
                if not spare:
                    spare = SparePart(name=spare_name, code=spare_code, brand=spare_brand, quantity=spare_qty, component=comp)
                    db.session.add(spare)
            
            processed_count += 1

        db.session.commit()
        return jsonify({"message": f"Procesadas {processed_count} filas de jerarquía."}), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Hierarchy Paste Failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/export-data', methods=['GET'])
def export_data():
    try:
        # Fetch all data flattened
        # Area -> Line -> Equip -> System -> Comp -> Spare
        # We need to construct a list of dicts
        
        data = []
        
        # Start from top or bottom? Top is easier to iterate if relationships are right
        areas = Area.query.all()
        for a in areas:
            lines = Line.query.filter_by(area_id=a.id).all() or [None]
            for l in lines:
                equips = (Equipment.query.filter_by(line_id=l.id).all() if l else []) or [None]
                for e in equips:
                    systems = (System.query.filter_by(equipment_id=e.id).all() if e else []) or [None]
                    for s in systems:
                        comps = (Component.query.filter_by(system_id=s.id).all() if s else []) or [None]
                        for c in comps:
                            spares = (SparePart.query.filter_by(component_id=c.id).all() if c else []) or [None]
                            for sp in spares:
                                row = {
                                    'Area': a.name,
                                    'Description (Area)': a.description,
                                    'Line': l.name if l else '',
                                    'Equipment': e.name if e else '',
                                    'Tag': e.tag if e else '',
                                    'System': s.name if s else '',
                                    'Component': c.name if c else '',
                                    'SparePart': sp.name if sp else '',
                                    'SpareCode': sp.code if sp else '',
                                    'SpareBrand': sp.brand if sp else '',
                                    'SpareQty': sp.quantity if sp else ''
                                }
                                data.append(row)
        
        df = pd.DataFrame(data)
        
        # Buffer
        from io import BytesIO
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='BaseDatos_Completa')
            
        output.seek(0)
        
        from flask import send_file
        return send_file(output, download_name="CMMS_BaseDatos_Completa.xlsx", as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    except Exception as e:
        logger.error(f"Export Failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/download-template', methods=['GET'])
def download_template():
    try:
        # Define structure
        structure = {
            'Areas': ['Name', 'Description'],
            'Lines': ['Name', 'Description', 'AreaName'],
            'Equipments': ['Name', 'Tag', 'Description', 'LineName', 'AreaName'],
            'Systems': ['Name', 'EquipmentName', 'LineName', 'AreaName'],
            'Components': ['Name', 'Description', 'SystemName', 'EquipmentName', 'LineName', 'AreaName'],
            'SpareParts': ['Name', 'Code', 'Brand', 'Quantity', 'ComponentName', 'SystemName', 'EquipmentName', 'LineName', 'AreaName']
        }
        
        # Create Excel in memory
        from io import BytesIO
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for sheet, columns in structure.items():
                pd.DataFrame(columns=columns).to_excel(writer, sheet_name=sheet, index=False)
        
        output.seek(0)
        
        from flask import send_file
        return send_file(output, download_name="plantilla_carga_masiva_cmms.xlsx", as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        
    except Exception as e:
        logger.error(f"Template Download Failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/predictive/ot-suggestions', methods=['GET'])
def get_ot_suggestions():
    try:
        # Extract query params
        m_type = request.args.get('maintenance_type')
        comp_id = request.args.get('component_id')
        sys_id = request.args.get('system_id')
        equip_id = request.args.get('equipment_id')
        
        # Build query
        query = WorkOrder.query.filter_by(status='Cerrada')
        
        if m_type:
            query = query.filter_by(maintenance_type=m_type)
            
        # Hierarchy filtering - prioritize most specific
        if comp_id:
            query = query.filter_by(component_id=comp_id)
        elif sys_id:
            query = query.filter_by(system_id=sys_id)
        elif equip_id:
            query = query.filter_by(equipment_id=equip_id)
        else:
            return jsonify({"found": False, "message": "No asset specified"}), 200
            
        # Get most recent
        last_ot = query.order_by(WorkOrder.id.desc()).first()
        
        if not last_ot:
            return jsonify({"found": False, "message": "No history found"}), 200
            
        # Gather materials
        tools = []
        parts = []
        
        for m in last_ot.assigned_materials:
            item_name = "Unknown"
            code = ""
            if m.item_type == 'tool':
                t = Tool.query.get(m.item_id)
                if t: 
                    item_name = t.name
                    code = t.code
                tools.append({
                    "item_id": m.item_id, 
                    "item_type": "tool", 
                    "quantity": m.quantity, 
                    "name": item_name,
                    "code": code
                })
            else:
                w = WarehouseItem.query.get(m.item_id)
                if w: 
                    item_name = w.name
                    code = w.code
                parts.append({
                    "item_id": m.item_id, 
                    "item_type": "warehouse", 
                    "quantity": m.quantity, 
                    "name": item_name,
                    "code": code
                })
        
        return jsonify({
            "found": True,
            "tools": tools,
            "parts": parts,
            "source_ot": last_ot.code
        }), 200
        
    except Exception as e:
        logger.error(f"Suggestion Error: {e}")
        return jsonify({"error": str(e)}), 500



@app.route('/api/work-orders/feedback', methods=['GET'])
def get_work_order_feedback():
    try:
        equip_id = request.args.get('equipment_id')
        if not equip_id:
            return jsonify([])
        
        # Get last 5 closed OTs for this equipment with comments
        ots = WorkOrder.query.filter(
            WorkOrder.equipment_id == equip_id,
            WorkOrder.status == 'Cerrada',
            WorkOrder.execution_comments != None,
            WorkOrder.execution_comments != ''
        ).order_by(WorkOrder.real_end_date.desc()).limit(5).all()
        
        results = []
        for ot in ots:
            tech_name = "Desconocido"
            if ot.technician_id:
                # heuristic: if numeric, find in DB, else use string
                if ot.technician_id.isdigit():
                    t = Technician.query.get(int(ot.technician_id))
                    if t: tech_name = t.name
            
            results.append({
                "date": ot.real_end_date or ot.real_start_date or 'N/A',
                "maintenance_type": ot.maintenance_type,
                "comments": ot.execution_comments,
                "tech_name": tech_name,
                "ot_code": ot.code or f"OT-{ot.id}"
            })
            
        return jsonify(results)
    except Exception as e:
        logger.error(f"Error fetching feedback: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/reports/kpis', methods=['GET'])
def get_kpi_reports():
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        area_id = request.args.get('area_id')
        line_id = request.args.get('line_id')
        
        # Determine Level and Groups
        level = "area"
        groups = [] # {id, name, children_ids}
        
        if line_id:
            level = "equipment"
            parent = Line.query.get(line_id)
            if not parent: return jsonify({"error": "Line not found"}), 404
            
            equips = Equipment.query.filter_by(line_id=line_id).all()
            for e in equips:
                groups.append({"id": e.id, "name": e.name, "object": e})
                
        elif area_id:
            level = "line"
            parent = Area.query.get(area_id)
            if not parent: return jsonify({"error": "Area not found"}), 404
            
            lines = Line.query.filter_by(area_id=area_id).all()
            for l in lines:
                groups.append({"id": l.id, "name": l.name, "object": l})
                
        else:
            level = "area"
            areas = Area.query.all()
            for a in areas:
                groups.append({"id": a.id, "name": a.name, "object": a})

        # Calculate KPIs for each group
        results = []
        
        # Helper to get all OTs for a hierarchy node
        def get_ots_for_node(node, level):
            # Traverse down to find IDs
            equip_ids = []
            
            if level == 'equipment':
                equip_ids = [node.id]
            elif level == 'line':
                equip_ids = [e.id for e in Equipment.query.filter_by(line_id=node.id).all()]
            elif level == 'area':
                lines = Line.query.filter_by(area_id=node.id).all()
                for l in lines:
                    equip_ids.extend([e.id for e in Equipment.query.filter_by(line_id=l.id).all()])
            
            if not equip_ids: return []

            # Find OTs linked to these equipments (or their components/systems)
            # Simplest approach: Query OTs directly linked to Equipment OR System OR Component that belongs to these equipments
            # But DB model links OT directly to Equipment/System/Component.
            # We need to aggregating.
            
            # Let's trust the OT's direct links for now. 
            # Ideally, we should join tables. But iterative python filtering is safer for now if dataset is small.
            
            # Optimized: Query OTs where equipment_id IN list OR system.equipment_id IN list OR component.system.equipment_id IN list
            # This is complex in ORM without joins.
            # Let's fetch all closed OTs and filter in python (Performance caveat: Bad for large DB, okay for prototype)
            
            all_ots = WorkOrder.query.filter_by(status='Cerrada').all()
            relevant_ots = []
            
            for ot in all_ots:
                # Check date range
                if start_date and ot.real_end_date and ot.real_end_date < start_date: continue
                if end_date and ot.real_end_date and ot.real_end_date > end_date: continue
                
                # Check hierarchy
                e_id = -1
                if ot.equipment_id: e_id = ot.equipment_id
                elif ot.system_id: 
                    s = System.query.get(ot.system_id)
                    if s: e_id = s.equipment_id
                elif ot.component_id:
                    c = Component.query.get(ot.component_id)
                    if c: 
                        s = System.query.get(c.system_id)
                        if s: e_id = s.equipment_id
                
                if e_id in equip_ids:
                    relevant_ots.append(ot)
                    
            return relevant_ots

        for g in groups:
            ots = get_ots_for_node(g['object'], level)
            
            # 1. Cost Calculation
            total_cost = 0
            for ot in ots:
                for m in ot.assigned_materials:
                    if m.item_type == 'warehouse':
                        item = WarehouseItem.query.get(m.item_id)
                        cost = (item.unit_cost or 0) * m.quantity
                        total_cost += cost
            
            # 2. Reliability Calculation
            failures = [ot for ot in ots if ot.maintenance_type == 'Correctivo']
            n_failures = len(failures)
            t_down = sum([(ot.real_duration or 0) for ot in failures])
            
            # Total Time window (hours)
            # Approximate if dates not set: 30 days
            t_total = 720 
            if start_date and end_date:
                try:
                    d1 = datetime.datetime.fromisoformat(start_date)
                    d2 = datetime.datetime.fromisoformat(end_date)
                    t_total = (d2 - d1).total_seconds() / 3600
                except: pass
            
            t_up = t_total - t_down
            if t_up < 0: t_up = 0 # Edge case
            
            mtbf = t_up / n_failures if n_failures > 0 else t_up # If 0 failures, MTBF is full period
            mttr = t_down / n_failures if n_failures > 0 else 0
            availability = (mtbf / (mtbf + mttr)) * 100 if (mtbf + mttr) > 0 else 100
            
            results.append({
                "id": g['id'],
                "name": g['name'],
                "cost": round(total_cost, 2),
                "failures": n_failures,
                "mtbf": round(mtbf, 1),
                "mttr": round(mttr, 1),
                "availability": round(availability, 2),
                "ot_count": len(ots)
            })
            
        return jsonify({
            "level": level,
            "groups": results
        })
        
    except Exception as e:
        logger.error(f"KPI Report Error: {e}")
        # traceback.print_exc()
        return jsonify({"error": str(e)}), 500



# --- PURCHASING MODELS MOVED TO models.py ---

# --- PURCHASING API ---
@app.route('/api/purchase-requests', methods=['GET', 'POST'])
def handle_requests():
    if request.method == 'POST':
        try:
            data = request.json
            count = PurchaseRequest.query.count()
            req_code = f"REQ-2026-{count+1:04d}"
            
            if data['item_type'] == 'SERVICIO' and not data.get('description'):
                 return jsonify({"error": "Descripción obligatoria para Servicios"}), 400
            
            if data['item_type'] == 'MATERIAL' and not data.get('spare_part_id') and not data.get('warehouse_item_id'):
                 return jsonify({"error": "Debe seleccionar un item del almacén."}), 400

            req = PurchaseRequest(
                req_code=req_code,
                work_order_id=data['work_order_id'],
                item_type=data['item_type'],
                spare_part_id=data.get('spare_part_id'),
                warehouse_item_id=data.get('warehouse_item_id'),
                description=data.get('description'),
                quantity=data['quantity']
            )
            db.session.add(req)
            db.session.commit()
            return jsonify(req.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    show_all = request.args.get('all', 'false') == 'true'
    if show_all:
        reqs = PurchaseRequest.query.order_by(PurchaseRequest.id.desc()).all()
    else:
        reqs = PurchaseRequest.query.filter(PurchaseRequest.status != 'RECIBIDO').order_by(PurchaseRequest.id.desc()).all()
        
    return jsonify([r.to_dict() for r in reqs])

@app.route('/api/purchase-orders', methods=['GET', 'POST'])
def handle_orders():
    if request.method == 'POST':
        try:
            data = request.json
            provider = data.get('provider_name')
            req_ids = data.get('request_ids', [])
            
            if not req_ids:
                return jsonify({"error": "No requests selected"}), 400
            
            count = PurchaseOrder.query.count()
            po_code = f"OC-2026-{count+1:03d}"
            
            po = PurchaseOrder(
                po_code=po_code,
                provider_name=provider,
                status='EMITIDA'
            )
            db.session.add(po)
            db.session.flush() 
            
            for rid in req_ids:
                req = PurchaseRequest.query.get(rid)
                if req:
                    req.purchase_order_id = po.id
                    req.status = 'EN_ORDEN'
            
            db.session.commit()
            return jsonify(po.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    orders = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).all()
    return jsonify([o.to_dict() for o in orders])

@app.route('/api/purchase-orders/<int:id>/close', methods=['POST'])
def close_po(id):
    try:
        po = PurchaseOrder.query.get_or_404(id)
        po.status = 'CERRADA'
        for req in po.requests:
            req.status = 'RECIBIDO'
        db.session.commit()
        return jsonify(po.to_dict())
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/dashboard-stats', methods=['GET'])
def get_dashboard_stats():
    try:
        # KPIs
        open_ots_count = WorkOrder.query.filter(WorkOrder.status != 'Cerrada').count()
        # For notices we count everything not closed
        pending_notices_count = MaintenanceNotice.query.filter(MaintenanceNotice.status != 'Cerrado').count()
        closed_ots_count = WorkOrder.query.filter_by(status='Cerrada').count()
        active_techs_count = Technician.query.filter_by(is_active=True).count()

        # Chart: Status
        status_counts = db.session.query(WorkOrder.status, func.count(WorkOrder.id)).group_by(WorkOrder.status).all()
        status_dict = {s: c for s, c in status_counts}

        # Chart: Types
        type_counts = db.session.query(WorkOrder.maintenance_type, func.count(WorkOrder.id)).group_by(WorkOrder.maintenance_type).all()
        type_dict = {t: c for t, c in type_counts}

        # Chart: Failure Modes (Top 5)
        fail_counts = db.session.query(WorkOrder.failure_mode, func.count(WorkOrder.id))\
            .filter(WorkOrder.failure_mode != None, WorkOrder.failure_mode != '')\
            .group_by(WorkOrder.failure_mode)\
            .order_by(func.count(WorkOrder.id).desc())\
            .limit(5).all()
        
        failures_list = [{"mode": f, "count": c} for f, c in fail_counts]

        # Recent Activity (Last 5 OTs)
        recent_ots = WorkOrder.query.order_by(WorkOrder.id.desc()).limit(5).all()
        recent_list = []
        for ot in recent_ots:
            date_display = '-'
            if ot.created_at: 
                date_display = ot.created_at.strftime('%Y-%m-%d')
            elif ot.scheduled_date:
                date_display = ot.scheduled_date.strftime('%Y-%m-%d')

            recent_list.append({
                "code": ot.code or f"OT-{ot.id}",
                "date": date_display,
                "description": ot.description,
                "status": ot.status
            })

        return jsonify({
            "kpi": {
                "open_ots": open_ots_count,
                "pending_notices": pending_notices_count,
                "closed_ots": closed_ots_count,
                "active_techs": active_techs_count
            },
            "charts": {
                "status": status_dict,
                "types": type_dict,
                "failures": failures_list
            },
            "recent": recent_list
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/list-spare-parts', methods=['GET'])
def list_warehouse_items_for_purchasing():
    try:
        # Return WarehouseItems instead of SpareParts as user migrated to Warehouse Module
        items = WarehouseItem.query.filter_by(is_active=True).all()
        return jsonify([{
            'id': i.id,
            'name': i.name,
            'code': i.code,
            'stock': i.stock,
            'brand': i.brand
        } for i in items])
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':

    with app.app_context():
        db.create_all()
        logger.info("Database ready")
    app.run(host='0.0.0.0', debug=True, use_reloader=False, port=5006)
    