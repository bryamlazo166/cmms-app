import re
import unicodedata
from io import BytesIO, StringIO

import pandas as pd
from flask import jsonify, request, send_file


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
    def _norm_col(col_name):
        raw = str(col_name or "").strip().lower()
        no_accents = "".join(
            ch for ch in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(ch)
        )
        return re.sub(r"[^a-z0-9]+", "", no_accents)

    def _clean_text(value):
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    def _default_tag(equipment_name, line_name):
        eq = "".join(ch for ch in (equipment_name or "").upper() if ch.isalnum())[:4] or "EQ"
        ln = "".join(ch for ch in (line_name or "").upper() if ch.isalnum())[:4] or "LN"
        return f"{eq}-{ln}"

    def _map_hierarchy_columns(df):
        aliases = {
            "area": "area",
            "areaname": "area",
            "nombrearea": "area",
            "linea": "line",
            "line": "line",
            "linename": "line",
            "nombrelinea": "line",
            "equipo": "equipment",
            "equipment": "equipment",
            "equipmentname": "equipment",
            "equipname": "equipment",
            "nombreequipo": "equipment",
            "tag": "equipment_tag",
            "tagequipo": "equipment_tag",
            "equiptag": "equipment_tag",
            "codigoequipo": "equipment_tag",
            "sistema": "system",
            "system": "system",
            "systemname": "system",
            "nombresistema": "system",
            "componente": "component",
            "component": "component",
            "componentname": "component",
            "nombrecomponente": "component",
            "descripcion": "component_description",
            "descripcioncomponente": "component_description",
            "componentdescription": "component_description",
            "criticidad": "component_criticality",
            "criticality": "component_criticality",
            "criticidadcomponente": "component_criticality",
        }

        mapped = {}
        for col in list(df.columns):
            key = aliases.get(_norm_col(col))
            if key and key not in mapped:
                mapped[key] = col
        return mapped

    def _extract_hierarchy_rows_from_df(df):
        col_map = _map_hierarchy_columns(df)
        required = ["area", "line", "equipment", "system", "component"]
        if not all(key in col_map for key in required):
            return []

        rows = []
        for idx, row in df.iterrows():
            rows.append(
                {
                    "row_num": int(idx) + 2,
                    "area": _clean_text(row.get(col_map["area"])),
                    "line": _clean_text(row.get(col_map["line"])),
                    "equipment": _clean_text(row.get(col_map["equipment"])),
                    "equipment_tag": _clean_text(row.get(col_map.get("equipment_tag"))),
                    "system": _clean_text(row.get(col_map["system"])),
                    "component": _clean_text(row.get(col_map["component"])),
                    "component_description": _clean_text(row.get(col_map.get("component_description"))),
                    "component_criticality": _clean_text(row.get(col_map.get("component_criticality"))),
                }
            )
        return rows

    def _upsert_hierarchy_row(row_data, stats):
        required_values = ["area", "line", "equipment", "system", "component"]
        missing = [k for k in required_values if not row_data.get(k)]
        if missing:
            return {"ok": False, "error": f"faltan valores: {', '.join(missing)}"}

        area_name = row_data["area"]
        line_name = row_data["line"]
        equipment_name = row_data["equipment"]
        equipment_tag = row_data.get("equipment_tag")
        system_name = row_data["system"]
        component_name = row_data["component"]
        component_description = row_data.get("component_description")
        component_criticality = row_data.get("component_criticality")

        area = Area.query.filter_by(name=area_name).first()
        if not area:
            area = Area(name=area_name, description="")
            db.session.add(area)
            db.session.flush()
            stats["created_areas"] += 1

        line_obj = Line.query.filter_by(name=line_name, area_id=area.id).first()
        if not line_obj:
            line_obj = Line(name=line_name, description="", area=area)
            db.session.add(line_obj)
            db.session.flush()
            stats["created_lines"] += 1

        equip = Equipment.query.filter_by(name=equipment_name, line_id=line_obj.id).first()
        if not equip:
            equip = Equipment(
                name=equipment_name,
                tag=equipment_tag or _default_tag(equipment_name, line_name),
                description="",
                line=line_obj,
            )
            db.session.add(equip)
            db.session.flush()
            stats["created_equipments"] += 1
        elif equipment_tag and (not equip.tag or equip.tag.strip() in {"", "-"}):
            equip.tag = equipment_tag
            stats["updated_equipments"] += 1

        system = System.query.filter_by(name=system_name, equipment_id=equip.id).first()
        if not system:
            system = System(name=system_name, equipment=equip)
            db.session.add(system)
            db.session.flush()
            stats["created_systems"] += 1

        comp = Component.query.filter_by(name=component_name, system_id=system.id).first()
        if not comp:
            comp = Component(
                name=component_name,
                description=component_description or "",
                criticality=component_criticality or "Media",
                system=system,
            )
            db.session.add(comp)
            stats["created_components"] += 1
        else:
            touched = False
            if component_description and not (comp.description or "").strip():
                comp.description = component_description
                touched = True
            if component_criticality and not (comp.criticality or "").strip():
                comp.criticality = component_criticality
                touched = True
            if touched:
                stats["updated_components"] += 1
            else:
                stats["skipped_existing"] += 1

        return {"ok": True}

    def _process_hierarchy_rows(rows):
        stats = {
            "rows_received": len(rows),
            "rows_processed": 0,
            "created_areas": 0,
            "created_lines": 0,
            "created_equipments": 0,
            "created_systems": 0,
            "created_components": 0,
            "updated_equipments": 0,
            "updated_components": 0,
            "skipped_existing": 0,
        }
        errors = []

        for row_data in rows:
            result = _upsert_hierarchy_row(row_data, stats)
            if result.get("ok"):
                stats["rows_processed"] += 1
            else:
                errors.append({"row": row_data.get("row_num"), "error": result.get("error")})

        return stats, errors

    @app.route('/api/upload-excel', methods=['POST'])
    def upload_excel():
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        try:
            xls = pd.ExcelFile(file)
            hierarchy_rows = []
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name)
                if df is None or df.empty:
                    continue
                df = df.where(pd.notnull(df), None)
                hierarchy_rows.extend(_extract_hierarchy_rows_from_df(df))

            if not hierarchy_rows:
                return jsonify(
                    {
                        "error": (
                            "Formato no reconocido. Usa la plantilla de JerarquiaCompleta con columnas: "
                            "Area, Linea, Equipo, TagEquipo(opcional), Sistema, Componente, "
                            "DescripcionComponente(opcional), CriticidadComponente(opcional)."
                        )
                    }
                ), 400

            stats, errors = _process_hierarchy_rows(hierarchy_rows)
            db.session.commit()
            return jsonify(
                {
                    "message": "Carga masiva completada",
                    "stats": stats,
                    "errors": errors[:30],
                }
            ), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Excel Upload Failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/bulk-paste', methods=['POST'])
    def bulk_paste():
        try:
            data = request.json or {}
            entity_type = data.get('entity_type')
            raw_data = data.get('raw_data')

            if not entity_type or not raw_data:
                return jsonify({"error": "Missing entity_type or raw_data"}), 400

            df = pd.read_csv(StringIO(raw_data), sep='\t')
            df = df.where(pd.notnull(df), None)

            if entity_type == 'Areas':
                for _, row in df.iterrows():
                    name = _clean_text(row.get('Name'))
                    if name and not Area.query.filter_by(name=name).first():
                        db.session.add(Area(name=name, description=_clean_text(row.get('Description')) or ''))

            elif entity_type == 'Lines':
                for _, row in df.iterrows():
                    area_name = _clean_text(row.get('AreaName'))
                    line_name = _clean_text(row.get('Name'))
                    area = Area.query.filter_by(name=area_name).first() if area_name else None
                    if area and line_name and not Line.query.filter_by(name=line_name, area_id=area.id).first():
                        db.session.add(Line(name=line_name, description=_clean_text(row.get('Description')) or '', area=area))

            elif entity_type == 'Equipments':
                for _, row in df.iterrows():
                    area_name = _clean_text(row.get('AreaName'))
                    line_name = _clean_text(row.get('LineName'))
                    equip_name = _clean_text(row.get('Name'))
                    tag = _clean_text(row.get('Tag'))
                    if not (area_name and line_name and equip_name):
                        continue
                    area = Area.query.filter_by(name=area_name).first()
                    line_obj = Line.query.filter_by(name=line_name, area_id=area.id).first() if area else None
                    if line_obj and not Equipment.query.filter_by(name=equip_name, line_id=line_obj.id).first():
                        db.session.add(
                            Equipment(
                                name=equip_name,
                                tag=tag or _default_tag(equip_name, line_name),
                                description=_clean_text(row.get('Description')) or '',
                                line=line_obj,
                            )
                        )

            elif entity_type == 'Systems':
                for _, row in df.iterrows():
                    area_name = _clean_text(row.get('AreaName'))
                    line_name = _clean_text(row.get('LineName'))
                    equip_name = _clean_text(row.get('EquipmentName'))
                    sys_name = _clean_text(row.get('Name'))
                    if not (area_name and line_name and equip_name and sys_name):
                        continue
                    area = Area.query.filter_by(name=area_name).first()
                    line_obj = Line.query.filter_by(name=line_name, area_id=area.id).first() if area else None
                    equip = Equipment.query.filter_by(name=equip_name, line_id=line_obj.id).first() if line_obj else None
                    if equip and not System.query.filter_by(name=sys_name, equipment_id=equip.id).first():
                        db.session.add(System(name=sys_name, equipment=equip))

            elif entity_type == 'Components':
                for _, row in df.iterrows():
                    area_name = _clean_text(row.get('AreaName'))
                    line_name = _clean_text(row.get('LineName'))
                    equip_name = _clean_text(row.get('EquipmentName'))
                    sys_name = _clean_text(row.get('SystemName'))
                    comp_name = _clean_text(row.get('Name'))
                    if not (area_name and line_name and equip_name and sys_name and comp_name):
                        continue
                    area = Area.query.filter_by(name=area_name).first()
                    line_obj = Line.query.filter_by(name=line_name, area_id=area.id).first() if area else None
                    equip = Equipment.query.filter_by(name=equip_name, line_id=line_obj.id).first() if line_obj else None
                    system = System.query.filter_by(name=sys_name, equipment_id=equip.id).first() if equip else None
                    if system and not Component.query.filter_by(name=comp_name, system_id=system.id).first():
                        db.session.add(
                            Component(
                                name=comp_name,
                                description=_clean_text(row.get('Description')) or '',
                                system=system,
                            )
                        )
            else:
                return jsonify({"error": "Invalid Entity Type"}), 400

            db.session.commit()
            return jsonify({"message": f"Bulk paste for {entity_type} completed"}), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Bulk Paste Failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/bulk-paste-hierarchy', methods=['POST'])
    def bulk_paste_hierarchy():
        try:
            data = request.json or {}
            raw_data = data.get('raw_data')

            if not raw_data:
                return jsonify({"error": "Faltan datos (raw_data)"}), 400

            lines = raw_data.strip().split('\n')
            if not lines:
                return jsonify({"error": "No hay datos"}), 400

            rows = []
            for i, raw_line in enumerate(lines, start=1):
                line = raw_line.strip()
                if not line:
                    continue

                parts = [p.strip() for p in line.split('\t')]
                if len(parts) < 5:
                    rows.append(
                        {
                            "row_num": i,
                            "area": None,
                            "line": None,
                            "equipment": None,
                            "equipment_tag": None,
                            "system": None,
                            "component": None,
                        }
                    )
                    continue

                # 5 cols: Area | Linea | Equipo | Sistema | Componente
                # 6+ cols: Area | Linea | Equipo | TagEquipo | Sistema | Componente | ...
                if len(parts) >= 6:
                    row = {
                        "row_num": i,
                        "area": _clean_text(parts[0]),
                        "line": _clean_text(parts[1]),
                        "equipment": _clean_text(parts[2]),
                        "equipment_tag": _clean_text(parts[3]),
                        "system": _clean_text(parts[4]),
                        "component": _clean_text(parts[5]),
                    }
                else:
                    row = {
                        "row_num": i,
                        "area": _clean_text(parts[0]),
                        "line": _clean_text(parts[1]),
                        "equipment": _clean_text(parts[2]),
                        "equipment_tag": None,
                        "system": _clean_text(parts[3]),
                        "component": _clean_text(parts[4]),
                    }
                rows.append(row)

            stats, errors = _process_hierarchy_rows(rows)
            db.session.commit()
            return jsonify({"message": "Jerarquia procesada", "stats": stats, "errors": errors[:30]}), 201
        except Exception as e:
            db.session.rollback()
            logger.error(f"Hierarchy Paste Failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/export-data', methods=['GET'])
    def export_data():
        # Legacy endpoint kept for compatibility.
        try:
            data = []
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
                                data.append(
                                    {
                                        'Area': a.name,
                                        'Line': l.name if l else '',
                                        'Equipment': e.name if e else '',
                                        'Tag': e.tag if e else '',
                                        'System': s.name if s else '',
                                        'Component': c.name if c else '',
                                        'ComponentDescription': c.description if c else '',
                                        'ComponentCriticality': c.criticality if c else '',
                                    }
                                )

            df = pd.DataFrame(data)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='BaseDatos_Completa')

            output.seek(0)
            return send_file(
                output,
                download_name="CMMS_BaseDatos_Completa.xlsx",
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            logger.error(f"Export Failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/export-hierarchy-complete', methods=['GET'])
    def export_hierarchy_complete():
        try:
            data = []
            areas = Area.query.order_by(Area.name.asc()).all()
            for a in areas:
                lines = Line.query.filter_by(area_id=a.id).order_by(Line.name.asc()).all() or [None]
                for l in lines:
                    equips = (
                        Equipment.query.filter_by(line_id=l.id).order_by(Equipment.name.asc()).all() if l else []
                    ) or [None]
                    for e in equips:
                        systems = (
                            System.query.filter_by(equipment_id=e.id).order_by(System.name.asc()).all() if e else []
                        ) or [None]
                        for s in systems:
                            comps = (
                                Component.query.filter_by(system_id=s.id).order_by(Component.name.asc()).all() if s else []
                            ) or [None]
                            for c in comps:
                                data.append(
                                    {
                                        "Area": a.name,
                                        "Linea": l.name if l else "",
                                        "Equipo": e.name if e else "",
                                        "TagEquipo": e.tag if e else "",
                                        "Sistema": s.name if s else "",
                                        "Componente": c.name if c else "",
                                        "DescripcionComponente": c.description if c else "",
                                        "CriticidadComponente": c.criticality if c else "",
                                    }
                                )

            df = pd.DataFrame(data)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='ArbolCompleto')

            output.seek(0)
            return send_file(
                output,
                download_name="CMMS_Arbol_Completo.xlsx",
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            logger.error(f"Hierarchy export failed: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route('/api/download-template', methods=['GET'])
    def download_template():
        try:
            template_rows = [
                {
                    "Area": "COCCION",
                    "Linea": "L. Digestor #1",
                    "Equipo": "DIGESTOR #1",
                    "TagEquipo": "TH1",
                    "Sistema": "SISTEMA DE TRANSMISION",
                    "Componente": "CADENA",
                    "DescripcionComponente": "Cadena principal",
                    "CriticidadComponente": "Media",
                },
                {
                    "Area": "COCCION",
                    "Linea": "L. Digestor #1",
                    "Equipo": "DIGESTOR #1",
                    "TagEquipo": "TH1",
                    "Sistema": "SISTEMA DE TRANSMISION",
                    "Componente": "FAJA",
                    "DescripcionComponente": "Faja trapezoidal",
                    "CriticidadComponente": "Alta",
                },
            ]

            instructions_rows = [
                {"Campo": "Area", "Requerido": "SI", "Descripcion": "Nivel 1"},
                {"Campo": "Linea", "Requerido": "SI", "Descripcion": "Nivel 2"},
                {"Campo": "Equipo", "Requerido": "SI", "Descripcion": "Nivel 3"},
                {"Campo": "TagEquipo", "Requerido": "NO", "Descripcion": "Codigo/TAG del equipo"},
                {"Campo": "Sistema", "Requerido": "SI", "Descripcion": "Nivel 4"},
                {"Campo": "Componente", "Requerido": "SI", "Descripcion": "Nivel 5"},
                {"Campo": "DescripcionComponente", "Requerido": "NO", "Descripcion": "Texto libre"},
                {"Campo": "CriticidadComponente", "Requerido": "NO", "Descripcion": "Baja, Media o Alta"},
            ]

            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                pd.DataFrame(template_rows).to_excel(writer, sheet_name='JerarquiaCompleta', index=False)
                pd.DataFrame(instructions_rows).to_excel(writer, sheet_name='Instrucciones', index=False)

            output.seek(0)
            return send_file(
                output,
                download_name="plantilla_jerarquia_completa_cmms.xlsx",
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except Exception as e:
            logger.error(f"Template Download Failed: {e}")
            return jsonify({"error": str(e)}), 500
