import pandas as pd
from flask import jsonify, request


def register_data_import_routes(
    app,
    db,
    logger,
    Area,
    Line,
    Equipment,
    System,
    Component,
    SparePart,
):
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
            return jsonify({"message": f"Procesadas {processed_count} filas de jerarquÃ­a."}), 201

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


    # --- PURCHASING MODELS MOVED TO models.py ---

    # --- PURCHASING API ---

