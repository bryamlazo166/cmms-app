"""Trabajos estandar: OTs repetitivas que salen ya llenas.

Un trabajo estandar ("Cambio de chumacera conducida") se aplica a uno o varios
equipos; por cada equipo elegido se crea la OT con descripcion, ubicacion,
tipo, duracion, personal y materiales previstos, y opcionalmente su aviso.
"""
import re
from datetime import datetime

from flask import jsonify, request

from bot.resolvers import normalize_token

OPEN_OT_STATUSES = ('Abierta', 'Programada', 'En Progreso')
TEXT_FIELDS = ('name', 'description_template', 'maintenance_type', 'failure_mode',
               'specialty', 'component_name', 'tag_filter', 'priority', 'criticality')
INT_FIELDS = ('area_id', 'line_id', 'equipment_id', 'system_id', 'component_id')


class _BadTarget(ValueError):
    """Equipo/componente invalido en la generacion: se revierte todo el lote."""


def _tokens(text):
    """Tokens normalizados ('Chumacera conducida' -> {'chumacer', 'conduc'})."""
    return {normalize_token(t) for t in re.split(r'[\s\-_/.,]+', text or '') if len(t) > 2}


def _natural_key(text):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)', text or '')]


def _int_or_none(value):
    try:
        return int(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    try:
        return float(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _clean_materials(raw):
    out = []
    for m in raw or []:
        name = (m.get('name') or '').strip()
        if not name:
            continue
        qty = _float_or_none(m.get('quantity')) or 1
        out.append({
            'item_type': m.get('item_type') if m.get('item_type') in ('warehouse', 'tool') else 'free',
            'item_id': _int_or_none(m.get('item_id')),
            'code': (m.get('code') or '').strip() or None,
            'name': name,
            'quantity': int(qty) if float(qty).is_integer() else qty,
            'unit': (m.get('unit') or '').strip() or None,
            'subtype': m.get('subtype') if m.get('subtype') in ('repuesto', 'consumible', 'herramienta') else 'repuesto',
        })
    return out


def render_description(template, equipment, system=None, component=None, line=None, area=None):
    values = {
        'tag': equipment.tag or '',
        'equipo': equipment.name or '',
        'name': equipment.name or '',
        'componente': component.name if component else '',
        'sistema': system.name if system else '',
        'linea': line.name if line else '',
        'area': area.name if area else '',
    }
    text = template or ''
    for key, val in values.items():
        text = re.sub(r'\{' + key + r'\}', val, text, flags=re.I)
    # Si quedo un marcador vacio ("del  -") se limpian espacios repetidos
    return re.sub(r'\s{2,}', ' ', text).strip()


def register_work_templates_routes(
    app, db, logger,
    WorkTemplate, WorkOrder, MaintenanceNotice, OTPersonnel, OTMaterial, OTLogEntry,
    Area, Line, Equipment, System, Component,
):

    def _apply_fields(tpl, data):
        for f in TEXT_FIELDS:
            if f in data:
                val = data.get(f)
                setattr(tpl, f, (val or '').strip() or None if isinstance(val, str) else val)
        for f in INT_FIELDS:
            if f in data:
                setattr(tpl, f, _int_or_none(data.get(f)))
        if 'estimated_duration' in data:
            tpl.estimated_duration = _float_or_none(data.get('estimated_duration'))
        if 'tech_count' in data:
            tpl.tech_count = max(1, _int_or_none(data.get('tech_count')) or 1)
        if 'create_notice' in data:
            tpl.create_notice = bool(data.get('create_notice'))
        if 'is_active' in data:
            tpl.is_active = bool(data.get('is_active'))
        if 'materials' in data:
            tpl.materials = _clean_materials(data.get('materials'))
        if tpl.failure_mode:
            tpl.failure_mode = tpl.failure_mode.upper()
        # Sin equipo fijo, sistema y componente fijos no tienen sentido
        if not tpl.equipment_id:
            tpl.system_id = None
            tpl.component_id = None

    def _validate(tpl):
        if not tpl.name:
            return "Falta el nombre del trabajo"
        if not tpl.description_template:
            return "Falta la descripcion"
        return None

    def _resolve_targets(tpl):
        """Lista de (equipo, sistema, componente) donde aplica el trabajo."""
        q = Equipment.query
        if tpl.equipment_id:
            q = q.filter(Equipment.id == tpl.equipment_id)
        else:
            if tpl.line_id:
                q = q.filter(Equipment.line_id == tpl.line_id)
            elif tpl.area_id:
                q = q.join(Line, Equipment.line_id == Line.id).filter(Line.area_id == tpl.area_id)
        equipments = q.all()
        if tpl.tag_filter and not tpl.equipment_id:
            terms = [t.strip().lower() for t in tpl.tag_filter.split(',') if t.strip()]
            equipments = [e for e in equipments
                          if any(t in (e.tag or '').lower() for t in terms)]
        if not equipments:
            return []
        eq_by_id = {e.id: e for e in equipments}

        if tpl.equipment_id and tpl.component_id:
            comp = Component.query.get(tpl.component_id)
            sys_ = System.query.get(comp.system_id) if comp else None
            eq = eq_by_id.get(tpl.equipment_id)
            return [(eq, sys_, comp)] if eq and comp and sys_ and sys_.equipment_id == eq.id else []

        if tpl.component_name:
            wanted = _tokens(tpl.component_name)
            rows = (db.session.query(Component, System)
                    .join(System, Component.system_id == System.id)
                    .filter(System.equipment_id.in_(list(eq_by_id)))
                    .all())
            if tpl.equipment_id and tpl.system_id:
                rows = [(c, s) for c, s in rows if s.id == tpl.system_id]
            return [(eq_by_id[s.equipment_id], s, c) for c, s in rows
                    if wanted and wanted <= _tokens(c.name)]

        if tpl.equipment_id and tpl.system_id:
            sys_ = System.query.get(tpl.system_id)
            eq = eq_by_id.get(tpl.equipment_id)
            return [(eq, sys_ if sys_ and sys_.equipment_id == eq.id else None, None)] if eq else []
        return [(e, None, None) for e in equipments]

    def _open_ot_index(equipment_ids):
        if not equipment_ids:
            return []
        return WorkOrder.query.filter(
            WorkOrder.equipment_id.in_(list(equipment_ids)),
            WorkOrder.status.in_(OPEN_OT_STATUSES),
        ).all()

    def _find_open_ot(open_ots, equipment_id, component_id, description):
        desc = (description or '').lower()[:40]
        for ot in open_ots:
            if ot.equipment_id != equipment_id:
                continue
            if component_id and ot.component_id == component_id:
                return ot
            if not component_id and desc and (ot.description or '').lower()[:40] == desc:
                return ot
        return None

    def _current_user_name():
        try:
            from flask_login import current_user
            return getattr(current_user, 'full_name', None) or getattr(current_user, 'username', None)
        except Exception:
            return None

    # ── CRUD ────────────────────────────────────────────────────────────────

    @app.route('/api/work-templates', methods=['GET', 'POST'])
    def handle_work_templates():
        if request.method == 'POST':
            try:
                tpl = WorkTemplate(created_by=_current_user_name())
                _apply_fields(tpl, request.json or {})
                err = _validate(tpl)
                if err:
                    return jsonify({"error": err}), 400
                db.session.add(tpl)
                db.session.commit()
                return jsonify(tpl.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                logger.exception('work template POST error')
                return jsonify({"error": str(e)}), 500

        q = WorkTemplate.query
        if request.args.get('only_active', '1') == '1':
            q = q.filter(WorkTemplate.is_active == True)  # noqa: E712
        rows = q.order_by(WorkTemplate.name).all()
        return jsonify([t.to_dict() for t in rows])

    @app.route('/api/work-templates/<int:template_id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_work_template(template_id):
        tpl = WorkTemplate.query.get_or_404(template_id)
        if request.method == 'GET':
            return jsonify(tpl.to_dict())
        try:
            if request.method == 'DELETE':
                db.session.delete(tpl)
                db.session.commit()
                return jsonify({"ok": True})
            _apply_fields(tpl, request.json or {})
            err = _validate(tpl)
            if err:
                db.session.rollback()
                return jsonify({"error": err}), 400
            db.session.commit()
            return jsonify(tpl.to_dict())
        except Exception as e:
            db.session.rollback()
            logger.exception('work template PUT/DELETE error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/work-templates/draft-from-ot/<int:ot_id>', methods=['GET'])
    def work_template_draft_from_ot(ot_id):
        """Borrador de trabajo estandar a partir de una OT existente (no guarda)."""
        ot = WorkOrder.query.get_or_404(ot_id)
        eq = Equipment.query.get(ot.equipment_id) if ot.equipment_id else None
        comp = Component.query.get(ot.component_id) if ot.component_id else None

        # Reemplazar el tag del equipo por el marcador para que sirva a otros
        desc = ot.description or ''
        if eq and eq.tag:
            desc = re.sub(r'(?<![A-Za-z0-9])' + re.escape(eq.tag) + r'(?![A-Za-z0-9])',
                          '{tag}', desc, flags=re.I)

        specialty = None
        for p in OTPersonnel.query.filter_by(work_order_id=ot.id).all():
            specialty = p.specialty or (p.technician.specialty if p.technician else None)
            if specialty:
                break

        materials = []
        try:
            from models import Tool, WarehouseItem
        except Exception:
            Tool = WarehouseItem = None
        for m in OTMaterial.query.filter_by(work_order_id=ot.id).all():
            item = None
            if m.item_id and m.item_type == 'warehouse' and WarehouseItem:
                item = WarehouseItem.query.get(m.item_id)
            elif m.item_id and m.item_type == 'tool' and Tool:
                item = Tool.query.get(m.item_id)
            materials.append({
                'item_type': m.item_type if item else 'free',
                'item_id': m.item_id if item else None,
                'code': getattr(item, 'code', None),
                'name': getattr(item, 'name', None) or m.item_name_free or '-',
                'quantity': m.quantity or 1,
                'unit': m.unit,
                'subtype': m.subtype or ('herramienta' if m.item_type == 'tool' else 'repuesto'),
            })

        return jsonify({
            'name': (ot.description or 'Trabajo estandar')[:80],
            'description_template': desc,
            'maintenance_type': ot.maintenance_type or 'Correctivo',
            'failure_mode': ot.failure_mode,
            'estimated_duration': ot.real_duration or ot.estimated_duration,
            'tech_count': ot.tech_count or 1,
            'specialty': specialty,
            'component_name': comp.name if comp else None,
            'create_notice': bool(ot.notice_id),
            'materials': _clean_materials(materials),
            'source_ot_code': ot.code,
            'source_equipment_tag': eq.tag if eq else None,
        })

    # ── Aplicar: candidatos y generacion ──────────────────────────────────────

    @app.route('/api/work-templates/preview-targets', methods=['POST'])
    def work_template_preview_targets():
        """Equipos donde aplicaria un trabajo aun no guardado (para el editor)."""
        tpl = WorkTemplate()
        _apply_fields(tpl, request.json or {})
        tpl.description_template = tpl.description_template or ''
        targets = _targets_payload(tpl)
        return jsonify({'count': len(targets),
                        'tags': [t['equipment_tag'] for t in targets[:40]]})

    @app.route('/api/work-templates/<int:template_id>/targets', methods=['GET'])
    def work_template_targets(template_id):
        tpl = WorkTemplate.query.get_or_404(template_id)
        return jsonify({'template': tpl.to_dict(), 'targets': _targets_payload(tpl)})

    def _targets_payload(tpl):
        targets = _resolve_targets(tpl)
        lines = {l.id: l for l in Line.query.all()}
        areas = {a.id: a for a in Area.query.all()}
        open_ots = _open_ot_index({eq.id for eq, _, _ in targets})

        result = []
        for eq, sys_, comp in targets:
            ln = lines.get(eq.line_id)
            ar = areas.get(ln.area_id) if ln else None
            desc = render_description(tpl.description_template, eq, sys_, comp, ln, ar)
            open_ot = _find_open_ot(open_ots, eq.id, comp.id if comp else None, desc)
            result.append({
                'key': f"{eq.id}:{sys_.id if sys_ else ''}:{comp.id if comp else ''}",
                'equipment_id': eq.id,
                'equipment_tag': eq.tag,
                'equipment_name': eq.name,
                'system_id': sys_.id if sys_ else None,
                'system_name': sys_.name if sys_ else None,
                'component_id': comp.id if comp else None,
                'component_name': comp.name if comp else None,
                'line_name': ln.name if ln else None,
                'area_name': ar.name if ar else None,
                'description': desc,
                'open_ot_code': open_ot.code if open_ot else None,
                'open_ot_status': open_ot.status if open_ot else None,
            })
        result.sort(key=lambda r: (r['area_name'] or '', r['line_name'] or '',
                                   _natural_key(r['equipment_tag']), r['system_name'] or ''))
        return result

    @app.route('/api/work-templates/<int:template_id>/generate', methods=['POST'])
    def work_template_generate(template_id):
        """Crea una OT (y su aviso, si se pide) por cada equipo elegido.

        Body: {targets: [{equipment_id, system_id, component_id, description?}],
               scheduled_date?, create_notice?}
        """
        tpl = WorkTemplate.query.get_or_404(template_id)
        data = request.json or {}
        targets = data.get('targets') or []
        if not targets:
            return jsonify({"error": "Elija al menos un equipo"}), 400
        if len(targets) > 100:
            return jsonify({"error": "Maximo 100 OTs por vez"}), 400

        scheduled_date = (data.get('scheduled_date') or '').strip()[:10] or None
        create_notice = bool(data.get('create_notice', tpl.create_notice))
        status = 'Programada' if scheduled_date else 'Abierta'
        user_name = _current_user_name()

        from utils.tz import now_lima_iso
        now_txt = now_lima_iso(with_seconds=False).replace('T', ' ')
        today = now_txt[:10]

        materials = tpl.materials or []
        material_lines = []
        for m in materials:
            qty = f"{m.get('quantity') or 1} {m.get('unit') or ''}".strip()
            code = f" [{m['code']}]" if m.get('code') else ''
            material_lines.append(f"- {qty} {m.get('name')}{code} ({m.get('subtype') or 'repuesto'})")

        lines = {l.id: l for l in Line.query.all()}
        areas = {a.id: a for a in Area.query.all()}

        created = []
        notices_created = []
        try:
            for t in targets:
                eq = Equipment.query.get(_int_or_none(t.get('equipment_id')))
                if not eq:
                    raise _BadTarget(f"El equipo {t.get('equipment_id')} no existe")
                sys_ = System.query.get(_int_or_none(t.get('system_id'))) if t.get('system_id') else None
                comp = Component.query.get(_int_or_none(t.get('component_id'))) if t.get('component_id') else None
                if comp and (not sys_ or comp.system_id != sys_.id):
                    sys_ = System.query.get(comp.system_id)
                if sys_ and sys_.equipment_id != eq.id:
                    raise _BadTarget(f"El componente elegido no pertenece a {eq.tag}")
                ln = lines.get(eq.line_id)
                ar = areas.get(ln.area_id) if ln else None

                desc = (t.get('description') or '').strip() or \
                    render_description(tpl.description_template, eq, sys_, comp, ln, ar)
                hierarchy = dict(
                    area_id=ar.id if ar else None,
                    line_id=eq.line_id,
                    equipment_id=eq.id,
                    system_id=sys_.id if sys_ else None,
                    component_id=comp.id if comp else None,
                )

                notice = None
                if create_notice:
                    notice = MaintenanceNotice(
                        reporter_name=user_name,
                        reporter_type='Mantenimiento',
                        specialty=tpl.specialty,
                        description=desc,
                        criticality=tpl.criticality,
                        priority=tpl.priority or 'Media',
                        maintenance_type=tpl.maintenance_type,
                        failure_mode=tpl.failure_mode,
                        request_date=now_txt,
                        reported_at=now_txt,
                        report_channel='SISTEMA',
                        planning_date=scheduled_date,
                        status='Programado' if scheduled_date else 'En Tratamiento',
                        **hierarchy,
                    )
                    db.session.add(notice)
                    db.session.flush()
                    notice.code = f"AV-{notice.id:04d}"

                wo = WorkOrder(
                    notice_id=notice.id if notice else None,
                    description=desc,
                    maintenance_type=tpl.maintenance_type or 'Correctivo',
                    failure_mode=tpl.failure_mode,
                    status=status,
                    scheduled_date=scheduled_date,
                    estimated_duration=tpl.estimated_duration,
                    tech_count=tpl.tech_count or 1,
                    **hierarchy,
                )
                db.session.add(wo)
                db.session.flush()
                wo.code = f"OT-{wo.id:04d}"
                if notice:
                    notice.ot_number = wo.code

                # Personal previsto (sin nombre: el planificador lo asigna)
                if tpl.specialty:
                    for _ in range(tpl.tech_count or 1):
                        db.session.add(OTPersonnel(
                            work_order_id=wo.id,
                            technician_id=None,
                            specialty=tpl.specialty,
                            hours_assigned=tpl.estimated_duration or 0,
                        ))

                # Agregar un repuesto de almacen a la OT descuenta stock; al
                # planificar solo se dejan anotados en la bitacora.
                comment = f"OT generada desde el trabajo estandar \"{tpl.name}\"."
                if material_lines:
                    comment += "\nMateriales previstos:\n" + "\n".join(material_lines)
                db.session.add(OTLogEntry(
                    work_order_id=wo.id,
                    log_date=today,
                    log_type='MATERIAL' if material_lines else 'NOTA',
                    author=user_name,
                    comment=comment,
                ))

                created.append({'id': wo.id, 'code': wo.code, 'description': desc,
                                'equipment_tag': eq.tag,
                                'notice_code': notice.code if notice else None})
                if notice:
                    notices_created.append(notice.id)

            tpl.use_count = (tpl.use_count or 0) + len(created)
            tpl.last_used_at = datetime.utcnow()
            db.session.commit()
        except _BadTarget as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.exception('work template generate error')
            return jsonify({"error": str(e)}), 500

        # Indexar los avisos nuevos para la busqueda semantica (como /api/notices)
        for nid in notices_created:
            try:
                from bot.telegram_bot import _index_entity_async
                _index_entity_async(app, 'notice', nid)
            except Exception as _ei:
                logger.warning(f"RAG index aviso {nid} fallo: {_ei}")

        return jsonify({'ok': True, 'created': created, 'created_count': len(created)}), 201
