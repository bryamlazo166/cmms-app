from datetime import datetime
from io import BytesIO

import pandas as pd
from flask import jsonify, request, send_file
from flask_login import login_required

from utils.rate_limit import limit_export


# Whitelist explicita de campos editables via API.
# Excluye id, code (autogenerado), y cualquier futura columna interna.
# Si se agrega un campo nuevo al modelo y debe ser editable, hay que
# agregarlo aqui de forma explicita.
_WAREHOUSE_EDITABLE_FIELDS = frozenset({
    'name', 'category', 'description', 'stock', 'min_stock', 'unit',
    'location', 'unit_cost', 'family', 'brand', 'manufacturer_code',
    'criticality', 'average_cost', 'lead_time', 'abc_class', 'xyz_class',
    'safety_stock', 'rop', 'max_stock', 'min_order_qty', 'is_active',
})


def register_warehouse_routes(
    app, db, logger, WarehouseItem, WarehouseMovement,
    RotativeAsset=None, RotativeAssetBOM=None, Equipment=None,
):
    # --- WAREHOUSE ENDPOINTS ---
    @app.route('/api/warehouse', methods=['GET', 'POST'])
    @login_required
    def handle_warehouse():
        if request.method == 'POST':
            try:
                data = request.json or {}
                # Whitelist: ignorar cualquier campo no editable que envie el cliente
                clean_data = {
                    k: v for k, v in data.items() if k in _WAREHOUSE_EDITABLE_FIELDS
                }

                item = WarehouseItem(code='REP-TEMP', **clean_data)
                db.session.add(item)
                db.session.flush()
                item.code = f"REP-{item.id:04d}"
                db.session.commit()
                return jsonify(item.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.exception("Warehouse create failed")
                return jsonify({"error": "No se pudo crear el item de almacen."}), 500

        # GET
        show_all = request.args.get('all')
        query = WarehouseItem.query
        if not show_all:
            query = query.filter_by(is_active=True)

        items = query.all()
        return jsonify([i.to_dict() for i in items])

    @app.route('/api/warehouse/<int:id>', methods=['PUT', 'DELETE'])
    @login_required
    def handle_warehouse_id(id):
        try:
            item = WarehouseItem.query.get(id)
            if not item:
                return jsonify({"error": "Item not found"}), 404

            if request.method == 'DELETE':
                item.is_active = not item.is_active  # Toggle
                db.session.commit()
                return jsonify({"message": "Status toggled"}), 200

            if request.method == 'PUT':
                data = request.json or {}
                # Whitelist explicita: bloquea mass assignment de id, code u
                # otros campos sensibles que el cliente intente sobrescribir.
                for k, v in data.items():
                    if k in _WAREHOUSE_EDITABLE_FIELDS:
                        setattr(item, k, v)
                db.session.commit()
                return jsonify(item.to_dict()), 200
        except Exception as e:
            db.session.rollback()
            logger.exception(f"Warehouse update/delete failed for id={id}")
            return jsonify({"error": "No se pudo actualizar el item de almacen."}), 500

    @app.route('/api/warehouse/export', methods=['GET'])
    @login_required
    @limit_export
    def export_warehouse_excel():
        try:
            items = WarehouseItem.query.all()
            data = []

            for i in items:
                data.append(
                    {
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
                        'Activo': 'Sí' if i.is_active else 'No',
                    }
                )

            df = pd.DataFrame(data)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Inventario')

            output.seek(0)

            return send_file(
                output,
                download_name="Inventario_Maestro_CMMS.xlsx",
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

        except Exception as e:
            logger.error(f"Warehouse Export Failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/warehouse/export-kardex', methods=['GET'])
    @login_required
    @limit_export
    def export_kardex_excel():
        try:
            movements = WarehouseMovement.query.order_by(WarehouseMovement.date.desc()).all()
            data = []

            for m in movements:
                item_code = m.item.code if m.item else 'Unknown'
                item_name = m.item.name if m.item else 'Unknown'

                data.append(
                    {
                        'Fecha': m.date,
                        'Tipo': m.movement_type,
                        'Item': f"{item_code} - {item_name}",
                        'Cantidad': m.quantity,
                        'Razón': m.reason,
                        'Referencia': m.reference_id,
                    }
                )

            df = pd.DataFrame(data)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Kardex')

            output.seek(0)

            return send_file(
                output,
                download_name="Kardex_CMMS.xlsx",
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

        except Exception as e:
            logger.error(f"Kardex Export Failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/warehouse/template', methods=['GET'])
    @login_required
    def download_warehouse_template():
        try:
            template_rows = [
                {
                    'Codigo': 'REP-1001',
                    'Nombre': 'RODAMIENTO 6205 ZZ',
                    'Categoria': 'Repuesto',
                    'Descripcion': 'Rodamiento de uso general',
                    'Stock': 10,
                    'StockMinimo': 2,
                    'Unidad': 'pza',
                    'Ubicacion': 'Estante A-2',
                    'CostoUnitario': 12.5,
                    'Familia': 'Rodamientos',
                    'Marca': 'SKF',
                    'CodigoFabricante': '6205ZZ',
                    'Criticidad': 'Media',
                    'CostoPromedio': 12.2,
                    'LeadTimeDias': 7,
                    'StockSeguridad': 2,
                    'ROP': 4,
                    'StockMaximo': 20,
                    'LoteMinimo': 1,
                },
                {
                    'Codigo': '',
                    'Nombre': 'GRASA EP2',
                    'Categoria': 'Lubricante',
                    'Descripcion': 'Cartucho 400g',
                    'Stock': 15,
                    'StockMinimo': 5,
                    'Unidad': 'und',
                    'Ubicacion': 'Estante L-1',
                    'CostoUnitario': 8.0,
                    'Familia': 'Lubricantes',
                    'Marca': 'Mobil',
                    'CodigoFabricante': '',
                    'Criticidad': 'Alta',
                    'CostoPromedio': 7.8,
                    'LeadTimeDias': 5,
                    'StockSeguridad': 3,
                    'ROP': 6,
                    'StockMaximo': 30,
                    'LoteMinimo': 1,
                },
            ]

            df = pd.DataFrame(template_rows)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Plantilla_Almacen')
            output.seek(0)

            return send_file(
                output,
                download_name='Plantilla_Almacen_CMMS.xlsx',
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            logger.error(f"Warehouse Template Failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/warehouse/import', methods=['POST'])
    def import_warehouse_excel():
        try:
            if 'file' not in request.files:
                return jsonify({'error': 'Archivo no recibido'}), 400

            file = request.files['file']
            if not file or not file.filename:
                return jsonify({'error': 'Archivo invalido'}), 400

            df = pd.read_excel(file)
            df.columns = [str(c).strip() for c in df.columns]

            if 'Nombre' not in set(df.columns):
                return jsonify({'error': 'La plantilla debe contener al menos la columna Nombre'}), 400

            existing_items = WarehouseItem.query.all()
            existing_by_code = {str(i.code).strip().upper(): i for i in existing_items if i.code}
            existing_key = {
                (
                    str(i.name or '').strip().upper(),
                    str(i.family or '').strip().upper(),
                    str(i.brand or '').strip().upper(),
                    str(i.manufacturer_code or '').strip().upper(),
                ): i
                for i in existing_items
            }

            inserted = 0
            skipped = 0
            notes = []
            seen_codes = set()
            seen_keys = set()

            def norm_text(v):
                if pd.isna(v):
                    return None
                txt = str(v).strip()
                return txt if txt else None

            def norm_int(v, default=0):
                if pd.isna(v) or v is None or str(v).strip() == '':
                    return default
                try:
                    return int(float(v))
                except Exception:
                    return default

            def norm_float(v, default=None):
                if pd.isna(v) or v is None or str(v).strip() == '':
                    return default
                try:
                    return float(v)
                except Exception:
                    return default

            last = WarehouseItem.query.order_by(WarehouseItem.id.desc()).first()
            next_id = (last.id if last else 0) + 1

            for idx, row in df.iterrows():
                row_number = idx + 2
                name = norm_text(row.get('Nombre'))
                if not name:
                    skipped += 1
                    notes.append(f'Fila {row_number}: sin nombre, omitida')
                    continue

                code = norm_text(row.get('Codigo'))
                category = norm_text(row.get('Categoria'))
                description = norm_text(row.get('Descripcion'))
                stock = norm_int(row.get('Stock'), 0)
                min_stock = norm_int(row.get('StockMinimo'), 0)
                unit = norm_text(row.get('Unidad')) or 'pza'
                location = norm_text(row.get('Ubicacion'))
                unit_cost = norm_float(row.get('CostoUnitario'), None)
                family = norm_text(row.get('Familia'))
                brand = norm_text(row.get('Marca'))
                manufacturer_code = norm_text(row.get('CodigoFabricante'))
                criticality = norm_text(row.get('Criticidad')) or 'Media'
                average_cost = norm_float(row.get('CostoPromedio'), None)
                lead_time = norm_int(row.get('LeadTimeDias'), 0)
                safety_stock = norm_int(row.get('StockSeguridad'), 0)
                rop = norm_int(row.get('ROP'), 0)
                max_stock = norm_int(row.get('StockMaximo'), 0)
                min_order_qty = norm_int(row.get('LoteMinimo'), 1)

                code_norm = code.upper() if code else None
                key = (
                    name.upper(),
                    (family or '').upper(),
                    (brand or '').upper(),
                    (manufacturer_code or '').upper(),
                )

                if code_norm:
                    if code_norm in seen_codes or code_norm in existing_by_code:
                        skipped += 1
                        continue
                if key in seen_keys or key in existing_key:
                    skipped += 1
                    continue

                if not code_norm:
                    code_norm = f"REP-{next_id:04d}"
                    while code_norm in existing_by_code or code_norm in seen_codes:
                        next_id += 1
                        code_norm = f"REP-{next_id:04d}"

                item = WarehouseItem(
                    code=code_norm,
                    name=name,
                    category=category,
                    description=description,
                    stock=stock,
                    min_stock=min_stock,
                    unit=unit,
                    location=location,
                    unit_cost=unit_cost,
                    family=family,
                    brand=brand,
                    manufacturer_code=manufacturer_code,
                    criticality=criticality,
                    average_cost=average_cost,
                    lead_time=lead_time,
                    safety_stock=safety_stock,
                    rop=rop,
                    max_stock=max_stock,
                    min_order_qty=min_order_qty,
                    is_active=True,
                )
                db.session.add(item)
                inserted += 1
                seen_codes.add(code_norm)
                seen_keys.add(key)
                next_id += 1

            db.session.commit()
            return jsonify(
                {
                    'inserted': inserted,
                    'skipped_duplicates': skipped,
                    'notes': notes[:30],
                }
            )
        except Exception as e:
            db.session.rollback()
            logger.error(f"Warehouse Import Failed: {e}")
            return jsonify({'error': str(e)}), 500
    @app.route('/api/warehouse/calculate', methods=['POST'])
    def calculate_inventory_params():
        """
        Recalculate ABC/XYZ and ROP for all items provided (or all active).
        ABC: Based on Usage Value (Qty * Cost).
        XYZ: Based on Coefficient of Variation.
        ROP: (AvgDailyUsage * LeadTime) + SafetyStock.
        """
        try:
            import numpy as np

            # 1. Fetch Data
            items = WarehouseItem.query.filter_by(is_active=True).all()
            movements = WarehouseMovement.query.filter(WarehouseMovement.movement_type.in_(['OUT', 'ADJUST'])).all()

            # Create DF
            mov_data = []
            for m in movements:
                mov_data.append(
                    {
                        'item_id': m.item_id,
                        'qty': abs(m.quantity),
                        'date': m.date[:10],  # YYYY-MM-DD
                    }
                )

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
                    if pd.isna(cv) or cv < 0.2:
                        xyz = 'X'
                    elif cv < 0.5:
                        xyz = 'Y'
                    else:
                        xyz = 'Z'
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
                if pct <= 0.80:
                    abc = 'A'
                elif pct <= 0.95:
                    abc = 'B'
                else:
                    abc = 'C'

                # XYZ Logic
                xyz = xyz_map.get(item.id, 'Z')  # Default Z if no history

                # ROP Calculation
                # 1. Avg Daily Usage
                avg_daily = qty / 365.0
                lead_time = item.lead_time or 0

                # Safety Stock (Simple Formula if 0)
                # SS = Z * Sigma * sqrt(L). Assuming simplified: 50% of Lead Time Demand if not set?
                # Let's keep existing SS if set, else suggest
                ss = item.safety_stock
                if ss == 0 and avg_daily > 0:
                    ss = int(avg_daily * lead_time * 0.5)  # Fallback heuristic

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
                date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                reason=reason,
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

    # ── BOM POR EQUIPO ─────────────────────────────────────────────────────
    # Cruza WarehouseItem ↔ RotativeAssetBOM ↔ RotativeAsset.equipment_id.
    # Permite ver, por cada item de almacen: en que equipos se usa, cuanto
    # stock total se necesita y si hay cobertura.
    if RotativeAsset is not None and RotativeAssetBOM is not None and Equipment is not None:

        @app.route('/api/warehouse/bom-by-equipment', methods=['GET'])
        def warehouse_bom_by_equipment():
            """Por cada item de almacen, lista los equipos que lo consumen
            (via activos rotativos) y la cantidad total esperada vs stock actual.
            """
            try:
                # Map equipment_id -> {tag, name}
                equip_map = {e.id: e for e in Equipment.query.all()}
                # Map asset_id -> equipment_id
                asset_to_eq = {
                    a.id: a.equipment_id for a in RotativeAsset.query.all()
                    if a.equipment_id is not None
                }
                # Agrupar BOM por warehouse_item_id
                grouped = {}  # item_id -> {'qty_total': float, 'equipments': {eq_id: qty}}
                for bom in RotativeAssetBOM.query.all():
                    if not bom.warehouse_item_id:
                        continue
                    eq_id = asset_to_eq.get(bom.asset_id)
                    if not eq_id:
                        continue
                    g = grouped.setdefault(bom.warehouse_item_id, {
                        'qty_total': 0.0, 'equipments': {}, 'asset_count': 0,
                    })
                    qty = float(bom.quantity or 0)
                    g['qty_total'] += qty
                    g['equipments'][eq_id] = g['equipments'].get(eq_id, 0.0) + qty
                    g['asset_count'] += 1

                # Construir respuesta
                rows = []
                for item in WarehouseItem.query.filter_by(is_active=True).all():
                    g = grouped.get(item.id)
                    if not g:
                        continue  # solo items vinculados a algun equipo
                    eq_breakdown = []
                    for eq_id, qty in sorted(g['equipments'].items(),
                                             key=lambda kv: -kv[1]):
                        eq = equip_map.get(eq_id)
                        if not eq:
                            continue
                        eq_breakdown.append({
                            'equipment_id': eq_id,
                            'tag': eq.tag,
                            'name': eq.name,
                            'qty_required': round(qty, 2),
                        })
                    qty_total = round(g['qty_total'], 2)
                    stock = float(item.stock or 0)
                    coverage = (stock / qty_total * 100) if qty_total > 0 else None
                    rows.append({
                        'item_id': item.id,
                        'code': item.code,
                        'name': item.name,
                        'family': getattr(item, 'family', None),
                        'unit': getattr(item, 'unit', None),
                        'stock': stock,
                        'min_stock': float(getattr(item, 'min_stock', 0) or 0),
                        'rop': float(getattr(item, 'rop', 0) or 0),
                        'criticality': getattr(item, 'criticality', None),
                        'qty_required_total': qty_total,
                        'equipment_count': len(eq_breakdown),
                        'coverage_pct': round(coverage, 1) if coverage is not None else None,
                        'is_covered': stock >= qty_total if qty_total > 0 else True,
                        'equipments': eq_breakdown,
                    })
                # Sin cobertura primero
                rows.sort(key=lambda r: (
                    r['is_covered'],  # False antes que True
                    -(r['qty_required_total'] - r['stock']),
                ))
                return jsonify({
                    'rows': rows,
                    'total_items_with_bom': len(rows),
                    'total_uncovered': sum(1 for r in rows if not r['is_covered']),
                })
            except Exception as e:
                logger.exception('warehouse_bom_by_equipment error')
                return jsonify({"error": str(e)}), 500

        @app.route('/api/warehouse/equipment-coverage/<int:equipment_id>', methods=['GET'])
        def warehouse_equipment_coverage(equipment_id):
            """Para un equipo, lista los repuestos que necesita y su stock."""
            try:
                eq = Equipment.query.get(equipment_id)
                if not eq:
                    return jsonify({"error": "Equipo no encontrado"}), 404
                assets = RotativeAsset.query.filter_by(equipment_id=equipment_id).all()
                asset_ids = [a.id for a in assets]
                if not asset_ids:
                    return jsonify({
                        'equipment': {'id': eq.id, 'tag': eq.tag, 'name': eq.name},
                        'rows': [], 'total_uncovered': 0,
                    })
                # Agrupar por warehouse_item_id
                grouped = {}
                for bom in RotativeAssetBOM.query.filter(RotativeAssetBOM.asset_id.in_(asset_ids)).all():
                    if not bom.warehouse_item_id:
                        continue
                    grouped[bom.warehouse_item_id] = grouped.get(bom.warehouse_item_id, 0) + float(bom.quantity or 0)

                rows = []
                for item_id, qty_required in grouped.items():
                    item = WarehouseItem.query.get(item_id)
                    if not item:
                        continue
                    stock = float(item.stock or 0)
                    rows.append({
                        'item_id': item.id,
                        'code': item.code,
                        'name': item.name,
                        'family': getattr(item, 'family', None),
                        'unit': getattr(item, 'unit', None),
                        'stock': stock,
                        'qty_required': round(qty_required, 2),
                        'shortage': max(0, round(qty_required - stock, 2)),
                        'is_covered': stock >= qty_required,
                    })
                rows.sort(key=lambda r: (r['is_covered'], -r['shortage']))
                return jsonify({
                    'equipment': {'id': eq.id, 'tag': eq.tag, 'name': eq.name},
                    'rows': rows,
                    'total_uncovered': sum(1 for r in rows if not r['is_covered']),
                })
            except Exception as e:
                logger.exception('warehouse_equipment_coverage error')
                return jsonify({"error": str(e)}), 500

        @app.route('/api/warehouse/export-bom', methods=['GET'])
        @login_required
        @limit_export
        def export_bom_excel():
            """Lista maestra de repuestos necesarios por equipo, en Excel.

            Cruza las tres fuentes donde hoy viven los repuestos:
              - BOM de activos rotativos vinculado a almacen
              - BOM de activos rotativos SIN vincular (texto libre)
              - Repuestos de la taxonomia (equipo > sistema > componente)
              - Fichas tecnicas (specs) de activos rotativos: campos como
                "Rodamiento lado acople" son repuestos escritos como dato
            y le agrega el consumo real del kardex para contrastar lo que
            se planifica contra lo que de verdad se saca de almacen.

            Query params (todos opcionales):
              area_id       filtra a un area
              equipment_id  filtra a un equipo
              months        ventana de consumo del kardex (default 12)
            """
            try:
                from datetime import date as _date, timedelta as _timedelta

                from models import (Area, Line, System, Component, SparePart,
                                    RotativeAssetSpec)

                f_area = request.args.get('area_id', type=int)
                f_equip = request.args.get('equipment_id', type=int)
                months = request.args.get('months', default=12, type=int) or 12
                months = max(1, min(months, 60))

                areas_map = {a.id: a for a in Area.query.all()}
                lines_map = {ln.id: ln for ln in Line.query.all()}
                equip_map = {e.id: e for e in Equipment.query.all()}
                items_map = {i.id: i for i in WarehouseItem.query.all()}

                def _ubicacion(equipment_id, fallback_area_id=None, fallback_line_id=None):
                    """(area_id, area_nombre, linea_nombre, equipo_tag, equipo_nombre)."""
                    eq = equip_map.get(equipment_id) if equipment_id else None
                    if eq:
                        ln = lines_map.get(eq.line_id)
                        ar = areas_map.get(ln.area_id) if ln else None
                        return (ar.id if ar else None,
                                ar.name if ar else '-',
                                ln.name if ln else '-',
                                eq.tag or '', eq.name or '')
                    ln = lines_map.get(fallback_line_id) if fallback_line_id else None
                    ar = areas_map.get(fallback_area_id) if fallback_area_id else (
                        areas_map.get(ln.area_id) if ln else None)
                    return (ar.id if ar else None,
                            ar.name if ar else '(sin area)',
                            ln.name if ln else '(sin linea)',
                            '', '(sin equipo asignado)')

                # ── Activos rotativos que entran en el reporte ────────────
                assets = [a for a in RotativeAsset.query.all() if a.is_active]
                assets_ok = {}
                for a in assets:
                    ubic = _ubicacion(a.equipment_id, a.area_id, a.line_id)
                    if f_equip and a.equipment_id != f_equip:
                        continue
                    if f_area and ubic[0] != f_area:
                        continue
                    assets_ok[a.id] = (a, ubic)

                # ── Hoja 2: detalle por equipo ────────────────────────────
                detalle = []
                consolidado = {}   # item_id -> acumulado
                por_catalogar = []
                bom_por_activo = {}  # asset_id -> [texto de cada repuesto]

                for bom in RotativeAssetBOM.query.all():
                    par = assets_ok.get(bom.asset_id)
                    if not par:
                        continue
                    asset, (ar_id, ar_name, ln_name, eq_tag, eq_name) = par
                    item = items_map.get(bom.warehouse_item_id) if bom.warehouse_item_id else None
                    qty = float(bom.quantity or 0)
                    nombre = item.name if item else (bom.free_text or '(sin descripcion)')

                    bom_por_activo.setdefault(bom.asset_id, []).append(nombre.lower())

                    detalle.append({
                        'Area': ar_name,
                        'Linea': ln_name,
                        'Tag equipo': eq_tag,
                        'Equipo': eq_name,
                        'Codigo activo': asset.code,
                        'Activo rotativo': asset.name,
                        'Tipo de activo': asset.category or '',
                        'Especialidad': bom.category or '',
                        'Codigo almacen': item.code if item else '',
                        'Repuesto': nombre,
                        'Unidad': (item.unit if item else '') or '',
                        'Cantidad necesaria': qty,
                        'Stock actual': float(item.stock or 0) if item else None,
                        'Estado': 'Vinculado a almacen' if item else 'SIN CODIGO DE ALMACEN',
                        'Notas': bom.notes or '',
                    })

                    if item:
                        acc = consolidado.setdefault(item.id, {
                            'qty': 0.0, 'equipos': {}, 'activos': 0})
                        acc['qty'] += qty
                        acc['activos'] += 1
                        clave = f"{eq_tag} {eq_name}".strip() if eq_name else ar_name
                        acc['equipos'][clave] = acc['equipos'].get(clave, 0.0) + qty
                    else:
                        por_catalogar.append({
                            'Origen': 'Lista del activo rotativo',
                            'Area': ar_name,
                            'Linea': ln_name,
                            'Equipo': f"{eq_tag} {eq_name}".strip(),
                            'Activo / Componente': f"{asset.code} {asset.name}",
                            'Repuesto': nombre,
                            'Codigo propuesto': '',
                            'Marca': '',
                            'Cantidad': qty,
                            'Que hacer': 'Crear el repuesto en almacen y vincularlo al activo',
                        })

                # ── Repuestos de la taxonomia (equipo > sistema > componente)
                # No estan conectados a almacen: se listan para catalogarlos.
                items_por_nombre = {}
                items_por_codigo = {}
                for i in items_map.values():
                    items_por_nombre.setdefault((i.name or '').strip().lower(), i)
                    for c in ((i.code or ''), (i.manufacturer_code or '')):
                        if c:
                            items_por_codigo.setdefault(c.strip().lower(), i)

                try:
                    sistemas = {s.id: s for s in System.query.all()}
                    componentes = {c.id: c for c in Component.query.all()}
                    for sp in SparePart.query.all():
                        comp = componentes.get(sp.component_id)
                        sis = sistemas.get(comp.system_id) if comp else None
                        eq_id = sis.equipment_id if sis else None
                        ar_id, ar_name, ln_name, eq_tag, eq_name = _ubicacion(eq_id)
                        if f_equip and eq_id != f_equip:
                            continue
                        if f_area and ar_id != f_area:
                            continue
                        ya = (items_por_codigo.get((sp.code or '').strip().lower())
                              or items_por_nombre.get((sp.name or '').strip().lower()))
                        por_catalogar.append({
                            'Origen': 'Taxonomia (componente)',
                            'Area': ar_name,
                            'Linea': ln_name,
                            'Equipo': f"{eq_tag} {eq_name}".strip(),
                            'Activo / Componente': (
                                f"{sis.name if sis else ''} / {comp.name if comp else ''}".strip(' /')),
                            'Repuesto': sp.name,
                            'Codigo propuesto': sp.code or '',
                            'Marca': sp.brand or '',
                            'Cantidad': float(sp.quantity or 0),
                            'Que hacer': (f'Ya existe en almacen como {ya.code} — solo falta vincularlo'
                                          if ya else 'Crear el item en almacen'),
                        })
                except Exception:
                    logger.exception('export_bom: taxonomia omitida')

                # ── Hoja 4: repuestos escondidos en las fichas tecnicas ───
                CLAVES_REPUESTO = (
                    'rodamiento', 'reten', 'retén', 'sello', 'faja', 'correa',
                    'cadena', 'pinon', 'piñon', 'piñón', 'acople', 'filtro',
                    'empaque', 'kit', 'buje', 'chaveta', 'acoplamiento',
                    'acoplamiento', 'catalina', 'eslabon', 'eslabón', 'lubricante',
                )
                specs_rows = []
                try:
                    for sp in RotativeAssetSpec.query.all():
                        if not getattr(sp, 'is_active', True):
                            continue
                        clave = (sp.key_name or '').lower()
                        if not any(k in clave for k in CLAVES_REPUESTO):
                            continue
                        par = assets_ok.get(sp.asset_id)
                        if not par:
                            continue
                        asset, (ar_id, ar_name, ln_name, eq_tag, eq_name) = par
                        valor = (sp.value_text or '').strip()
                        if not valor:
                            continue
                        en_bom = any(valor.lower() in txt
                                     for txt in bom_por_activo.get(sp.asset_id, []))
                        specs_rows.append({
                            'Area': ar_name,
                            'Linea': ln_name,
                            'Equipo': f"{eq_tag} {eq_name}".strip(),
                            'Codigo activo': asset.code,
                            'Activo rotativo': asset.name,
                            'Campo de la ficha': sp.key_name,
                            'Valor (repuesto)': valor,
                            'Unidad': sp.unit or '',
                            'Ya esta en la lista del activo': 'Si' if en_bom else 'NO — falta agregarlo',
                        })
                except Exception:
                    logger.exception('export_bom: specs omitidas')

                # ── Hoja 5: consumo real del kardex ───────────────────────
                corte = (_date.today() - _timedelta(days=months * 30)).isoformat()
                consumo = {}   # item_id -> {'qty': x, 'salidas': n, 'ultima': str, 'ots': set}
                for m in WarehouseMovement.query.all():
                    if (m.movement_type or '').upper() != 'OUT':
                        continue
                    fecha = (m.date or '')[:10]
                    if fecha < corte:
                        continue
                    c = consumo.setdefault(m.item_id, {
                        'qty': 0.0, 'salidas': 0, 'ultima': '', 'ots': set()})
                    c['qty'] += abs(float(m.quantity or 0))
                    c['salidas'] += 1
                    if fecha > c['ultima']:
                        c['ultima'] = fecha
                    if m.reference_id:
                        c['ots'].add(m.reference_id)

                # ── Hoja 1: consolidado por repuesto ──────────────────────
                consol_rows = []
                for item_id, acc in consolidado.items():
                    item = items_map.get(item_id)
                    if not item:
                        continue
                    stock = float(item.stock or 0)
                    req = round(acc['qty'], 2)
                    faltante = round(max(0.0, req - stock), 2)
                    costo = float(item.average_cost or item.unit_cost or 0)
                    equipos_txt = ', '.join(
                        f"{k} (x{round(v, 2):g})"
                        for k, v in sorted(acc['equipos'].items(), key=lambda kv: -kv[1]))
                    c = consumo.get(item_id, {})
                    consol_rows.append({
                        'Codigo': item.code,
                        'Repuesto': item.name,
                        'Familia': item.family or '',
                        'Marca': item.brand or '',
                        'Unidad': item.unit or '',
                        'Criticidad': item.criticality or '',
                        'Clase ABC': item.abc_class or '',
                        'Stock actual': stock,
                        'Cantidad necesaria (todos los equipos)': req,
                        'Faltante': faltante,
                        'Cobertura %': round(stock / req * 100, 1) if req > 0 else None,
                        'Stock minimo': float(item.min_stock or 0),
                        'Punto de reposicion': float(item.rop or 0),
                        'Costo unitario': costo or None,
                        'Costo de cubrir el faltante': round(faltante * costo, 2) if costo else None,
                        f'Consumo ultimos {months} meses': round(c.get('qty', 0), 2),
                        'Cantidad de equipos': len(acc['equipos']),
                        'Equipos que lo usan': equipos_txt,
                    })
                consol_rows.sort(key=lambda r: (-r['Faltante'], r['Repuesto'] or ''))

                kardex_rows = []
                for item_id, c in consumo.items():
                    item = items_map.get(item_id)
                    if not item:
                        continue
                    stock = float(item.stock or 0)
                    mensual = c['qty'] / months if months else 0
                    lead = int(item.lead_time or 0)
                    sugerido = (mensual * (lead / 30.0)) + float(item.safety_stock or 0)
                    kardex_rows.append({
                        'Codigo': item.code,
                        'Repuesto': item.name,
                        'Familia': item.family or '',
                        f'Salidas ultimos {months} meses': round(c['qty'], 2),
                        'Numero de salidas': c['salidas'],
                        'Consumo mensual promedio': round(mensual, 2),
                        'Stock actual': stock,
                        'Meses de cobertura del stock': round(stock / mensual, 1) if mensual > 0 else None,
                        'Cantidad necesaria (equipos)': round(consolidado.get(item_id, {}).get('qty', 0), 2),
                        'Stock minimo actual': float(item.min_stock or 0),
                        'Dias de reposicion del proveedor': lead,
                        'Stock minimo sugerido': round(sugerido, 2) if sugerido > 0 else None,
                        'Ultima salida': c['ultima'],
                        'Ordenes de trabajo que lo consumieron': len(c['ots']),
                    })
                kardex_rows.sort(key=lambda r: -r[f'Salidas ultimos {months} meses'])

                detalle.sort(key=lambda r: (r['Area'], r['Linea'], r['Tag equipo'],
                                            r['Activo rotativo'], r['Repuesto']))
                por_catalogar.sort(key=lambda r: (r['Area'], r['Linea'], r['Equipo'], r['Repuesto']))

                hojas = [
                    ('Consolidado', consol_rows,
                     ['Codigo', 'Repuesto', 'Familia', 'Marca', 'Unidad', 'Criticidad',
                      'Clase ABC', 'Stock actual', 'Cantidad necesaria (todos los equipos)',
                      'Faltante', 'Cobertura %', 'Stock minimo', 'Punto de reposicion',
                      'Costo unitario', 'Costo de cubrir el faltante',
                      f'Consumo ultimos {months} meses', 'Cantidad de equipos',
                      'Equipos que lo usan']),
                    ('Detalle por equipo', detalle,
                     ['Area', 'Linea', 'Tag equipo', 'Equipo', 'Codigo activo',
                      'Activo rotativo', 'Tipo de activo', 'Especialidad',
                      'Codigo almacen', 'Repuesto', 'Unidad', 'Cantidad necesaria',
                      'Stock actual', 'Estado', 'Notas']),
                    ('Por catalogar', por_catalogar,
                     ['Origen', 'Area', 'Linea', 'Equipo', 'Activo / Componente',
                      'Repuesto', 'Codigo propuesto', 'Marca', 'Cantidad', 'Que hacer']),
                    ('Repuestos en fichas tecnicas', specs_rows,
                     ['Area', 'Linea', 'Equipo', 'Codigo activo', 'Activo rotativo',
                      'Campo de la ficha', 'Valor (repuesto)', 'Unidad',
                      'Ya esta en la lista del activo']),
                    ('Consumo de almacen', kardex_rows,
                     ['Codigo', 'Repuesto', 'Familia', f'Salidas ultimos {months} meses',
                      'Numero de salidas', 'Consumo mensual promedio', 'Stock actual',
                      'Meses de cobertura del stock', 'Cantidad necesaria (equipos)',
                      'Stock minimo actual', 'Dias de reposicion del proveedor',
                      'Stock minimo sugerido', 'Ultima salida',
                      'Ordenes de trabajo que lo consumieron']),
                ]

                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    for nombre_hoja, filas, columnas in hojas:
                        df = pd.DataFrame(filas, columns=columnas)
                        df.to_excel(writer, index=False, sheet_name=nombre_hoja[:31])
                        ws = writer.sheets[nombre_hoja[:31]]
                        ws.freeze_panes = 'A2'
                        for idx, col in enumerate(columnas, start=1):
                            largo = max([len(str(col))] + [
                                len(str(f.get(col, ''))) for f in filas[:400]])
                            ws.column_dimensions[
                                ws.cell(row=1, column=idx).column_letter
                            ].width = min(max(largo + 2, 10), 55)

                output.seek(0)
                sufijo = _date.today().isoformat()
                return send_file(
                    output,
                    download_name=f"Repuestos_por_Equipo_{sufijo}.xlsx",
                    as_attachment=True,
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                )
            except Exception as e:
                logger.exception('export_bom_excel error')
                return jsonify({"error": str(e)}), 500

