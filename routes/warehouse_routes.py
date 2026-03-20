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
                        'CÃ³digo': i.code,
                        'Nombre': i.name,
                        'DescripciÃ³n': i.description,
                        'Familia': i.family,
                        'Marca': i.brand,
                        'CategorÃ­a': i.category,
                        'Stock Actual': i.stock,
                        'Unidad': i.unit,
                        'UbicaciÃ³n': i.location,
                        'Criticidad': i.criticality,
                        'Costo Promedio': i.average_cost,
                        'Costo Unitario': i.unit_cost,
                        'ABC': i.abc_class,
                        'XYZ': i.xyz_class,
                        'Lead Time (DÃ­as)': i.lead_time,
                        'Stock Seguridad': i.safety_stock,
                        'Punto Reorden (ROP)': i.rop,
                        'Stock MÃ¡ximo': i.max_stock,
                        'Lote MÃ­nimo': i.min_order_qty,
                        'Activo': 'SÃ­' if i.is_active else 'No',
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
                        'RazÃ³n': m.reason,
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
