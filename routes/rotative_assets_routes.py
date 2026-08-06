import datetime as dt
import re
import unicodedata

from flask import jsonify, request
from sqlalchemy import or_, text

# ── Estados y destinos de un activo rotativo ────────────────────────────────
# Un rotativo se retira de un equipo por una de estas razones, y cada una
# deja el activo en un estado distinto:
#   TALLER     -> se rompio, va al taller interno            -> 'En Taller'
#   PROVEEDOR  -> se manda a un tercero para su mantenimiento -> 'En Proveedor'
#   BAJA       -> ya no sirve, se descarta                    -> 'Baja'
#   STANDBY    -> sale operativo, queda listo para reinstalar -> 'Disponible'
REMOVAL_DESTINATIONS = {
    'TALLER': 'En Taller',
    'PROVEEDOR': 'En Proveedor',
    'BAJA': 'Baja',
    'STANDBY': 'Disponible',
    'DISPONIBLE': 'Disponible',
}
DESTINATION_LABELS = {
    'TALLER': 'Taller interno',
    'PROVEEDOR': 'Proveedor externo',
    'BAJA': 'Baja definitiva',
    'STANDBY': 'Disponible (stand-by)',
    'DISPONIBLE': 'Disponible (stand-by)',
}
# Estados desde los que el activo puede volver a montarse en un equipo.
INSTALLABLE_STATUSES = ('Disponible',)
# Estados de un activo que esta fuera de servicio pero volvera.
IN_SERVICE_STATUSES = ('En Taller', 'En Proveedor')


def _strip_accents(value):
    return ''.join(
        c for c in unicodedata.normalize('NFD', value)
        if unicodedata.category(c) != 'Mn'
    )


def _norm_text(value):
    """Normaliza texto para comparar: sin tildes, mayusculas, espacios simples."""
    if not value:
        return ''
    return re.sub(r'\s+', ' ', _strip_accents(str(value)).upper()).strip()


# Familias de activos intercambiables entre si. Un motorreductor no reemplaza
# a una caja reductora aunque ambos reduzcan: el motorreductor trae su propio
# motor. Por eso cada familia es cerrada.
CATEGORY_FAMILIES = {
    'MOTOR': ('MOTOR', 'MOTOR ELECTRICO', 'MOTOR ASINCRONO', 'MOTOR TRIFASICO'),
    'MOTORREDUCTOR': ('MOTORREDUCTOR', 'MOTOREDUCTOR', 'MOTO REDUCTOR', 'MOTORREDUCTORES'),
    'REDUCTOR': ('CAJA REDUCTORA', 'REDUCTOR', 'CAJA DE ENGRANAJES', 'REDUCTORA'),
    'BOMBA': ('BOMBA', 'BOMBA CENTRIFUGA', 'ELECTROBOMBA', 'BOMBA DE TORNILLO', 'BOMBA DOSIFICADORA'),
    'VENTILADOR': ('VENTILADOR', 'SOPLADOR', 'BLOWER', 'EXTRACTOR'),
    'COMPRESOR': ('COMPRESOR', 'COMPRESORA'),
    'HIDROLAVADORA': ('HIDROLAVADORA', 'HIDROLAVADORAS'),
}


def _category_family(category):
    """Familia de intercambio de una categoria. None si no se reconoce."""
    norm = _norm_text(category)
    if not norm:
        return None
    for family, aliases in CATEGORY_FAMILIES.items():
        if norm in aliases:
            return family
    # Coincidencia parcial: 'MOTORREDUCTOR TH1', 'BOMBA CENTRIFUGA 3HP', etc.
    # MOTORREDUCTOR primero: contiene 'MOTOR' y 'REDUCTOR' como subcadenas.
    for family in ('MOTORREDUCTOR', 'REDUCTOR', 'MOTOR', 'BOMBA',
                   'VENTILADOR', 'COMPRESOR', 'HIDROLAVADORA'):
        for alias in CATEGORY_FAMILIES[family]:
            if alias in norm:
                return family
    return None


def _spec_number(value_text):
    """Primer numero contenido en el texto de una caracteristica (o None)."""
    if value_text is None:
        return None
    match = re.search(r'-?\d+(?:[.,]\d+)?', str(value_text).replace(' ', ''))
    if not match:
        return None
    try:
        return float(match.group(0).replace(',', '.'))
    except ValueError:
        return None


# Caracteristicas que deciden si dos activos son intercambiables, y con que
# tolerancia. rel = tolerancia relativa (0.10 = +-10%); None = comparacion textual.
COMPARABLE_SPECS = [
    ('potencia',   ('POTENCIA NOMINAL', 'POTENCIA ENTRADA', 'POTENCIA', 'POTENCIA QUE ADMITE'), 0.10, 8),
    ('reduccion',  ('RELACION DE REDUCCION (I)', 'RELACION DE REDUCCION', 'RELACION'), 0.02, 10),
    ('rpm_salida', ('RPM SALIDA', 'VELOCIDAD SALIDA'), 0.10, 8),
    ('rpm',        ('VELOCIDAD NOMINAL', 'RPM', 'RPM ENTRADA'), 0.10, 5),
    ('voltaje',    ('VOLTAJE NOMINAL', 'VOLTAJE MOTOR', 'VOLTAJE'), 0.05, 5),
    ('torque',     ('TORQUE SALIDA NOMINAL', 'TORQUE'), 0.10, 5),
    ('eje_salida', ('DIAMETRO EJE SALIDA', 'DIAMETRO DE EJE SALIDA'), 0.02, 6),
    ('montaje',    ('FORMA DE MONTAJE',), None, 5),
]


