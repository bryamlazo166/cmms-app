from io import BytesIO

import pandas as pd
from flask import jsonify, request, send_file


def register_tools_routes(app, db, Tool):
    @app.route('/api/tools', methods=['GET', 'POST'])
    def handle_tools():
        if request.method == 'POST':
            try:
                data = request.json
                data['code'] = 'HRR-TEMP'

                tool = Tool(**data)
                db.session.add(tool)
                db.session.flush()
                tool.code = f"HRR-{tool.id:03d}"
                db.session.commit()
                return jsonify(tool.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        # GET - return active tools
        show_all = request.args.get('all', 'false').lower() == 'true'
        if show_all:
            tools = Tool.query.order_by(Tool.id.asc()).all()
        else:
            tools = Tool.query.filter_by(is_active=True).order_by(Tool.id.asc()).all()
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

    @app.route('/api/tools/export', methods=['GET'])
    def export_tools_excel():
        try:
            tools = Tool.query.order_by(Tool.id.asc()).all()
            rows = []
            for t in tools:
                rows.append(
                    {
                        'Codigo': t.code,
                        'Nombre': t.name,
                        'Categoria': t.category,
                        'Descripcion': t.description,
                        'Estado': t.status,
                        'Ubicacion': t.location,
                        'Activo': 'SI' if t.is_active else 'NO',
                    }
                )

            df = pd.DataFrame(rows)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Herramientas')
            output.seek(0)

            return send_file(
                output,
                download_name='Herramientas_CMMS.xlsx',
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/tools/template', methods=['GET'])
    def download_tools_template():
        try:
            template_rows = [
                {
                    'Codigo': 'HRR-100',
                    'Nombre': 'LLAVE MIXTA 19 MM',
                    'Categoria': 'Manual',
                    'Descripcion': 'Herramienta para ajuste general',
                    'Estado': 'Disponible',
                    'Ubicacion': 'Gabinete A-1',
                },
                {
                    'Codigo': '',
                    'Nombre': 'EJEMPLO SIN CODIGO',
                    'Categoria': 'Manual',
                    'Descripcion': 'Si no coloca codigo se autogenera',
                    'Estado': 'Disponible',
                    'Ubicacion': 'Gabinete B-2',
                },
            ]
            df = pd.DataFrame(template_rows)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Plantilla')
            output.seek(0)

            return send_file(
                output,
                download_name='Plantilla_Herramientas_CMMS.xlsx',
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/tools/import', methods=['POST'])
    def import_tools_excel():
        try:
            if 'file' not in request.files:
                return jsonify({'error': 'Archivo no recibido'}), 400

            file = request.files['file']
            if not file or not file.filename:
                return jsonify({'error': 'Archivo invalido'}), 400

            df = pd.read_excel(file)
            df.columns = [str(c).strip() for c in df.columns]

            required = {'Nombre'}
            if not required.issubset(set(df.columns)):
                return jsonify({'error': 'La plantilla debe contener al menos la columna Nombre'}), 400

            # Existing maps
            existing_by_code = {str(t.code).strip().upper(): t for t in Tool.query.all() if t.code}
            existing_name_cat = {
                (str(t.name).strip().upper(), str(t.category or '').strip().upper()): t
                for t in Tool.query.all()
            }

            inserted = 0
            skipped = 0
            errors = []
            seen_codes = set()
            seen_name_cat = set()

            def normalize_text(v):
                if pd.isna(v):
                    return None
                txt = str(v).strip()
                return txt if txt else None

            # Determine next code only once
            last = Tool.query.order_by(Tool.id.desc()).first()
            next_id = (last.id if last else 0) + 1

            for idx, row in df.iterrows():
                row_number = idx + 2  # header row is 1
                name = normalize_text(row.get('Nombre'))
                if not name:
                    skipped += 1
                    errors.append(f'Fila {row_number}: sin nombre, omitida')
                    continue

                category = normalize_text(row.get('Categoria'))
                description = normalize_text(row.get('Descripcion'))
                status = normalize_text(row.get('Estado')) or 'Disponible'
                location = normalize_text(row.get('Ubicacion'))

                code = normalize_text(row.get('Codigo'))
                code_norm = code.upper() if code else None
                key_name_cat = (name.upper(), (category or '').upper())

                # Duplicate checks against file and DB
                if code_norm:
                    if code_norm in seen_codes or code_norm in existing_by_code:
                        skipped += 1
                        continue
                if key_name_cat in seen_name_cat or key_name_cat in existing_name_cat:
                    skipped += 1
                    continue

                if not code_norm:
                    code_norm = f"HRR-{next_id:03d}"
                    while code_norm in existing_by_code or code_norm in seen_codes:
                        next_id += 1
                        code_norm = f"HRR-{next_id:03d}"

                tool = Tool(
                    code=code_norm,
                    name=name,
                    category=category,
                    description=description,
                    status=status,
                    location=location,
                    is_active=True,
                )
                db.session.add(tool)
                inserted += 1

                seen_codes.add(code_norm)
                seen_name_cat.add(key_name_cat)

                next_id += 1

            db.session.commit()
            return jsonify(
                {
                    'inserted': inserted,
                    'skipped_duplicates': skipped,
                    'notes': errors[:30],
                }
            )
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
