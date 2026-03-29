from datetime import datetime
from io import BytesIO

import pandas as pd
from flask import jsonify, request, send_file


def register_warehouse_routes(app, db, logger, WarehouseItem, WarehouseMovement):
    # --- WAREHOUSE ENDPOINTS ---
    @app.route('/api/warehouse', methods=['GET', 'POST'])
    def handle_warehouse():
        if request.method == 'POST':
            try:
                data = request.json
                data['code'] = 'REP-TEMP'

                # Sanitization for models
                valid_keys = {c.name for c in WarehouseItem.__table__.columns}
                clean_data = {k: v for k, v in data.items() if k in valid_keys}

                item = WarehouseItem(**clean_data)
                db.session.add(item)
                db.session.flush()
                item.code = f"REP-{item.id:04d}"
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
                item.is_active = not item.is_active  # Toggle
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