def register_rotative_assets_routes(
    app,
    db,
    RotativeAsset,
    RotativeAssetHistory,
    RotativeAssetSpec,
    RotativeAssetBOM=None,
    WarehouseItem=None,
    WorkOrder=None,
    LubricationExecution=None,
    LubricationPoint=None,
):
    # _generate_rotative_code removed — code assigned after flush

    def _is_postgres():
        try:
            bind = db.session.get_bind()
            return bool(bind and bind.dialect and bind.dialect.name == 'postgresql')
        except Exception:
            return False

    def _repair_history_sequence_if_needed():
        if not _is_postgres():
            return
        db.session.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence('rotative_asset_history','id'),
                    COALESCE((SELECT MAX(id) FROM rotative_asset_history), 0) + 1,
                    false
                )
                """
            )
        )

    def _record_history(asset, event_type, event_date=None, comments=None):
        _repair_history_sequence_if_needed()
        db.session.add(
            RotativeAssetHistory(
                asset_id=asset.id,
                event_type=event_type,
                event_date=event_date or dt.date.today().isoformat(),
                comments=comments,
                area_id=asset.area_id,
                line_id=asset.line_id,
                equipment_id=asset.equipment_id,
                system_id=asset.system_id,
                component_id=asset.component_id,
            )
        )

    def _specs_map(asset_ids):
        """{asset_id: {KEY_NORMALIZADA: valor_texto}} para una lista de activos."""
        result = {aid: {} for aid in asset_ids}
        if not asset_ids:
            return result
        rows = RotativeAssetSpec.query.filter(
            RotativeAssetSpec.asset_id.in_(asset_ids),
            RotativeAssetSpec.is_active == True,  # noqa: E712
        ).all()
        for s in rows:
            value = (s.value_text or '').strip()
            # '—' es el placeholder que dejan las plantillas de ficha tecnica
            # sin completar: no aporta nada para comparar.
            if not value or value in ('—', '-', 'N/A'):
                continue
            result.setdefault(s.asset_id, {})[_norm_text(s.key_name)] = value
        return result

    def _pick_spec(spec_dict, aliases):
        for alias in aliases:
            if alias in spec_dict:
                return spec_dict[alias]
        # Coincidencia parcial (la ficha puede decir 'POTENCIA NOMINAL MOTOR')
        for alias in aliases:
            for key, value in spec_dict.items():
                if alias in key:
                    return value
        return None

    def _score_candidate(target, target_specs, cand, cand_specs):
        """Puntua que tan buen reemplazo es `cand` para `target`.

        Devuelve (score 0-100, nivel, razones, advertencias). El peso fuerte
        esta en la categoria: un motor no reemplaza a una caja reductora.
        """
        reasons, warnings = [], []
        score = 0

        t_family = _category_family(target.category)
        c_family = _category_family(cand.category)
        same_category = _norm_text(target.category) == _norm_text(cand.category)
        if t_family and c_family and t_family == c_family:
            score += 45
            reasons.append(
                f"Mismo tipo: {_norm_text(cand.category) or c_family}"
                if same_category else
                f"Tipo compatible ({c_family}): {cand.category or '-'}"
            )
        elif same_category and _norm_text(target.category):
            score += 45
            reasons.append(f"Mismo tipo: {_norm_text(cand.category)}")
        else:
            warnings.append(
                f"Tipo distinto: el instalado es {target.category or 'sin categoria'} "
                f"y este es {cand.category or 'sin categoria'}"
            )

        if target.brand and cand.brand and _norm_text(target.brand) == _norm_text(cand.brand):
            score += 10
            reasons.append(f"Misma marca: {cand.brand}")
        if target.model and cand.model and _norm_text(target.model) == _norm_text(cand.model):
            score += 15
            reasons.append(f"Mismo modelo: {cand.model}")

        # Datos de placa del motor que viven en el propio activo
        if target.rated_hp and cand.rated_hp:
            if abs(target.rated_hp - cand.rated_hp) <= max(target.rated_hp * 0.10, 0.01):
                score += 8
                reasons.append(f"Misma potencia de placa: {cand.rated_hp} HP")
            else:
                warnings.append(
                    f"Potencia de placa distinta: instalado {target.rated_hp} HP "
                    f"vs este {cand.rated_hp} HP"
                )

        compared_any = False
        for _key, aliases, tolerance, weight in COMPARABLE_SPECS:
            t_val = _pick_spec(target_specs, aliases)
            c_val = _pick_spec(cand_specs, aliases)
            if not t_val or not c_val:
                continue
            label = aliases[0].capitalize()
            if tolerance is None:
                compared_any = True
                if _norm_text(t_val) == _norm_text(c_val):
                    score += weight
                    reasons.append(f"{label}: {c_val}")
                else:
                    warnings.append(f"{label} distinta: {t_val} vs {c_val}")
                continue
            t_num, c_num = _spec_number(t_val), _spec_number(c_val)
            if t_num is None or c_num is None:
                continue
            compared_any = True
            if abs(t_num - c_num) <= max(abs(t_num) * tolerance, 1e-6):
                score += weight
                reasons.append(f"{label}: {c_val}")
            else:
                warnings.append(f"{label} distinta: {t_val} vs {c_val}")

        if not compared_any:
            warnings.append(
                "Sin ficha tecnica comparable — verifique potencia, reduccion "
                "y montaje antes de instalar"
            )

        score = max(0, min(100, score))
        if score >= 65 and not any('Tipo distinto' in w for w in warnings):
            level = 'ALTA'
        elif score >= 40:
            level = 'MEDIA'
        else:
            level = 'BAJA'
        return score, level, reasons, warnings

    def _candidate_payload(target, target_specs, cand, cand_specs):
        score, level, reasons, warnings = _score_candidate(
            target, target_specs, cand, cand_specs.get(cand.id, {}))
        return {
            'id': cand.id,
            'code': cand.code,
            'name': cand.name,
            'category': cand.category,
            'brand': cand.brand,
            'model': cand.model,
            'serial_number': cand.serial_number,
            'status': cand.status,
            'location': ' / '.join(filter(None, [
                cand.area.name if cand.area else None,
                cand.line.name if cand.line else None,
                cand.equipment.name if cand.equipment else None,
            ])) or None,
            'out_since': cand.out_since,
            'out_reason': cand.out_reason,
            'expected_return_date': cand.expected_return_date,
            'service_provider_name': cand.service_provider.name if cand.service_provider else None,
            'score': score,
            'match_level': level,
            'reasons': reasons,
            'warnings': warnings,
        }

    def _apply_removal(asset, destination, event_date, reason=None, comments=None,
                       provider_id=None, expected_return_date=None, extra_note=None):
        """Retira el activo del equipo y lo deja en el estado del destino.

        Centraliza lo que antes hacian por separado /remove y /swap: limpiar la
        ubicacion y la fecha de instalacion, fijar el estado segun a donde va
        (taller, proveedor, baja o stand-by) y dejar la trazabilidad de por que
        salio y cuando se espera de vuelta.
        """
        destination = (destination or 'STANDBY').upper()
        new_status = REMOVAL_DESTINATIONS.get(destination)
        if not new_status:
            raise ValueError(
                f"Destino '{destination}' no valido. Use: "
                + ', '.join(sorted(REMOVAL_DESTINATIONS))
            )

        provider_name = None
        if destination == 'PROVEEDOR':
            if not provider_id:
                raise ValueError("Indique el proveedor externo al que se envia el activo.")
            from models import Provider
            provider = Provider.query.get(provider_id)
            if not provider:
                raise ValueError("Proveedor no encontrado.")
            provider_name = provider.name

        origin = ' / '.join(filter(None, [
            asset.area.name if asset.area else None,
            asset.line.name if asset.line else None,
            asset.equipment.name if asset.equipment else None,
            asset.component.name if asset.component else None,
        ]))

        detail = [f"Destino: {DESTINATION_LABELS.get(destination, new_status)}"]
        if origin:
            detail.append(f"Retirado de: {origin}")
        if reason:
            detail.append(f"Motivo: {reason}")
        if provider_name:
            detail.append(f"Proveedor: {provider_name}")
        if destination in ('TALLER', 'PROVEEDOR') and expected_return_date:
            detail.append(f"Retorno estimado: {expected_return_date}")
        if extra_note:
            detail.append(extra_note)
        if comments:
            detail.append(comments)

        # El historial se graba ANTES de limpiar la ubicacion para que el
        # evento quede anclado al equipo del que realmente salio.
        _record_history(asset, 'RETIRO', event_date=event_date,
                        comments=' | '.join(detail))

        asset.status = new_status
        asset.area_id = None
        asset.line_id = None
        asset.equipment_id = None
        asset.system_id = None
        asset.component_id = None
        asset.install_date = None

        if destination in ('TALLER', 'PROVEEDOR', 'BAJA'):
            asset.out_since = event_date
            asset.out_reason = reason or comments
            asset.service_provider_id = provider_id if destination == 'PROVEEDOR' else None
            asset.expected_return_date = (
                expected_return_date if destination in ('TALLER', 'PROVEEDOR') else None
            )
        else:
            # Sale operativo: no arrastra motivo de falla ni proveedor.
            asset.out_since = None
            asset.out_reason = None
            asset.service_provider_id = None
            asset.expected_return_date = None

        return new_status

    @app.route('/api/rotative-assets/predictive-tracking', methods=['GET'])
    def rotative_predictive_tracking():
        """Seguimiento de medidas predictivas por activo rotativo.

        Cubre motores electricos, bombas, motorreductores y cajas reductoras:
        - Megado y ruta mensual corriente/temperatura (si is_electric_motor,
          programacion que ya vive en el propio RotativeAsset).
        - Puntos de monitoreo (vibracion, temperatura, etc.) vinculados por
          rotative_asset_id o, en su defecto, por el equipo+componente donde
          esta instalado.
        Devuelve semaforo global por activo (peor estado de sus medidas).
        """
        try:
            from models import MonitoringPoint
            from utils.schedule_helpers import _calculate_monitoring_schedule

            CATS = ('MOTOR', 'BOMBA', 'MOTORREDUCTOR', 'CAJA REDUCTORA', 'REDUCTOR')
            assets = RotativeAsset.query.filter(RotativeAsset.is_active == True).all()  # noqa: E712
            assets = [a for a in assets
                      if getattr(a, 'is_electric_motor', False)
                      or any(c in (a.category or '').strip().upper() for c in CATS)]

            # Puntos de monitoreo activos, indexados por rotativo y por equipo/comp
            points = MonitoringPoint.query.filter_by(is_active=True).all()
            by_asset, by_eq_comp, by_eq = {}, {}, {}
            for p in points:
                if getattr(p, 'rotative_asset_id', None):
                    by_asset.setdefault(p.rotative_asset_id, []).append(p)
                if p.equipment_id and p.component_id:
                    by_eq_comp.setdefault((p.equipment_id, p.component_id), []).append(p)
                elif p.equipment_id:
                    by_eq.setdefault(p.equipment_id, []).append(p)

            SEV = {'ROJO': 3, 'AMARILLO': 2, 'PENDIENTE': 1, 'VERDE': 0}
            rows = []
            summary = {'total': 0, 'rojo': 0, 'amarillo': 0, 'verde': 0, 'pendiente': 0, 'sin_medidas': 0}
            for a in assets:
                measures = []
                if getattr(a, 'is_electric_motor', False):
                    _, meg_status = _calculate_monitoring_schedule(
                        a.last_megado_date, a.megado_frequency_days or 180,
                        a.megado_warning_days or 14)
                    measures.append({
                        'tipo': 'MEGADO', 'status': meg_status,
                        'last': a.last_megado_date, 'next': a.next_megado_due,
                        'freq_days': a.megado_frequency_days or 180,
                    })
                    _, mes_status = _calculate_monitoring_schedule(
                        a.last_measure_date, a.measure_frequency_days or 30,
                        a.measure_warning_days or 5)
                    measures.append({
                        'tipo': 'CORRIENTE/TEMP', 'status': mes_status,
                        'last': a.last_measure_date, 'next': a.next_measure_due,
                        'freq_days': a.measure_frequency_days or 30,
                    })

                pts = list(by_asset.get(a.id, []))
                if not pts and a.equipment_id:
                    if a.component_id:
                        pts = by_eq_comp.get((a.equipment_id, a.component_id), [])
                    else:
                        pts = by_eq.get(a.equipment_id, [])
                for p in pts:
                    _, p_status = _calculate_monitoring_schedule(
                        p.last_measurement_date, p.frequency_days or 7, p.warning_days or 1)
                    measures.append({
                        'tipo': (p.measurement_type or 'MONITOREO').upper(),
                        'status': p_status, 'last': p.last_measurement_date,
                        'next': p.next_due_date, 'freq_days': p.frequency_days,
                        'point_code': p.code, 'point_id': p.id,
                    })

                overall = None
                if measures:
                    overall = max((m['status'] or 'PENDIENTE' for m in measures),
                                  key=lambda s: SEV.get(s, 1))
                rows.append({
                    'id': a.id, 'code': a.code, 'name': a.name,
                    'category': (a.category or '-').upper(),
                    'status': a.status,
                    'equipment_id': a.equipment_id,
                    'is_electric_motor': bool(getattr(a, 'is_electric_motor', False)),
                    'measures': measures,
                    'overall': overall,   # None = sin medidas configuradas
                })
                summary['total'] += 1
                if overall is None:
                    summary['sin_medidas'] += 1
                else:
                    summary[overall.lower() if overall.lower() in ('rojo', 'amarillo', 'verde') else 'pendiente'] += 1

            # Peor estado primero; sin medidas al final (son el hueco a cerrar)
            rows.sort(key=lambda r: -(SEV.get(r['overall'], -1) if r['overall'] else -1))
            return jsonify({'summary': summary, 'assets': rows})
        except Exception as e:
            app.logger.exception('predictive-tracking error')
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets', methods=['GET', 'POST'])
    def handle_rotative_assets():
        if request.method == 'POST':
            try:
                data = request.json or {}
                if not (data.get('name') or '').strip():
                    return jsonify({"error": "name es obligatorio"}), 400

                asset = RotativeAsset(
                    code=data.get('code') or 'MR-TEMP',
                    name=data.get('name').strip(),
                    category=data.get('category'),
                    brand=data.get('brand'),
                    model=data.get('model'),
                    serial_number=data.get('serial_number'),
                    status=data.get('status') or 'Disponible',
                    install_date=data.get('install_date'),
                    notes=data.get('notes'),
                    is_active=bool(data.get('is_active', True)),
                    area_id=data.get('area_id'),
                    line_id=data.get('line_id'),
                    equipment_id=data.get('equipment_id'),
                    system_id=data.get('system_id'),
                    component_id=data.get('component_id'),
                )
                db.session.add(asset)
                db.session.flush()
                if asset.code == 'MR-TEMP':
                    asset.code = f"MR-{asset.id:04d}"

                _record_history(asset, 'CREACION', comments='Activo rotativo creado')
                db.session.commit()
                return jsonify(asset.to_dict()), 201
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        show_all = request.args.get('all', 'false').lower() == 'true'
        area_id = request.args.get('area_id', type=int)
        line_id = request.args.get('line_id', type=int)
        equipment_id = request.args.get('equipment_id', type=int)
        component_id = request.args.get('component_id', type=int)
        status = request.args.get('status')

        query = RotativeAsset.query
        if not show_all:
            query = query.filter_by(is_active=True)
        if area_id:
            query = query.filter_by(area_id=area_id)
        if line_id:
            query = query.filter_by(line_id=line_id)
        if equipment_id:
            query = query.filter_by(equipment_id=equipment_id)
        if component_id:
            query = query.filter_by(component_id=component_id)
        if status:
            query = query.filter_by(status=status)

        rows = query.order_by(RotativeAsset.id.desc()).all()
        return jsonify([r.to_dict() for r in rows])

    @app.route('/api/rotative-assets/<int:asset_id>', methods=['GET', 'PUT', 'DELETE'])
    def handle_rotative_asset_id(asset_id):
        asset = RotativeAsset.query.get_or_404(asset_id)
        if request.method == 'GET':
            return jsonify(asset.to_dict())

        if request.method == 'DELETE':
            try:
                asset.is_active = not asset.is_active
                _record_history(asset, 'CAMBIO_ACTIVO', comments='Toggle activo/inactivo')
                db.session.commit()
                return jsonify({"message": "Estado actualizado"})
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500

        try:
            data = request.json or {}
            location_before = (asset.area_id, asset.line_id, asset.equipment_id, asset.system_id, asset.component_id)
            status_before = asset.status
            for field in [
                'code', 'name', 'category', 'brand', 'model', 'serial_number',
                'status', 'install_date', 'notes', 'is_active',
                'area_id', 'line_id', 'equipment_id', 'system_id', 'component_id',
            ]:
                if field in data:
                    setattr(asset, field, data[field])
            location_after = (asset.area_id, asset.line_id, asset.equipment_id, asset.system_id, asset.component_id)
            if location_before != location_after or status_before != asset.status:
                _record_history(asset, 'ACTUALIZACION', comments='Actualizacion de datos/ubicacion')
            db.session.commit()
            return jsonify(asset.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets/<int:asset_id>/install', methods=['POST'])
    def install_rotative_asset(asset_id):
        asset = RotativeAsset.query.get_or_404(asset_id)
        try:
            data = request.json or {}
            event_date = data.get('event_date') or dt.date.today().isoformat()
            if asset.status == 'Baja' and not data.get('force'):
                return jsonify({
                    "error": f"{asset.code} esta dado de Baja. Cambie su estado antes de instalarlo."
                }), 400
            asset.status = 'Instalado'
            asset.install_date = event_date
            asset.area_id = data.get('area_id')
            asset.line_id = data.get('line_id')
            asset.equipment_id = data.get('equipment_id')
            asset.system_id = data.get('system_id')
            asset.component_id = data.get('component_id')
            # Ya esta montado: deja de estar fuera de servicio.
            asset.out_since = None
            asset.out_reason = None
            asset.service_provider_id = None
            asset.expected_return_date = None

            _record_history(asset, 'INSTALACION', event_date=event_date, comments=data.get('comments'))
            db.session.commit()
            return jsonify(asset.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets/<int:asset_id>/remove', methods=['POST'])
    def remove_rotative_asset(asset_id):
        """Desinstala un activo y lo manda a taller, proveedor, baja o stand-by."""
        asset = RotativeAsset.query.get_or_404(asset_id)
        try:
            data = request.json or {}
            event_date = data.get('event_date') or dt.date.today().isoformat()

            destination = data.get('destination')
            if not destination:
                # Compatibilidad con el flujo anterior, que solo mandaba el
                # estado destino en new_status.
                legacy = _norm_text(data.get('new_status') or 'Disponible')
                destination = {
                    'EN TALLER': 'TALLER',
                    'EN PROVEEDOR': 'PROVEEDOR',
                    'BAJA': 'BAJA',
                }.get(legacy, 'STANDBY')

            _apply_removal(
                asset,
                destination=destination,
                event_date=event_date,
                reason=data.get('reason'),
                comments=data.get('comments'),
                provider_id=data.get('provider_id'),
                expected_return_date=data.get('expected_return_date'),
            )
            db.session.commit()
            return jsonify(asset.to_dict())
        except ValueError as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets/<int:asset_id>/return-to-service', methods=['POST'])
    def return_rotative_asset_to_service(asset_id):
        """Recibe de vuelta un activo que estaba en taller o en un proveedor.

        Queda Disponible (listo para instalar) o de Baja si el diagnostico fue
        que ya no sirve. Limpia la trazabilidad de fuera de servicio.
        """
        asset = RotativeAsset.query.get_or_404(asset_id)
        try:
            data = request.json or {}
            event_date = data.get('event_date') or dt.date.today().isoformat()
            new_status = data.get('new_status') or 'Disponible'
            if new_status not in ('Disponible', 'Baja'):
                return jsonify({"error": "El retorno solo puede dejar el activo Disponible o de Baja."}), 400

            was = asset.status
            detail = [f"Retorno de {was}", f"Nuevo estado: {new_status}"]
            if asset.service_provider:
                detail.append(f"Proveedor: {asset.service_provider.name}")
            if asset.out_since:
                detail.append(f"Fuera de servicio desde: {asset.out_since}")
            if data.get('work_done'):
                detail.append(f"Trabajo realizado: {data['work_done']}")
            if data.get('comments'):
                detail.append(data['comments'])

            _record_history(asset, 'RETORNO_SERVICIO', event_date=event_date,
                            comments=' | '.join(detail))

            asset.status = new_status
            asset.out_since = None if new_status == 'Disponible' else asset.out_since
            asset.out_reason = None if new_status == 'Disponible' else asset.out_reason
            asset.service_provider_id = None
            asset.expected_return_date = None
            db.session.commit()
            return jsonify(asset.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets/<int:asset_id>/history', methods=['GET'])
    def get_rotative_asset_history(asset_id):
        RotativeAsset.query.get_or_404(asset_id)
        rows = RotativeAssetHistory.query.filter_by(asset_id=asset_id).order_by(RotativeAssetHistory.id.desc()).all()
        return jsonify([r.to_dict() for r in rows])

    @app.route('/api/rotative-assets/<int:asset_id>/specs', methods=['GET', 'POST'])
    def handle_rotative_specs(asset_id):
        asset = RotativeAsset.query.get_or_404(asset_id)

        if request.method == 'GET':
            rows = RotativeAssetSpec.query.filter_by(asset_id=asset_id, is_active=True).order_by(RotativeAssetSpec.order_index.asc(), RotativeAssetSpec.id.asc()).all()
            return jsonify([r.to_dict() for r in rows])

        try:
            data = request.json or {}
            key_name = (data.get('key_name') or '').strip()
            value_text = (data.get('value_text') or '').strip()
            unit = (data.get('unit') or '').strip() or None
            order_index = data.get('order_index')
            try:
                order_index = int(order_index) if order_index is not None else 0
            except Exception:
                order_index = 0

            if not key_name or not value_text:
                return jsonify({"error": "key_name y value_text son obligatorios"}), 400

            spec = None
            spec_id = data.get('id')
            if spec_id:
                spec = RotativeAssetSpec.query.filter_by(id=spec_id, asset_id=asset_id).first()

            if spec is None:
                spec = RotativeAssetSpec.query.filter_by(asset_id=asset_id, key_name=key_name, unit=unit, is_active=True).first()

            if spec:
                spec.value_text = value_text
                spec.order_index = order_index
                spec.is_active = True
                event_label = 'FICHA_ACTUALIZADA'
            else:
                spec = RotativeAssetSpec(
                    asset_id=asset_id,
                    key_name=key_name,
                    value_text=value_text,
                    unit=unit,
                    order_index=order_index,
                    is_active=True,
                )
                db.session.add(spec)
                event_label = 'FICHA_AGREGADA'

            _record_history(asset, event_label, comments=f'{key_name}={value_text}{(" " + unit) if unit else ""}')
            db.session.commit()
            return jsonify(spec.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @app.route('/api/rotative-assets/specs/<int:spec_id>', methods=['DELETE'])
    def delete_rotative_spec(spec_id):
        spec = RotativeAssetSpec.query.get_or_404(spec_id)
        try:
            spec.is_active = False
            asset = RotativeAsset.query.get(spec.asset_id)
            if asset:
                _record_history(asset, 'FICHA_ELIMINADA', comments=f'{spec.key_name} eliminado')
            db.session.commit()
            return jsonify({"message": "Caracteristica eliminada"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    # ── BOM (Bill of Materials) ────────────────────────────────────────────

    @app.route('/api/rotative-assets/<int:asset_id>/bom', methods=['GET', 'POST'])
    def handle_asset_bom(asset_id):
        RotativeAsset.query.get_or_404(asset_id)

        from sqlalchemy import text as sql_text

        # Ensure free_text column exists
        try:
            db.session.execute(sql_text("ALTER TABLE rotative_asset_bom ADD COLUMN free_text VARCHAR(200)"))
            db.session.execute(sql_text("ALTER TABLE rotative_asset_bom ALTER COLUMN warehouse_item_id DROP NOT NULL"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        if request.method == 'POST':
            try:
                data = request.json or {}
                wi_id = data.get('warehouse_item_id') or None
                free_text = (data.get('free_text') or '').strip().upper() or None

                if not wi_id and not free_text:
                    return jsonify({"error": "Seleccione un repuesto o escriba el nombre."}), 400

                category = (data.get('category') or 'MECANICO').upper()
                quantity = float(data.get('quantity') or 1)
                notes = data.get('notes') or None

                db.session.execute(sql_text("""
                    INSERT INTO rotative_asset_bom (asset_id, warehouse_item_id, free_text, category, quantity, notes)
                    VALUES (:aid, :wid, :ft, :cat, :qty, :notes)
                """), {"aid": asset_id, "wid": int(wi_id) if wi_id else None, "ft": free_text, "cat": category, "qty": quantity, "notes": notes})
                db.session.commit()
                return jsonify({"ok": True}), 201
            except Exception as exc:
                db.session.rollback()
                return jsonify({"error": str(exc)}), 500

        # GET
        try:
            rows = db.session.execute(sql_text("""
                SELECT b.id, b.asset_id, b.warehouse_item_id, b.free_text, b.category, b.quantity, b.notes,
                       w.code, w.name, w.stock, w.unit
                FROM rotative_asset_bom b
                LEFT JOIN warehouse_items w ON b.warehouse_item_id = w.id
                WHERE b.asset_id = :aid
            """), {"aid": asset_id}).fetchall()
            result = []
            for r in rows:
                result.append({
                    "id": r[0], "asset_id": r[1], "warehouse_item_id": r[2],
                    "free_text": r[3], "item_code": r[7],
                    "item_name": r[8] if r[8] else (r[3] or '-'),
                    "item_stock": r[9], "item_unit": r[10],
                    "category": r[4], "quantity": r[5], "notes": r[6],
                    "is_linked": r[2] is not None,
                })
            return jsonify(result)
        except Exception as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 500

    @app.route('/api/rotative-assets/bom/<int:bom_id>', methods=['DELETE'])
    def delete_asset_bom(bom_id):
        if not RotativeAssetBOM:
            return jsonify({"error": "BOM no disponible"}), 500
        bom = RotativeAssetBOM.query.get_or_404(bom_id)
        db.session.delete(bom)
        db.session.commit()
        return jsonify({"ok": True})

    # ── Swap: Uninstall current + Install replacement ──────────────────────

    @app.route('/api/rotative-assets/<int:asset_id>/swap-candidates', methods=['GET'])
    def rotative_swap_candidates(asset_id):
        """Reemplazos posibles para un activo instalado, ordenados por afinidad.

        Consulta la base completa — NO la tabla ya filtrada de la pantalla —
        porque un repuesto disponible no tiene ubicacion y desapareceria en
        cuanto el usuario filtre por el equipo que fallo.

        Devuelve tres grupos:
          - candidates: estado Disponible, se pueden instalar ahora.
          - in_service: en taller o en un proveedor (llegan despues; se listan
            con su fecha estimada de retorno para decidir si vale la pena esperar).
          - discarded:  dados de Baja, solo informativos (canibalizar repuestos).
        """
        try:
            target = RotativeAsset.query.get_or_404(asset_id)

            others = RotativeAsset.query.filter(
                RotativeAsset.id != asset_id,
                RotativeAsset.is_active == True,  # noqa: E712
                RotativeAsset.status != 'Instalado',
            ).all()

            specs = _specs_map([asset_id] + [o.id for o in others])
            target_specs = specs.get(asset_id, {})

            groups = {'candidates': [], 'in_service': [], 'discarded': []}
            for cand in others:
                payload = _candidate_payload(target, target_specs, cand, specs)
                if cand.status in INSTALLABLE_STATUSES:
                    groups['candidates'].append(payload)
                elif cand.status in IN_SERVICE_STATUSES:
                    groups['in_service'].append(payload)
                else:
                    groups['discarded'].append(payload)

            for key in groups:
                groups[key].sort(key=lambda c: (-c['score'], c['code'] or ''))

            same_family = [c for c in groups['candidates']
                           if not any('Tipo distinto' in w for w in c['warnings'])]
            return jsonify({
                'target': target.to_dict(),
                'target_family': _category_family(target.category),
                'candidates': groups['candidates'],
                'in_service': groups['in_service'],
                'discarded': groups['discarded'],
                'summary': {
                    'disponibles': len(groups['candidates']),
                    'compatibles': len(same_family),
                    'en_servicio': len(groups['in_service']),
                    'de_baja': len(groups['discarded']),
                },
            })
        except Exception as exc:
            app.logger.exception('swap-candidates error')
            return jsonify({"error": str(exc)}), 500

    @app.route('/api/rotative-assets/swap', methods=['POST'])
    def swap_rotative_assets():
        """Cambia un activo instalado por otro en la misma ubicacion.

        El retirado va al destino indicado (taller, proveedor, baja o stand-by)
        y el nuevo hereda area/linea/equipo/sistema/componente del que salio.
        """
        try:
            data = request.json or {}
            remove_id = data.get('remove_asset_id')
            install_id = data.get('install_asset_id')
            if not remove_id or not install_id:
                return jsonify({"error": "Se requiere remove_asset_id e install_asset_id."}), 400
            if int(remove_id) == int(install_id):
                return jsonify({"error": "El reemplazo no puede ser el mismo activo."}), 400

            old_asset = RotativeAsset.query.get(remove_id)
            new_asset = RotativeAsset.query.get(install_id)
            if not old_asset or not new_asset:
                return jsonify({"error": "Activo no encontrado."}), 404
            if new_asset.status == 'Instalado':
                where = new_asset.equipment.name if new_asset.equipment else 'otro equipo'
                return jsonify({
                    "error": f"{new_asset.code} ya esta instalado en {where}. "
                             f"Retirelo de ahi antes de usarlo como reemplazo."
                }), 400
            if new_asset.status == 'Baja' and not data.get('force'):
                return jsonify({
                    "error": f"{new_asset.code} esta dado de Baja y no puede instalarse."
                }), 400
            if not new_asset.is_active:
                return jsonify({"error": f"{new_asset.code} esta inactivo en el maestro."}), 400

            location = {
                'area_id': old_asset.area_id, 'line_id': old_asset.line_id,
                'equipment_id': old_asset.equipment_id,
                'system_id': old_asset.system_id, 'component_id': old_asset.component_id,
            }
            swap_date = data.get('date') or data.get('event_date') or dt.date.today().isoformat()
            reason = data.get('reason') or 'Swap de activo'

            destination = data.get('destination')
            if not destination:
                legacy = _norm_text(data.get('old_status') or 'En Taller')
                destination = {
                    'EN TALLER': 'TALLER',
                    'EN PROVEEDOR': 'PROVEEDOR',
                    'BAJA': 'BAJA',
                }.get(legacy, 'STANDBY')

            _apply_removal(
                old_asset,
                destination=destination,
                event_date=swap_date,
                reason=reason,
                comments=data.get('comments'),
                provider_id=data.get('provider_id'),
                expected_return_date=data.get('expected_return_date'),
                extra_note=f"Reemplazado por {new_asset.code} {new_asset.name}",
            )

            for k, v in location.items():
                setattr(new_asset, k, v)
            new_asset.status = 'Instalado'
            new_asset.install_date = swap_date
            new_asset.out_since = None
            new_asset.out_reason = None
            new_asset.service_provider_id = None
            new_asset.expected_return_date = None
            _record_history(new_asset, 'INSTALACION', event_date=swap_date,
                            comments=f"Instalado por swap (reemplaza a {old_asset.code} "
                                     f"{old_asset.name}) | Motivo: {reason}")

            db.session.commit()
            return jsonify({
                'removed': old_asset.to_dict(),
                'installed': new_asset.to_dict(),
                'message': f"{new_asset.code} instalado en lugar de {old_asset.code}. "
                           f"{old_asset.code} quedo en estado {old_asset.status}.",
            })
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 500

    # ── Consolidated Asset History ─────────────────────────────────────────

    @app.route('/api/rotative-assets/<int:asset_id>/full-history', methods=['GET'])
    def get_asset_full_history(asset_id):
        """Historial consolidado del activo rotativo.

        Cada evento trae `scope`:
          - ACTIVO: le pasa al activo mismo (movimientos, OTs y avisos suyos,
            pruebas electricas, y solo los puntos de lubricacion/monitoreo que
            son del propio activo — el aceite del reductor, no la grasa de las
            chumaceras del equipo).
          - EQUIPO: pasa en el equipo donde esta montado. Las chumaceras, las
            fajas y las rondas de inspeccion son del sistema de transmision,
            no del motorreductor: son contexto, y el front las oculta salvo
            que el usuario las pida.
        """
        try:
            from models import (MaintenanceNotice, InspectionRoute, InspectionExecution,
                                MonitoringPoint, MonitoringReading, MotorElectricalTest)
            asset = RotativeAsset.query.get_or_404(asset_id)
            events = []
            asset_code = _norm_text(asset.code)

            def _belongs_to_asset(point):
                """True si el punto es del activo y no del equipo que lo aloja.

                Dos formas de vinculo: mismo componente que el activo, o el
                punto lleva el codigo del activo en su codigo/nombre (asi los
                creo scripts/bulk_create_lub_motors.py).
                """
                if getattr(point, 'rotative_asset_id', None) == asset.id:
                    return True
                if asset.component_id and point.component_id == asset.component_id:
                    return True
                if asset_code and (asset_code in _norm_text(point.code)
                                   or asset_code in _norm_text(point.name)):
                    return True
                return False

            # 1. Movimientos del propio rotativo
            for h in (asset.history or []):
                loc = ' / '.join(filter(None, [
                    h.area.name if h.area else None,
                    h.line.name if h.line else None,
                    h.equipment.name if h.equipment else None,
                ]))
                events.append({
                    'date': h.event_date or '',
                    'category': 'MOVIMIENTO',
                    'scope': 'ACTIVO',
                    'code': None,
                    'type': (h.event_type or '').replace('_', ' '),
                    'status': None,
                    'description': h.comments or '-',
                    'failure_mode': None,
                    'duration_h': None,
                    'source_type': None,
                    'location': loc,
                })

            # 2. OTs vinculadas directamente al rotativo
            if WorkOrder:
                ots = WorkOrder.query.filter_by(rotative_asset_id=asset_id).order_by(WorkOrder.id.desc()).all()
                for ot in ots:
                    events.append({
                        'date': ot.real_start_date or ot.scheduled_date or '',
                        'category': 'OT',
                        'scope': 'ACTIVO',
                        'code': ot.code,
                        'type': ot.maintenance_type,
                        'status': ot.status,
                        'description': ot.description,
                        'failure_mode': ot.failure_mode,
                        'duration_h': ot.real_duration,
                        'source_type': getattr(ot, 'source_type', None),
                    })

            # 3. Avisos vinculados al rotativo
            try:
                notices = MaintenanceNotice.query.filter(
                    (MaintenanceNotice.rotative_asset_id == asset_id) |
                    (MaintenanceNotice.rotable_asset_id == asset_id)
                ).order_by(MaintenanceNotice.id.desc()).all()
            except Exception:
                notices = MaintenanceNotice.query.filter_by(rotative_asset_id=asset_id).all()
            for n in notices:
                events.append({
                    'date': n.request_date or '',
                    'category': 'AVISO',
                    'scope': 'ACTIVO',
                    'code': n.code,
                    'type': n.maintenance_type,
                    'status': n.status,
                    'description': n.description,
                    'failure_mode': getattr(n, 'failure_mode', None),
                    'duration_h': None,
                    'source_type': getattr(n, 'source_type', None),
                })

            # 4. Pruebas electricas del propio activo (megado, corriente, temperatura).
            #    Siguen al motor aunque cambie de equipo: son suyas siempre.
            try:
                for t in MotorElectricalTest.query.filter_by(
                        rotative_asset_id=asset_id).order_by(MotorElectricalTest.id.desc()).all():
                    if t.test_type == 'MEGADO':
                        detail = f"Aislamiento minimo: {t.insulation_mohm} MΩ"
                        if t.test_voltage_v:
                            detail += f" @ {t.test_voltage_v} V"
                    elif t.test_type == 'CORRIENTE':
                        fases = [x for x in (t.current_r, t.current_s, t.current_t) if x is not None]
                        detail = "Corriente por fase: " + (' / '.join(f"{x} A" for x in fases) or '-')
                    else:
                        detail = f"Temperatura: {t.temperature_c} °C" + (f" en {t.temp_point}" if t.temp_point else '')
                    events.append({
                        'date': t.test_date or '',
                        'category': 'ELECTRICA',
                        'scope': 'ACTIVO',
                        'code': None,
                        'type': t.test_type,
                        'status': t.status,
                        'description': detail + (f" | {t.notes}" if t.notes else ''),
                        'failure_mode': None,
                        'duration_h': None,
                        'source_type': t.context,
                    })
            except Exception:
                # Instalaciones antiguas sin la tabla de pruebas electricas.
                pass

            # 5. Lubricacion y monitoreo: se separa lo que es del activo de lo
            #    que es del equipo que lo aloja. Las chumaceras, fajas y cadenas
            #    son del sistema de transmision — se etiquetan scope EQUIPO para
            #    que no se confundan con el mantenimiento del rotativo.
            install_date = (asset.install_date or '')[:10]

            def _after_install(d):
                if not d or not install_date:
                    return True
                return (d or '')[:10] >= install_date

            if LubricationExecution and LubricationPoint:
                # Puntos del equipo donde esta montado (contexto) + los del
                # propio componente del activo (suyos, aunque no este montado).
                lub_filters = []
                if asset.equipment_id:
                    lub_filters.append(LubricationPoint.equipment_id == asset.equipment_id)
                if asset.component_id:
                    lub_filters.append(LubricationPoint.component_id == asset.component_id)
                lub_points = (
                    LubricationPoint.query.filter(or_(*lub_filters)).all()
                    if lub_filters else []
                )
                by_id = {p.id: p for p in lub_points}
                if by_id:
                    for e in LubricationExecution.query.filter(
                            LubricationExecution.point_id.in_(list(by_id))
                    ).order_by(LubricationExecution.id.desc()).all():
                        pt = by_id.get(e.point_id)
                        own = pt is not None and _belongs_to_asset(pt)
                        # El contexto del equipo solo interesa desde que este
                        # activo esta montado ahi; lo suyo se muestra completo.
                        if not own and not _after_install(e.execution_date):
                            continue
                        events.append({
                            'date': e.execution_date or '',
                            'category': 'LUBRICACION',
                            'scope': 'ACTIVO' if own else 'EQUIPO',
                            'code': pt.code if pt else None,
                            'type': e.action_type,
                            'status': (('Fuga ' if e.leak_detected else '') + ('Anomalia' if e.anomaly_detected else '')).strip() or 'Normal',
                            'description': f"{pt.name if pt else ''}: {pt.lubricant_name if pt else ''} {e.quantity_used or ''} {e.quantity_unit or ''}".strip(),
                            'failure_mode': None,
                            'duration_h': None,
                            'source_type': None,
                        })

            if MonitoringPoint and MonitoringReading:
                mon_filters = [MonitoringPoint.rotative_asset_id == asset_id]
                if asset.equipment_id:
                    mon_filters.append(MonitoringPoint.equipment_id == asset.equipment_id)
                if asset.component_id:
                    mon_filters.append(MonitoringPoint.component_id == asset.component_id)
                mon_points = MonitoringPoint.query.filter(or_(*mon_filters)).all()
                mon_map = {p.id: p for p in mon_points}
                if mon_map:
                    for r in MonitoringReading.query.filter(
                        MonitoringReading.point_id.in_(list(mon_map))
                    ).order_by(MonitoringReading.id.desc()).limit(200).all():
                        pt = mon_map.get(r.point_id)
                        own = pt is not None and _belongs_to_asset(pt)
                        if not own and not _after_install(r.reading_date):
                            continue
                        events.append({
                            'date': r.reading_date or '',
                            'category': 'MONITOREO',
                            'scope': 'ACTIVO' if own else 'EQUIPO',
                            'code': pt.code if pt else None,
                            'type': pt.measurement_type if pt else None,
                            'status': f"{r.value} {pt.unit if pt else ''}".strip(),
                            'description': pt.name if pt else '',
                            'failure_mode': None,
                            'duration_h': None,
                            'source_type': None,
                        })

            # 6. Inspecciones: las rondas se definen por equipo, nunca por
            #    activo rotativo, asi que siempre son contexto del equipo.
            if asset.equipment_id and InspectionRoute and InspectionExecution:
                insp_routes = InspectionRoute.query.filter_by(equipment_id=asset.equipment_id).all()
                route_map = {r.id: r for r in insp_routes}
                if route_map:
                    for ex in InspectionExecution.query.filter(
                        InspectionExecution.route_id.in_(list(route_map))
                    ).order_by(InspectionExecution.id.desc()).all():
                        if not _after_install(ex.execution_date):
                            continue
                        rt = route_map.get(ex.route_id)
                        events.append({
                            'date': ex.execution_date or '',
                            'category': 'INSPECCION',
                            'scope': 'EQUIPO',
                            'code': rt.code if rt else None,
                            'type': ex.overall_result,
                            'status': f"{ex.findings_count} hallazgo(s)" if ex.findings_count else 'OK',
                            'description': rt.name if rt else '',
                            'failure_mode': None,
                            'duration_h': None,
                            'source_type': None,
                        })

            events.sort(key=lambda x: x.get('date') or '', reverse=True)
            own_events = [e for e in events if e.get('scope') != 'EQUIPO']
            env_events = [e for e in events if e.get('scope') == 'EQUIPO']
            # El historial del activo manda; el contexto del equipo va detras y
            # acotado para no desplazar lo propio del limite de 200.
            events = own_events[:200] + env_events[:100]

            bom_items = []
            if RotativeAssetBOM:
                bom_items = [b.to_dict() for b in RotativeAssetBOM.query.filter_by(asset_id=asset_id).all()]

            def _count(cat):
                return len([e for e in own_events if e['category'] == cat])

            return jsonify({
                'asset': asset.to_dict(),
                'events': events,
                'bom': bom_items,
                'counts': {
                    'movimientos': _count('MOVIMIENTO'),
                    'ots':          _count('OT'),
                    'avisos':       _count('AVISO'),
                    'electrica':    _count('ELECTRICA'),
                    'lubricacion':  _count('LUBRICACION'),
                    'inspeccion':   _count('INSPECCION'),
                    'monitoreo':    _count('MONITOREO'),
                    'entorno':      len(env_events[:100]),
                },
            })
        except Exception as exc:
            import traceback; traceback.print_exc()
            return jsonify({"error": str(exc)}), 500
