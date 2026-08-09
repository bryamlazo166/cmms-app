"""Diagnostico mensual de gestion de mantenimiento.

Pagina /diagnostico: informe ejecutivo con datos calculados EN VIVO desde la
BD (mismo formato siempre), narrativa generada con DeepSeek, modo presentacion
para gerencia, drill-down (Pareto/equipos -> OTs; confiabilidad por area via
/api/indicators/*), cuadro consolidado de 12 meses y programacion del resto
del mes en curso + mes siguiente para coordinar con produccion.
"""
import calendar
import datetime as dt
import math
from collections import defaultdict

from flask import jsonify, render_template, request

from utils.deepseek import DEEPSEEK_MODEL, DEEPSEEK_THINKING


def register_diagnostico_routes(app, db, logger):
    from models import (
        WorkOrder, Equipment, Line, ProductionGoal,
        LubricationPoint, InspectionRoute, MonitoringPoint,
        RotativeAsset, WarehouseItem, Technician, Shutdown,
    )

    SACK_KG = 50  # 1 saco de harina = 50 kg (igual que el modulo Produccion)

    # ── Helpers de fechas (todas las fechas son strings ISO) ─────────────

    def _prev_month(ym):
        y, m = int(ym[:4]), int(ym[5:7])
        return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"

    def _next_month(ym):
        y, m = int(ym[:4]), int(ym[5:7])
        return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"

    def _month_label(ym):
        MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                 'Julio', 'Agosto', 'Setiembre', 'Octubre', 'Noviembre', 'Diciembre']
        return f"{MESES[int(ym[5:7])]} {ym[:4]}"

    def _ot_close_month(ot):
        d = ot.real_end_date or ot.real_start_date or ot.scheduled_date
        return str(d)[:7] if d else None

    def _downtime(ot):
        if getattr(ot, 'caused_downtime', None):
            return float(ot.downtime_hours or ot.real_duration or 0)
        return 0.0

    def _mtype(ot):
        return (ot.maintenance_type or '').strip().lower()

    def _months_back(ym, n):
        out = []
        cur = ym
        for _ in range(n):
            out.append(cur)
            cur = _prev_month(cur)
        out.reverse()
        return out

    # ── Periodo analizado (mes completo o rango libre de fechas) ──────────
    # Todo el diagnostico se calcula sobre un periodo [ini, fin]. Por defecto
    # es un mes, pero el usuario puede pedir cualquier rango (?desde=&hasta=)
    # para analizar, por ejemplo, una campana o las ultimas 6 semanas.

    MESES_CORTO = ['', 'ene', 'feb', 'mar', 'abr', 'may', 'jun',
                   'jul', 'ago', 'set', 'oct', 'nov', 'dic']

    def _d(s):
        return dt.date.fromisoformat(str(s)[:10])

    def _fecha_corta(d):
        return f"{d.day:02d} {MESES_CORTO[d.month]} {d.year}"

    def _build_periodo(month, desde, hasta):
        """Normaliza lo que pidio el usuario a un periodo con todo lo que
        necesitan los calculos: limites, dias, etiqueta y periodo anterior
        comparable (mes anterior, o el mismo numero de dias hacia atras)."""
        hoy = dt.date.today()
        mes_actual = hoy.strftime('%Y-%m')

        if desde and hasta:
            try:
                ini, fin = _d(desde), _d(hasta)
            except Exception:
                ini = fin = None
            if ini and fin and ini <= fin:
                fin_real = min(fin, hoy)
                dias = (fin_real - ini).days + 1
                dias_nom = (fin - ini).days + 1
                prev_fin = ini - dt.timedelta(days=1)
                prev_ini = prev_fin - dt.timedelta(days=dias_nom - 1)
                return {
                    'modo': 'rango',
                    'ini': ini, 'fin': fin, 'fin_real': fin_real,
                    'dias': max(dias, 1), 'dias_nominales': dias_nom,
                    'en_curso': fin > hoy,
                    'label': f"{_fecha_corta(ini)} — {_fecha_corta(fin)}",
                    'month': fin.strftime('%Y-%m'),
                    'prev_ini': prev_ini, 'prev_fin': prev_fin,
                    'prev_label': f"{_fecha_corta(prev_ini)} — {_fecha_corta(prev_fin)}",
                    'hoy': hoy,
                }

        month = (month or mes_actual)[:7]
        y, m = int(month[:4]), int(month[5:7])
        dias_mes = calendar.monthrange(y, m)[1]
        ini = dt.date(y, m, 1)
        fin = dt.date(y, m, dias_mes)
        en_curso = (month == mes_actual)
        fin_real = min(fin, hoy) if en_curso else fin
        prev = _prev_month(month)
        py, pm = int(prev[:4]), int(prev[5:7])
        return {
            'modo': 'mes',
            'ini': ini, 'fin': fin, 'fin_real': fin_real,
            'dias': max((fin_real - ini).days + 1, 1), 'dias_nominales': dias_mes,
            'en_curso': en_curso,
            'label': _month_label(month),
            'month': month,
            'prev_ini': dt.date(py, pm, 1),
            'prev_fin': dt.date(py, pm, calendar.monthrange(py, pm)[1]),
            'prev_label': _month_label(prev),
            'hoy': hoy,
        }

    def _ot_date(ot):
        """Fecha con la que la OT entra al periodo: cierre real, inicio real
        o, en ultimo caso, la fecha programada."""
        d = ot.real_end_date or ot.real_start_date or ot.scheduled_date
        return str(d)[:10] if d else None

    def _in_range(ot, ini, fin):
        d = _ot_date(ot)
        return bool(d) and ini.isoformat() <= d <= fin.isoformat()

    def _paro_en_rango(ot, ini, fin):
        """Horas de parada de la OT que caen DENTRO de [ini, fin].

        Una parada larga que cruza meses (ej. el molino detenido del 23-abr al
        28-may) se reparte entre los dias que realmente cubrio. Antes se
        cargaban las 838 h completas al mes de cierre, y mayo heredaba las
        perdidas de abril."""
        h = _downtime(ot)
        if h <= 0:
            return 0.0
        s, e = ot.real_start_date, ot.real_end_date
        if not s or not e:
            return h if _in_range(ot, ini, fin) else 0.0
        try:
            ds, de = _d(s), _d(e)
        except Exception:
            return h if _in_range(ot, ini, fin) else 0.0
        if de < ds:
            ds, de = de, ds
        ov_ini, ov_fin = max(ds, ini), min(de, fin)
        if ov_fin < ov_ini:
            return 0.0
        dias_tot = (de - ds).days + 1
        dias_ov = (ov_fin - ov_ini).days + 1
        return h * dias_ov / dias_tot if dias_tot else h

    # ── Produccion: TM/h por area segun metas (modulo Produccion vs Mtto) ─

    def _goals_por_area():
        """{area_id: [(period, goal), ...] ordenado}."""
        out = {}
        for g in ProductionGoal.query.all():
            out.setdefault(g.area_id, []).append((g.goal_period, g))
        for k in out:
            out[k].sort(key=lambda x: x[0])
        return out

    def _goal_para(goals_area, ym):
        """Meta vigente para el mes: la ultima con period <= ym, o la primera."""
        if not goals_area:
            return None
        anteriores = [g for (p, g) in goals_area if p <= ym]
        return anteriores[-1] if anteriores else goals_area[0][1]

    # ── Capacidad real de planta (base de las TM no producidas) ───────────
    # ANTES: TM perdidas = horas de parada x (rendimiento mensual del AREA /
    # horas del mes). Eso valoraba la parada de UN digestor como si se hubiera
    # detenido el area entera, y ademas sumaba COCCION + SECADO + MOLINO, que
    # son la misma planta en serie: en julio daba 3 983 TM, mas de lo que la
    # planta produce en un mes.
    # AHORA: cada equipo aporta SU capacidad real (los digestores por llenadas
    # y % de llenado; el resto por sus TM/dia capturadas en Alcance de
    # Indicadores), con techo en la capacidad de planta del periodo.

    def _contexto_capacidad():
        from utils.kpi_helpers import (
            eq_batch_kg, eq_batch_regime, eq_capacity_basis, eq_capacity_tm_day,
            eq_harina_tm_day, eq_is_batch, eq_jornada, eq_output_tph,
            eq_produces, eq_stage, plant_capacity_tm_day, plant_harina_tm_day,
            plant_stages, plant_yield_factor,
        )
        from models import Area as _Area

        equipos = Equipment.query.all()
        lines = {l.id: l for l in Line.query.all()}
        areas = {a.id: a for a in _Area.query.all()}

        def area_de(eq):
            ln = lines.get(eq.line_id)
            return areas.get(ln.area_id) if ln else None

        def en_alcance(eq):
            if not getattr(eq, 'include_in_kpi', True):
                return False
            a = area_de(eq)
            return bool(a) and getattr(a, 'include_in_kpi', True)

        # Materia prima que entra a coccion y harina que puede salir de la
        # planta. La harina la marca la etapa mas limitada (coccion, secado o
        # molienda), porque van en serie.
        planta_dia = plant_capacity_tm_day(equipos)
        rendimiento = plant_yield_factor(equipos)
        harina_dia = plant_harina_tm_day(equipos)
        etapas = plant_stages(equipos)

        # tph = TM de HARINA por hora que se dejan de producir si el equipo
        # para. Los digestores generan (se les aplica el rendimiento); los
        # secadores y molinos procesan harina (su capacidad ya esta en harina).
        tph, cap_dia, harina_eq, produce, base = {}, {}, {}, {}, {}
        for e in equipos:
            dentro = en_alcance(e)
            cap_dia[e.id] = eq_capacity_tm_day(e) if dentro else 0.0
            harina_eq[e.id] = eq_harina_tm_day(e, rendimiento) if dentro else 0.0
            tph[e.id] = eq_output_tph(e, rendimiento) if dentro else 0.0
            base[e.id] = eq_capacity_basis(e)
            # Auxiliar: mueve o acondiciona, no transforma. Su parada no
            # resta toneladas, pero se reporta aparte para no esconderla.
            produce[e.id] = eq_produces(e) and dentro

        digestores = []
        for e in sorted([x for x in equipos if eq_is_batch(x)],
                        key=lambda x: (x.tag or '')):
            fill, batches = eq_batch_regime(e)
            shift_h, _ = eq_jornada(e)
            cap = eq_capacity_tm_day(e)
            digestores.append({
                'tag': e.tag, 'nombre': e.name,
                'kg_llenada': round(eq_batch_kg(e)),
                'fill_pct': round(fill, 1), 'llenadas_dia': round(batches, 1),
                'tm_dia': round(cap, 2),
                'tm_hora': round(cap / shift_h, 3) if shift_h else 0.0,
                'en_servicio': bool(getattr(e, 'in_service', True)),
                'motivo': getattr(e, 'out_of_service_reason', None),
                'en_alcance': en_alcance(e),
            })

        ORDEN_ETAPA = {'COCCION': 0, 'SECADOR': 1, 'MOLINO': 2}
        etapas_out = sorted(
            [{'etapa': s['etapa'],
              'rol': ('genera la harina' if s['base'] == 'MP'
                      else ('la seca' if s['etapa'] == 'SECADOR' else 'la muele')),
              'tm_dia': round(s['tm_dia'], 2),
              'equipos': s['equipos'], 'operativos': s['operativos'],
              'fuera_servicio': s['fuera_servicio'],
              'cuello_botella': abs(s['tm_dia'] - harina_dia) < 0.01}
             for s in etapas.values()],
            key=lambda x: ORDEN_ETAPA.get(x['etapa'], 9))

        return {
            'equipos': equipos,
            'area_de': area_de,
            'en_alcance': en_alcance,
            'planta_dia': planta_dia,       # TM/dia de materia prima a coccion
            'harina_dia': harina_dia,       # TM/dia de harina que sale
            'rendimiento': rendimiento,
            'tph': tph,                     # TM/h de HARINA por equipo
            'cap_dia': cap_dia,
            'harina_eq': harina_eq,
            'base': base,
            'produce': produce,
            'digestores': digestores,
            'etapas': etapas_out,
            'productivos': sorted(
                [{'tag': e.tag, 'nombre': e.name,
                  'area': (ctx_a.name if (ctx_a := area_de(e)) else None),
                  'etapa': eq_stage(e),
                  'base': base[e.id],
                  'tm_dia': round(cap_dia[e.id], 2),
                  'harina_tm_dia': round(harina_eq[e.id], 2),
                  'tm_hora': round(tph[e.id], 3),
                  'por_lotes': eq_is_batch(e),
                  'en_servicio': bool(getattr(e, 'in_service', True))}
                 for e in equipos if produce.get(e.id) and cap_dia[e.id] > 0],
                key=lambda x: (ORDEN_ETAPA.get(x['etapa'], 9), x['tag'] or '')),
        }

    def _tons_de_ot(ctx, ot, horas):
        """TM de HARINA que no se produjeron durante la parada del equipo."""
        if horas <= 0 or not ot.equipment_id:
            return 0.0
        return horas * ctx['tph'].get(ot.equipment_id, 0.0)

    def _area_resolver():
        line_map = {l.id: l for l in Line.query.all()}
        eq_map = {e.id: e for e in Equipment.query.all()}

        def resolver(ot):
            if ot.area_id:
                return ot.area_id
            if ot.line_id and ot.line_id in line_map:
                return line_map[ot.line_id].area_id
            if ot.equipment_id and ot.equipment_id in eq_map:
                e = eq_map[ot.equipment_id]
                if e.line_id and e.line_id in line_map:
                    return line_map[e.line_id].area_id
            return None
        return resolver, eq_map

    def _tons_periodo(ctx, closed, ini, fin):
        """TM de HARINA no producidas entre [ini, fin], equipo por equipo.
        Devuelve tambien lo que quedo fuera del calculo para poder avisarlo
        en pantalla en vez de esconderlo.

        El resultado se cachea por periodo: el mismo rango lo piden los KPIs,
        la lamina de produccion y la tendencia de 12 meses."""
        cache = ctx.setdefault('_cache_tons', {})
        clave = (ini, fin)
        if clave in cache:
            return cache[clave]
        hoy = dt.date.today()
        dias = max((min(fin, hoy) - ini).days + 1, 0)
        horas_periodo = dias * 24

        por_equipo = {}
        sin_cap = {'ots': 0, 'horas': 0.0, 'equipos': set()}
        auxiliares = {'ots': 0, 'horas': 0.0, 'equipos': set()}
        for o in closed:
            # Se recorren TODAS las cerradas, no solo las del periodo: una
            # parada que empezo antes tambien resta produccion a estos dias.
            h = _paro_en_rango(o, ini, fin)
            if h <= 0:
                continue
            eid = o.equipment_id
            if eid and not ctx['produce'].get(eid, False):
                # Auxiliar: paro, pero no es donde se produce la harina
                auxiliares['ots'] += 1
                auxiliares['horas'] += h
                auxiliares['equipos'].add(eid)
                continue
            if not eid or ctx['tph'].get(eid, 0.0) <= 0:
                # Productivo sin capacidad configurada (o OT sin equipo):
                # esto SI es un hueco que hay que llenar
                sin_cap['ots'] += 1
                sin_cap['horas'] += h
                if eid:
                    sin_cap['equipos'].add(eid)
                continue
            b = por_equipo.setdefault(eid, {'horas': 0.0, 'ots': 0})
            b['horas'] += h
            b['ots'] += 1

        total_harina = total_mp = 0.0
        for eid, b in por_equipo.items():
            # Un equipo no puede dejar de procesar mas horas que las que tuvo
            # el periodo (protege de downtimes mal capturados).
            b['horas_computadas'] = min(b['horas'], horas_periodo) if horas_periodo else 0.0
            b['tm_harina'] = b['horas_computadas'] * ctx['tph'][eid]
            # Materia prima: solo tiene sentido en coccion, que es donde entra
            b['tm_mp'] = (b['horas_computadas'] * ctx['cap_dia'][eid] / 24.0
                          if ctx['base'].get(eid) == 'MP' else 0.0)
            total_harina += b['tm_harina']
            total_mp += b['tm_mp']

        # Techo de realidad: la planta no puede dejar de producir mas harina
        # de la que su capacidad instalada permitia en esos dias.
        techo = ctx['harina_dia'] * dias
        techo_aplicado = False
        if techo > 0 and total_harina > techo:
            factor = techo / total_harina
            for b in por_equipo.values():
                b['tm_harina'] *= factor
                b['tm_mp'] *= factor
            total_mp *= factor
            total_harina = techo
            techo_aplicado = True

        res = {'por_equipo': por_equipo, 'tm_harina': total_harina,
               'tm_mp': total_mp, 'dias': dias,
               'horas_periodo': horas_periodo, 'capacidad_harina': techo,
               'techo_aplicado': techo_aplicado, 'sin_capacidad': sin_cap,
               'auxiliares': auxiliares}
        cache[clave] = res
        return res

    def _impacto_produccion(per, closed, eq_map, ctx=None):
        """Lamina de impacto en produccion del periodo analizado."""
        from models import Area as _Area
        ctx = ctx or _contexto_capacidad()
        if ctx['harina_dia'] <= 0:
            return {'disponible': False,
                    'motivo': 'Ningun equipo productivo tiene capacidad '
                              'configurada. Registrala en Alcance de Indicadores.'}

        rend = ctx['rendimiento']
        area_names = {a.id: a.name for a in _Area.query.all()}

        sel = _tons_periodo(ctx, closed, per['ini'], per['fin'])
        prev = _tons_periodo(ctx, closed, per['prev_ini'], per['prev_fin'])

        serie = []
        for ym in _months_back(per['month'], 12):
            y, m = int(ym[:4]), int(ym[5:7])
            r = _tons_periodo(ctx, closed, dt.date(y, m, 1),
                              dt.date(y, m, calendar.monthrange(y, m)[1]))
            t = r['tm_harina']
            serie.append({'month': ym, 'tons_lost': round(t, 1),
                          'tons_mp_lost': round(r['tm_mp'], 1),
                          'sacks_lost': int(t * 1000 / SACK_KG)})

        # Por area y por equipo
        por_area, top = {}, []
        for eid, b in sel['por_equipo'].items():
            eq = eq_map.get(eid)
            a = ctx['area_de'](eq) if eq else None
            aid = a.id if a else None
            pa = por_area.setdefault(aid, {'tm_harina': 0.0, 'tm_mp': 0.0,
                                           'horas': 0.0, 'ots': 0, 'equipos': 0})
            pa['tm_harina'] += b['tm_harina']
            pa['tm_mp'] += b['tm_mp']
            pa['horas'] += b['horas_computadas']
            pa['ots'] += b['ots']
            pa['equipos'] += 1
            top.append({
                'equipo': (f"[{eq.tag}] {eq.name}" if eq and eq.tag
                           else (eq.name if eq else f'Eq {eid}')),
                'equipment_id': eid,
                'horas_paro': round(b['horas_computadas'], 1),
                'ots': b['ots'],
                'rol': ('genera' if ctx['base'].get(eid) == 'MP' else 'procesa'),
                'tm_hora': round(ctx['tph'][eid], 3),
                'tons_lost': round(b['tm_harina'], 1),
                'tons_mp_lost': round(b['tm_mp'], 1),
                'sacks_lost': int(b['tm_harina'] * 1000 / SACK_KG),
            })
        top.sort(key=lambda x: -x['tons_lost'])

        tons_sel = sel['tm_harina']
        tons_prev = prev['tm_harina']
        cap_harina_periodo = sel['capacidad_harina']

        # Referencia de produccion: meta y produccion real del mes. Las metas
        # se registran por area pero son la MISMA cifra de planta repetida,
        # asi que se toma la mayor, no la suma (sumarlas triplicaba la meta).
        goals_map = _goals_por_area()
        areas_kpi = {a.id: bool(a.include_in_kpi) for a in _Area.query.all()}
        meta_planta = prod_real = 0.0
        periodo_meta = None
        for aid, lst in goals_map.items():
            g = _goal_para(lst, per['month'])
            if not g:
                continue
            if aid and not areas_kpi.get(aid, True):
                continue
            meta_planta = max(meta_planta, float(g.monthly_target_tons or 0))
            prod_real = max(prod_real, float(g.monthly_avg_yield_tons or 0))
            periodo_meta = g.goal_period

        def _nombres(ids, tope=12):
            out = []
            for eid in list(ids)[:tope]:
                e = eq_map.get(eid)
                if e:
                    out.append(f"[{e.tag}] {e.name}" if e.tag else e.name)
            return out

        sin_cap = sel['sin_capacidad']
        sin_cap_equipos = _nombres(sin_cap['equipos'])
        aux = sel['auxiliares']

        # Paradas anormalmente largas: casi siempre son horas mal capturadas
        # (se registro el tiempo transcurrido, no el que la planta estuvo
        # detenida). Se muestran para que se corrijan, no se ocultan.
        sospechosas = []
        for o in closed:
            h = _paro_en_rango(o, per['ini'], per['fin'])
            if h < 72:  # mas de 3 dias de parada continua
                continue
            e = eq_map.get(o.equipment_id)
            sospechosas.append({
                'code': o.code or f'OT-{o.id}',
                'equipo': (f"[{e.tag}] {e.name}" if e and e.tag else (e.name if e else '-')),
                'horas': round(h, 1),
                'dias': round(h / 24.0, 1),
                'desde': str(o.real_start_date or '')[:10],
                'hasta': str(o.real_end_date or '')[:10],
                'descripcion': (o.description or '')[:90],
            })
        sospechosas.sort(key=lambda x: -x['horas'])

        return {
            'disponible': True,
            'metodo': 'capacidad_real',
            'periodo_label': per['label'],
            'dias': sel['dias'],
            # Impacto del periodo
            'tons_lost_mes': round(tons_sel, 1),
            'tons_mp_lost_mes': round(sel['tm_mp'], 1),
            'sacks_lost_mes': int(tons_sel * 1000 / SACK_KG),
            'tons_lost_prev': round(tons_prev, 1),
            'horas_paro': round(sum(b['horas_computadas']
                                    for b in sel['por_equipo'].values()), 1),
            # Referencias para dimensionar el numero
            'capacidad_periodo_tons': round(cap_harina_periodo, 1),
            'capacidad_periodo_mp': round(ctx['planta_dia'] * sel['dias'], 1),
            'pct_de_capacidad': (round(tons_sel / cap_harina_periodo * 100, 2)
                                 if cap_harina_periodo else None),
            # La meta es mensual: solo tiene sentido compararla cuando el
            # periodo analizado es justamente un mes.
            'meta_mes_tons': round(meta_planta, 1) or None,
            'produccion_real_tons': round(prod_real, 1) or None,
            'periodo_meta': periodo_meta,
            'pct_de_meta': (round(tons_sel / meta_planta * 100, 2)
                            if meta_planta and per['modo'] == 'mes' else None),
            'utilizacion_pct': (round(prod_real / (ctx['harina_dia'] * 30.4375) * 100, 1)
                                if prod_real and ctx['harina_dia'] else None),
            'techo_aplicado': sel['techo_aplicado'],
            # Historico
            'tons_lost_12m': round(sum(s['tons_lost'] for s in serie), 1),
            'sacks_lost_12m': int(sum(s['tons_lost'] for s in serie) * 1000 / SACK_KG),
            'serie': serie,
            # Desgloses
            'por_area': sorted([
                {'area': area_names.get(aid, 'Sin area'),
                 'horas_paro': round(v['horas'], 1), 'ots': v['ots'],
                 'equipos': v['equipos'],
                 'tons_lost': round(v['tm_harina'], 1),
                 'tons_mp_lost': round(v['tm_mp'], 1),
                 'sacks_lost': int(v['tm_harina'] * 1000 / SACK_KG),
                 # Cuanto de la capacidad de PLANTA se llevo esta area
                 'pct_de_capacidad': (round(v['tm_harina'] / cap_harina_periodo * 100, 2)
                                      if cap_harina_periodo else None)}
                for aid, v in por_area.items()], key=lambda x: -x['tons_lost']),
            'top_equipos': top[:8],
            # Como se calculo (para mostrarlo en pantalla, sin caja negra)
            'capacidad': {
                'planta_tm_dia': round(ctx['planta_dia'], 1),
                'planta_tm_hora': round(ctx['planta_dia'] / 24.0, 3),
                'rendimiento_pct': round(rend * 100, 1),
                'harina_tm_dia': round(ctx['harina_dia'], 1),
                'harina_tm_hora': round(ctx['harina_dia'] / 24.0, 3),
                'digestores': ctx['digestores'],
                'operativos': len([d for d in ctx['digestores'] if d['en_servicio']]),
                'fuera_servicio': [d for d in ctx['digestores'] if not d['en_servicio']],
                # Las tres etapas en serie y cual es el cuello de botella
                'etapas': ctx['etapas'],
                # Todo lo que produce: digestores + secadores + molinos
                'productivos': ctx['productivos'],
            },
            'sin_capacidad': {
                'ots': sin_cap['ots'], 'horas': round(sin_cap['horas'], 1),
                'equipos': sin_cap_equipos,
            },
            # Paradas de equipos que no producen harina (transportadores,
            # ciclones, percoladores, vahos...): se informan, no restan TM.
            'auxiliares': {
                'ots': aux['ots'], 'horas': round(aux['horas'], 1),
                'equipos_distintos': len(aux['equipos']),
                'equipos': _nombres(aux['equipos'], 8),
            },
            'paradas_largas': sospechosas[:6],
            'sack_kg': SACK_KG,
        }

    # ── Portada ejecutiva: el veredicto en una sola lamina ────────────────
    # Lo primero que ve gerencia tiene que responder tres preguntas sin
    # explicaciones: como cerro el periodo, cuanto costo y que hay que hacer.

    def _semaforo(valor, bueno, regular, invertido=False):
        """'bueno' | 'regular' | 'malo' segun umbrales (invertido: menos es
        mejor)."""
        if valor is None:
            return 'neutro'
        if invertido:
            return 'bueno' if valor <= bueno else ('regular' if valor <= regular else 'malo')
        return 'bueno' if valor >= bueno else ('regular' if valor >= regular else 'malo')

    def _portada(per, k, kp, prod, backlog, top_equipos, pareto_mes):
        disp = k.get('disponibilidad_pct')
        proa = k.get('proactive_pct')
        cump = k.get('cumplimiento_pct')
        tons = prod.get('tons_lost_mes') if prod.get('disponible') else None
        pct_cap = prod.get('pct_de_capacidad') if prod.get('disponible') else None

        estados = {
            'disponibilidad': _semaforo(disp, 95, 90),
            'proactivo': _semaforo(proa, 75, 50),
            'cumplimiento': _semaforo(cump, 90, 70),
            'produccion': _semaforo(pct_cap, 2, 5, invertido=True),
        }
        malos = [k_ for k_, v in estados.items() if v == 'malo']
        regulares = [k_ for k_, v in estados.items() if v == 'regular']

        if len(malos) >= 2:
            veredicto, color = 'CRITICO', 'malo'
        elif malos:
            veredicto, color = 'REQUIERE ACCION', 'malo'
        elif regulares:
            veredicto, color = 'CON OBSERVACIONES', 'regular'
        else:
            veredicto, color = 'BAJO CONTROL', 'bueno'

        # Titular: la frase que resume el periodo
        horas = k.get('downtime_h') or 0
        if tons:
            titular = (f"{horas:g} h de planta parada — {tons:g} TM de harina "
                       f"que no se produjeron")
        else:
            titular = f"{horas:g} h de planta parada en el periodo"
        sub = f"{k.get('closed_total', 0)} OTs cerradas · "
        if disp is not None:
            sub += f"disponibilidad {disp}% · "
        sub += f"{k.get('correctivas', 0)} correctivas vs {k.get('proactivas', 0)} proactivas"

        # Las cuatro cifras que mandan
        def delta(cur, prv, unidad='', menos_es_mejor=False):
            if cur is None or prv is None:
                return None
            d = round(cur - prv, 1)
            return {'valor': d, 'unidad': unidad,
                    'mejor': (d < 0 if menos_es_mejor else d > 0) if d else None}

        cifras = [
            {'clave': 'produccion', 'label': 'TM de harina no producidas',
             'valor': tons, 'unidad': 'TM', 'estado': estados['produccion'],
             'pie': (f"{prod.get('sacks_lost_mes', 0):,} sacos de 50 kg".replace(',', ' ')
                     if prod.get('disponible') else 'sin capacidad configurada'),
             'delta': delta(tons, prod.get('tons_lost_prev'), ' TM', True)},
            {'clave': 'downtime', 'label': 'Horas de planta parada',
             'valor': round(horas, 1), 'unidad': 'h',
             'estado': _semaforo(horas, (kp.get('downtime_h') or horas) * 0.8,
                                 (kp.get('downtime_h') or horas) * 1.2, invertido=True),
             'pie': f"periodo anterior: {kp.get('downtime_h', 0)} h",
             'delta': delta(horas, kp.get('downtime_h'), ' h', True)},
            {'clave': 'disponibilidad', 'label': 'Disponibilidad de planta',
             'valor': disp, 'unidad': '%', 'estado': estados['disponibilidad'],
             'pie': 'meta clase mundial: 95%',
             'delta': delta(disp, kp.get('disponibilidad_pct'), ' pts')},
            {'clave': 'cumplimiento', 'label': 'Cumplimiento del programa',
             'valor': cump, 'unidad': '%', 'estado': estados['cumplimiento'],
             'pie': f"{k.get('programadas', 0)} OTs programadas · meta SMRP 90%",
             'delta': None},
        ]

        # Los hechos que explican esas cifras (solo lo que sale de los datos)
        hechos = []
        if prod.get('disponible') and prod.get('top_equipos'):
            t = prod['top_equipos'][0]
            parte = (round(t['tons_lost'] / tons * 100) if tons else 0)
            hechos.append(
                f"{t['equipo']} concentra {t['tons_lost']:g} TM perdidas "
                f"({parte}% del total) en {t['horas_paro']:g} h de parada.")
        if pareto_mes.get('items'):
            it = pareto_mes['items'][0]
            hechos.append(
                f"El modo de falla mas repetido es {it['label']}: {it['count']} "
                f"de {pareto_mes['total']} correctivas y {it['downtime_h']:g} h de paro.")
        if proa is not None:
            falta = max(0, round(75 - proa, 1))
            hechos.append(
                f"La mezcla de trabajo esta en {proa}% proactivo"
                + (f", {falta} puntos debajo del 75% de referencia SMRP."
                   if falta else ", por encima del 75% de referencia SMRP."))
        if cump is not None and k.get('programadas'):
            hechos.append(
                f"Se cerraron {round(cump / 100 * k['programadas'])} de "
                f"{k['programadas']} OTs programadas ({cump}% de cumplimiento).")
        vencidas = backlog['aging']['30-60'] + backlog['aging']['>60']
        if vencidas:
            hechos.append(
                f"El backlog arrastra {vencidas} OTs con mas de 30 dias y "
                f"{backlog['aging']['sin_fecha']} sin fecha asignada.")

        # Acciones priorizadas
        acciones = []
        if prod.get('disponible') and prod.get('top_equipos'):
            tops = ', '.join(t['equipo'] for t in prod['top_equipos'][:2])
            acciones.append(f"Analisis causa raiz de {tops}: ahi esta la mayor "
                            f"recuperacion de toneladas.")
        if pareto_mes.get('items'):
            acciones.append(f"Atacar el modo {pareto_mes['items'][0]['label']} con "
                            f"tarea preventiva especifica y repuesto en almacen.")
        if proa is not None and proa < 75:
            acciones.append("Subir la mezcla proactiva: pasar a plan las correctivas "
                            "repetitivas antes de que vuelvan a parar planta.")
        if cump is not None and cump < 90:
            acciones.append("Cerrar el programa comprometido: coordinar con produccion "
                            "las ventanas de las OTs que quedaron sin ejecutar.")
        if vencidas > 15:
            acciones.append(f"Sanear el backlog: {vencidas} OTs superan los 30 dias.")

        return {
            'veredicto': veredicto, 'color': color,
            'titular': titular, 'subtitulo': sub,
            'periodo': per['label'], 'prev': per['prev_label'],
            'en_curso': per['en_curso'], 'dias': per['dias'],
            'estados': estados,
            'cifras': cifras,
            'hechos': hechos[:5],
            'acciones': acciones[:4],
        }

    # ── Datos del diagnostico ─────────────────────────────────────────────

    @app.route('/diagnostico')
    def diagnostico_page():
        return render_template('diagnostico.html')

    def _build_diagnostico(month, desde=None, hasta=None):
        """Arma el dict completo del diagnostico del periodo. Lo usan el API
        JSON (/api/diagnostico/data) y el informe HTML descargable.

        El periodo es un mes completo (month=YYYY-MM) o cualquier rango de
        fechas (desde/hasta) para analizar campanas o ventanas propias."""
        try:
            per = _build_periodo(month, desde, hasta)
            hoy = per['hoy']
            mes_actual = hoy.strftime('%Y-%m')
            month = per['month']
            prev = _prev_month(month)
            nxt = _next_month(month)

            ots = WorkOrder.query.all()
            closed = [o for o in ots if o.status == 'Cerrada']
            open_ots = [o for o in ots if (o.status or '') not in ('Cerrada', 'No Ejecutada')]
            eq_map = {e.id: e for e in Equipment.query.all()}

            ctx_cap = _contexto_capacidad()

            # ── Stats de un periodo (MTBF/Disp/Conf a nivel planta) ──────
            # La disponibilidad de PLANTA se pondera por capacidad, no se
            # resta la suma bruta de horas: los 9 digestores trabajan en
            # PARALELO, asi que sumar sus paradas como si fueran en serie
            # daba disponibilidades de 0% cuando la planta seguia operando.
            #   disponibilidad = 1 - (TM que no se procesaron / TM que se
            #                          podian procesar en esas horas)
            # Es la misma cuenta que sostiene las toneladas perdidas, asi que
            # ambos indicadores cuadran entre si.
            def range_stats(ini, fin, label=None, ym=None):
                mes = [o for o in closed if _in_range(o, ini, fin)]
                corr = [o for o in mes if _mtype(o) == 'correctivo']
                proa = [o for o in mes if _mtype(o) in ('preventivo', 'predictivo')]
                mejora = [o for o in mes if _mtype(o) == 'mejora']
                mix_base = len(corr) + len(proa)
                # Horas de parada QUE OCURRIERON en el periodo (las paradas
                # que cruzan meses se reparten por dias, no se cargan enteras
                # al mes en que se cerro la OT).
                dt_total = sum(_paro_en_rango(o, ini, fin) for o in closed)
                # MTTR = tiempo medio de REPARACION: horas que el equipo
                # estuvo detenido por averia / numero de averias. Antes se
                # promediaba real_duration (horas-hombre del trabajo), que es
                # otra cosa y no coincidia con el modulo de Indicadores.
                paro_corr = [h for h in (_paro_en_rango(o, ini, fin) for o in corr) if h > 0]

                dias_nom = (fin - ini).days + 1
                dias_efectivos = max((min(fin, hoy) - ini).days + 1, 0)
                en_curso = fin > hoy
                horas_m = max(dias_efectivos * 24, 1)
                n_fallas = len(corr)

                imp = _tons_periodo(ctx_cap, closed, ini, fin)
                cap_mp = imp['capacidad_harina']
                if cap_mp > 0 and dias_efectivos:
                    perdida_pct = min(imp['tm_harina'] / cap_mp, 1.0)
                    disp = round((1 - perdida_pct) * 100, 2)
                    uptime = horas_m * (1 - perdida_pct)
                else:
                    # Sin capacidad configurada: se cae al metodo en serie
                    uptime = max(horas_m - dt_total, 0)
                    disp = round(uptime / horas_m * 100, 2) if dias_efectivos else None
                mtbf = round(uptime / n_fallas, 1) if n_fallas and dias_efectivos else None
                # Confiabilidad semanal R(168h) = e^(-168/MTBF)
                conf = (round(math.exp(-168.0 / mtbf) * 100, 1)
                        if mtbf and mtbf > 0 else None)

                return {
                    'month': ym or fin.strftime('%Y-%m'),
                    'desde': ini.isoformat(), 'hasta': fin.isoformat(),
                    'label': label or f"{_fecha_corta(ini)} — {_fecha_corta(fin)}",
                    'en_curso': en_curso,
                    'dias_efectivos': dias_efectivos,
                    'dias_mes': dias_nom,
                    'horas_periodo': horas_m,
                    'uptime_equivalente_h': round(uptime, 1),
                    'closed_total': len(mes),
                    'correctivas': len(corr),
                    'proactivas': len(proa),
                    'mejoras': len(mejora),
                    'proactive_pct': round(len(proa) / mix_base * 100, 1) if mix_base else 0.0,
                    'reactive_pct': round(len(corr) / mix_base * 100, 1) if mix_base else 0.0,
                    'mttr_h': round(sum(paro_corr) / len(paro_corr), 1) if paro_corr else None,
                    'downtime_h': round(dt_total, 1),
                    'mtbf_h': mtbf,
                    'disponibilidad_pct': disp,
                    'confiabilidad_pct': conf,
                    'metodo_disp': 'capacidad' if cap_mp > 0 else 'serie',
                }

            def month_stats(ym):
                y, m = int(ym[:4]), int(ym[5:7])
                return range_stats(dt.date(y, m, 1),
                                   dt.date(y, m, calendar.monthrange(y, m)[1]),
                                   _month_label(ym), ym)

            kpis_mes = range_stats(per['ini'], per['fin'], per['label'], per['month'])
            kpis_prev = range_stats(per['prev_ini'], per['prev_fin'], per['prev_label'])

            # Cumplimiento: OTs PROGRAMADAS dentro del periodo -> % cerradas
            d_ini, d_fin = per['ini'].isoformat(), per['fin'].isoformat()
            prog_mes = [o for o in ots if o.scheduled_date
                        and d_ini <= str(o.scheduled_date)[:10] <= d_fin]
            cerradas_prog = [o for o in prog_mes if o.status == 'Cerrada']
            kpis_mes['programadas'] = len(prog_mes)
            kpis_mes['cumplimiento_pct'] = (
                round(len(cerradas_prog) / len(prog_mes) * 100, 1) if prog_mes else None)

            # Tiempo de respuesta aviso->cierre en el periodo. Los avisos se
            # traen de una sola consulta: leerlos uno por uno (o.notice)
            # disparaba cientos de viajes a la BD y la pagina tardaba ~30 s.
            resp = []
            del_periodo = [o for o in closed
                           if o.notice_id and _in_range(o, per['ini'], per['fin'])]
            if del_periodo:
                from models import MaintenanceNotice
                ids = list({o.notice_id for o in del_periodo})
                fechas_aviso = {}
                for chunk in (ids[i:i + 300] for i in range(0, len(ids), 300)):
                    for n in MaintenanceNotice.query.filter(
                            MaintenanceNotice.id.in_(chunk)).all():
                        fechas_aviso[n.id] = n.request_date
                for o in del_periodo:
                    try:
                        d1 = dt.date.fromisoformat(str(fechas_aviso[o.notice_id])[:10])
                        d2 = dt.date.fromisoformat(str(o.real_end_date)[:10])
                        resp.append((d2 - d1).days)
                    except Exception:
                        pass
            kpis_mes['respuesta_dias'] = round(sum(resp) / len(resp), 1) if resp else None

            # ── Pareto de fallas (periodo y ultimos 6 meses) ─────────────
            def pareto(months_set=None, rango=None):
                buckets = {}
                total = 0
                for o in ots:
                    if _mtype(o) != 'correctivo':
                        continue
                    if rango is not None:
                        if not _in_range(o, rango[0], rango[1]):
                            continue
                    elif _ot_close_month(o) not in months_set:
                        continue
                    total += 1
                    key = (o.failure_mode or 'SIN MODO').strip().upper()
                    b = buckets.setdefault(key, {'label': key, 'count': 0, 'downtime_h': 0.0})
                    b['count'] += 1
                    b['downtime_h'] += _downtime(o)
                items = sorted(buckets.values(), key=lambda x: (-x['count'], -x['downtime_h']))
                cum = 0
                for it in items:
                    cum += it['count']
                    it['downtime_h'] = round(it['downtime_h'], 1)
                    it['cum_pct'] = round(cum / total * 100, 1) if total else 0
                return {'total': total, 'items': items[:12]}

            m6 = set(_months_back(month, 6))
            pareto_mes = pareto(rango=(per['ini'], per['fin']))
            pareto_6m = pareto(m6)

            # ── Top equipos por downtime (6 meses) ───────────────────────
            eq_buckets = {}
            for o in ots:
                if _mtype(o) != 'correctivo' or _ot_close_month(o) not in m6:
                    continue
                if o.equipment_id and o.equipment_id in eq_map:
                    e = eq_map[o.equipment_id]
                    key = f"[{e.tag}] {e.name}" if e.tag else e.name
                    eid = e.id
                else:
                    key, eid = '(sin equipo)', None
                b = eq_buckets.setdefault(key, {'equipo': key, 'equipment_id': eid,
                                                'fallas': 0, 'downtime_h': 0.0})
                b['fallas'] += 1
                b['downtime_h'] += _downtime(o)
            top_equipos = sorted(eq_buckets.values(),
                                 key=lambda x: (-x['downtime_h'], -x['fallas']))[:8]
            for t in top_equipos:
                t['downtime_h'] = round(t['downtime_h'], 1)

            # ── Tendencia y consolidado 12 meses ─────────────────────────
            trend = [month_stats(ym) for ym in _months_back(month, 12)]

            # ── Indicadores semana a semana del periodo seleccionado ─────
            # Bloques de 7 dias desde el inicio del periodo (en un mes salen
            # las semanas 1-7, 8-14... de siempre; en un rango libre, tantos
            # bloques como haga falta, hasta 12).
            semanas = []
            w = 0
            cursor = per['ini']
            while cursor <= per['fin'] and w < 12:
                d_ini = cursor
                d_fin = min(cursor + dt.timedelta(days=6), per['fin'])
                # El ultimo bloque de un mes absorbe los dias sueltos (29-31)
                if per['modo'] == 'mes' and (per['fin'] - d_fin).days <= 3 and w >= 3:
                    d_fin = per['fin']
                ini, fin = d_ini.isoformat(), d_fin.isoformat()

                mes_w = [o for o in closed if _in_range(o, d_ini, d_fin)]
                corr_w = [o for o in mes_w if _mtype(o) == 'correctivo']
                proa_w = [o for o in mes_w if _mtype(o) in ('preventivo', 'predictivo')]
                mix_w = len(corr_w) + len(proa_w)
                dt_w = sum(_paro_en_rango(o, d_ini, d_fin) for o in closed)
                # MTTR de la semana: horas de parada por averia / nº de averias
                mttr_vals_w = [h for h in (_paro_en_rango(o, d_ini, d_fin) for o in corr_w) if h > 0]

                # Bloque aun no transcurrido: sin KPIs de horas
                futura = d_ini > hoy
                dias_ef = max(0, (min(d_fin, hoy) - d_ini).days + 1)
                horas_w = dias_ef * 24
                imp_w = _tons_periodo(ctx_cap, closed, d_ini, d_fin)
                if imp_w['capacidad_harina'] > 0 and horas_w:
                    perd_w = min(imp_w['tm_harina'] / imp_w['capacidad_harina'], 1.0)
                    disp_w = round((1 - perd_w) * 100, 2)
                    uptime_w = horas_w * (1 - perd_w)
                else:
                    uptime_w = max(horas_w - dt_w, 0)
                    disp_w = round(uptime_w / horas_w * 100, 2) if horas_w else None
                mtbf_w = round(uptime_w / len(corr_w), 1) if corr_w and horas_w else None
                tons_w = imp_w['tm_harina']

                prog_w = [o for o in ots if o.scheduled_date
                          and ini <= str(o.scheduled_date)[:10] <= fin]
                cerr_w = [o for o in prog_w if o.status == 'Cerrada']

                semanas.append({
                    'semana': f"Sem {w + 1}",
                    'rango': (f"{d_ini.day:02d}-{d_fin.day:02d}" if per['modo'] == 'mes'
                              else f"{d_ini.day:02d}/{d_ini.month:02d}-{d_fin.day:02d}/{d_fin.month:02d}"),
                    'desde': ini, 'hasta': fin,
                    'futura': futura,
                    'closed_total': len(mes_w),
                    'correctivas': len(corr_w),
                    'proactivas': len(proa_w),
                    'mejoras': len([o for o in mes_w if _mtype(o) == 'mejora']),
                    'proactive_pct': round(len(proa_w) / mix_w * 100, 1) if mix_w else None,
                    'downtime_h': round(dt_w, 1),
                    'mttr_h': (round(sum(mttr_vals_w) / len(mttr_vals_w), 1)
                               if mttr_vals_w else None),
                    'mtbf_h': mtbf_w,
                    'disponibilidad_pct': disp_w,
                    'tons_lost': round(tons_w, 1),
                    'programadas': len(prog_w),
                    'cumplimiento_pct': (round(len(cerr_w) / len(prog_w) * 100, 1)
                                         if prog_w else None),
                })
                cursor = d_fin + dt.timedelta(days=1)
                w += 1

            # ── Backlog (foto actual) ────────────────────────────────────
            aging = {'<30': 0, '30-60': 0, '>60': 0, 'sin_fecha': 0}
            for o in open_ots:
                if not o.scheduled_date:
                    aging['sin_fecha'] += 1
                    continue
                try:
                    d = dt.date.fromisoformat(str(o.scheduled_date)[:10])
                    dias = (hoy - d).days
                    aging['>60' if dias > 60 else ('30-60' if dias > 30 else '<30')] += 1
                except Exception:
                    aging['sin_fecha'] += 1
            backlog = {
                'total': len(open_ots),
                'con_tecnico': len([o for o in open_ots if o.technician_id]),
                'programadas': len([o for o in open_ots if o.status == 'Programada']),
                'horas_estimadas': round(sum(float(o.estimated_duration or 0) for o in open_ots), 1),
                'aging': aging,
            }

            # ── Rutinas y predictivo ─────────────────────────────────────
            lub_pts = LubricationPoint.query.filter_by(is_active=True).all()
            insp_pts = InspectionRoute.query.filter_by(is_active=True).all()
            mon_pts = MonitoringPoint.query.filter_by(is_active=True).all()

            def sem_counts(points):
                c = defaultdict(int)
                for p in points:
                    c[(p.semaphore_status or 'PENDIENTE').upper()] += 1
                return dict(c)

            rutinas = {
                'lubricacion': sem_counts(lub_pts),
                'inspeccion': sem_counts(insp_pts),
                'monitoreo': sem_counts(mon_pts),
            }

            rot = RotativeAsset.query.filter_by(is_active=True).all()
            CATS = ('MOTOR', 'BOMBA', 'MOTORREDUCTOR', 'CAJA REDUCTORA', 'REDUCTOR')
            rot_pred = [a for a in rot
                        if getattr(a, 'is_electric_motor', False)
                        or any(c in (a.category or '').upper() for c in CATS)]
            electricos = [a for a in rot_pred if getattr(a, 'is_electric_motor', False)]
            predictivo = {
                'activos_criticos': len(rot_pred),
                'electricos': len(electricos),
                'megado_hecho': len([a for a in electricos if a.last_megado_date]),
                'megado_pendiente': len([a for a in electricos if not a.last_megado_date]),
                'megado_rojo': len([a for a in electricos if (a.megado_status or '') == 'ROJO']),
            }

            # ── Almacen / proveedores ────────────────────────────────────
            items_alm = WarehouseItem.query.filter_by(is_active=True).all()
            almacen = {
                'items': len(items_alm),
                'bajo_minimo': len([i for i in items_alm
                                    if i.min_stock and (i.stock or 0) <= i.min_stock]),
                'quiebres': len([i for i in items_alm
                                 if (i.stock or 0) == 0 and (i.min_stock or 0) > 0]),
            }
            informes = {
                'requeridos': len([o for o in ots if o.report_required]),
                'pendientes': len([o for o in ots if o.report_required
                                   and (o.report_status or 'PENDIENTE') != 'RECIBIDO'
                                   and not (o.report_url or '').strip()]),
            }

            # ── Impacto en produccion: TM y sacos no producidos ──────────
            # TM no producidas = horas de parada x capacidad REAL del equipo
            # que paro. Los digestores aportan sus llenadas (kg x % llenado x
            # llenadas/dia); el resto de equipos, las TM/dia capturadas en
            # Alcance de Indicadores. Nunca se valora la parada de un equipo
            # con el rendimiento de toda la planta, y el total del periodo
            # tiene techo en la capacidad instalada de esos dias.
            produccion = {'disponible': False}
            try:
                produccion = _impacto_produccion(per, closed, eq_map, ctx_cap)
            except Exception as _pe:
                logger.warning(f"produccion impacto skipped: {_pe}")

            # ── Programacion: resto del mes en curso + mes siguiente ─────
            tecnicos = Technician.query.filter_by(is_active=True).count()

            def _ot_row(o):
                e = eq_map.get(o.equipment_id)
                return {
                    'code': o.code or f'OT-{o.id}',
                    'equipo': (f"[{e.tag}] {e.name}" if e and e.tag else (e.name if e else '-')),
                    'tipo': o.maintenance_type or '-',
                    'fecha': o.scheduled_date,
                    'horas': float(o.estimated_duration or 0),
                    'descripcion': (o.description or '')[:110],
                    'status': o.status,
                }

            def build_programa(ym, desde_dia=1):
                """Programa del mes ym, desde el dia `desde_dia` (para el mes
                en curso: solo lo que queda)."""
                dias_m = calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]
                d_ini = f"{ym}-{desde_dia:02d}"
                d_fin = f"{ym}-{dias_m:02d}"

                ots_win = [o for o in open_ots
                           if o.scheduled_date and d_ini <= str(o.scheduled_date)[:10] <= d_fin]

                def due(points, attr):
                    out = []
                    for p in points:
                        d = getattr(p, attr, None)
                        if d and d_ini <= str(d)[:10] <= d_fin:
                            out.append(str(d)[:10])
                    # Vencidos arrastrados: si estamos en el mes en curso,
                    # lo vencido ANTES de hoy tambien es carga pendiente
                    if desde_dia > 1:
                        for p in points:
                            d = getattr(p, attr, None)
                            if d and str(d)[:10] < d_ini:
                                out.append(d_ini)  # se cuenta en la 1ra semana restante
                    return out

                lub_due = due(lub_pts, 'next_due_date')
                insp_due = due(insp_pts, 'next_due_date')
                mon_due = due(mon_pts, 'next_due_date')
                meg_due = due(electricos, 'next_megado_due')

                def por_semana(fechas):
                    sem = [0, 0, 0, 0, 0]
                    for f in fechas:
                        dia = int(f[8:10])
                        sem[min((dia - 1) // 7, 4)] += 1
                    return sem

                habiles = sum(1 for d in range(desde_dia, dias_m + 1)
                              if dt.date(int(ym[:4]), int(ym[5:7]), d).weekday() < 6)
                capacidad_h = tecnicos * 8 * habiles
                carga_h = sum(float(o.estimated_duration or 0) for o in ots_win)

                return {
                    'month': ym,
                    'label': _month_label(ym),
                    'parcial': desde_dia > 1,
                    'desde': d_ini,
                    'ots_programadas': [_ot_row(o) for o in
                                        sorted(ots_win, key=lambda x: x.scheduled_date or '')][:120],
                    'rutinas_semana': {
                        'semanas': ['Sem 1 (1-7)', 'Sem 2 (8-14)', 'Sem 3 (15-21)',
                                    'Sem 4 (22-28)', 'Sem 5 (29+)'],
                        'lubricacion': por_semana(lub_due),
                        'inspeccion': por_semana(insp_due),
                        'monitoreo': por_semana(mon_due),
                        'megado': por_semana(meg_due),
                    },
                    'totales_rutinas': {
                        'lubricacion': len(lub_due), 'inspeccion': len(insp_due),
                        'monitoreo': len(mon_due), 'megado': len(meg_due),
                    },
                    'capacidad': {
                        'tecnicos': tecnicos, 'dias_habiles': habiles,
                        'horas_disponibles': capacidad_h,
                        'horas_programadas': round(carga_h, 1),
                        'utilizacion_pct': (round(carga_h / capacidad_h * 100, 1)
                                            if capacidad_h else None),
                    },
                }

            # Resto del mes seleccionado (solo aplica si es el mes en curso)
            programa_actual = (build_programa(month, desde_dia=hoy.day)
                               if month == mes_actual else None)
            programa = build_programa(nxt)
            programa['ots_sin_fecha'] = len([o for o in open_ots if not o.scheduled_date])

            paradas_prox = []
            try:
                for s in Shutdown.query.all():
                    if s.shutdown_date and str(s.shutdown_date)[:10] >= hoy.isoformat():
                        paradas_prox.append({
                            'code': getattr(s, 'code', None), 'name': s.name,
                            'fecha': str(s.shutdown_date)[:10],
                            'planificada': bool(getattr(s, 'is_planned', True)),
                        })
                paradas_prox.sort(key=lambda x: x['fecha'])
            except Exception:
                pass
            programa['paradas_proximas'] = paradas_prox[:10]

            portada = _portada(per, kpis_mes, kpis_prev, produccion, backlog,
                               top_equipos, pareto_mes)

            return {
                'meta': {
                    'month': month, 'label': per['label'],
                    'prev_label': per['prev_label'],
                    'modo': per['modo'],
                    'desde': per['ini'].isoformat(), 'hasta': per['fin'].isoformat(),
                    'dias': per['dias'], 'dias_nominales': per['dias_nominales'],
                    'en_curso': per['en_curso'],
                    'dia_hoy': hoy.day,
                    'hoy': hoy.isoformat(),
                    'generated_at': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
                },
                'portada': portada,
                'kpis_mes': kpis_mes,
                'kpis_prev': kpis_prev,
                'semanas': semanas,
                'pareto_mes': pareto_mes,
                'pareto_6m': pareto_6m,
                'top_equipos': top_equipos,
                'trend': trend,
                'backlog': backlog,
                'rutinas': rutinas,
                'predictivo': predictivo,
                'almacen': almacen,
                'informes': informes,
                'produccion': produccion,
                'programa_actual': programa_actual,
                'programa': programa,
            }
        except Exception:
            logger.exception('diagnostico build error')
            raise

    @app.route('/api/diagnostico/data', methods=['GET'])
    def diagnostico_data():
        """month=YYYY-MM  o  desde=YYYY-MM-DD&hasta=YYYY-MM-DD (rango libre)."""
        try:
            return jsonify(_build_diagnostico(
                request.args.get('month'),
                request.args.get('desde'),
                request.args.get('hasta')))
        except Exception as e:
            logger.exception('diagnostico_data error')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/diagnostico/periodos', methods=['GET'])
    def diagnostico_periodos():
        """Atajos de periodo para el selector, calculados en el servidor para
        que 'ultimo mes cerrado' sea siempre el mes correcto."""
        try:
            hoy = dt.date.today()
            mes_actual = hoy.strftime('%Y-%m')
            prev = _prev_month(mes_actual)

            def rango(dias):
                fin = hoy
                ini = hoy - dt.timedelta(days=dias - 1)
                return {'desde': ini.isoformat(), 'hasta': fin.isoformat()}

            # Ultimo mes YA TERMINADO con OTs cerradas: es el que sirve para
            # presentar. El mes en curso casi siempre lleva dos dias cargados
            # y sus indicadores no representan nada.
            meses = set()
            for o in WorkOrder.query.filter(WorkOrder.status == 'Cerrada').all():
                m = _ot_close_month(o)
                if m and m < mes_actual:
                    meses.add(m)
            ultimo_con_datos = max(meses) if meses else prev

            return jsonify({
                'hoy': hoy.isoformat(),
                'mes_actual': mes_actual,
                'mes_actual_label': _month_label(mes_actual),
                'ultimo_mes': prev,
                'ultimo_mes_label': _month_label(prev),
                'ultimo_con_datos': ultimo_con_datos,
                'ultimo_con_datos_label': _month_label(ultimo_con_datos),
                'ultimos_30': rango(30),
                'ultimos_90': rango(90),
                'anio_actual': {'desde': f'{hoy.year}-01-01', 'hasta': hoy.isoformat()},
            })
        except Exception as e:
            logger.exception('diagnostico_periodos error')
            return jsonify({'error': str(e)}), 500

    # ── Evolucion mensual por alcance (planta / area / equipo) ────────────

    @app.route('/api/diagnostico/evolucion', methods=['GET'])
    def diagnostico_evolucion():
        """Indicadores mes a mes para el alcance elegido (drill-down):
        sin filtro = planta; ?area_id=N = un area; ?equipment_id=N = un
        equipo. Incluye TM no producidas si el area tiene meta de produccion.
        """
        try:
            hoy = dt.date.today()
            mes_actual = hoy.strftime('%Y-%m')
            month = (request.args.get('month') or mes_actual)[:7]
            n = min(request.args.get('months', default=12, type=int), 24)
            area_id = request.args.get('area_id', type=int)
            equipment_id = request.args.get('equipment_id', type=int)

            resolver_area, eq_map = _area_resolver()
            ctx = _contexto_capacidad()

            closed = [o for o in WorkOrder.query.filter(WorkOrder.status == 'Cerrada').all()]

            def en_alcance(o):
                if equipment_id:
                    return o.equipment_id == equipment_id
                if area_id:
                    return resolver_area(o) == area_id
                return True

            # Capacidad del alcance visible (denominador de la disponibilidad
            # ponderada). Para un area se usa la capacidad de PLANTA, no la
            # suma de sus equipos: todas las areas procesan el mismo flujo en
            # serie, y sumar digestor + su transportador contaria dos veces la
            # misma tonelada. Asi la disponibilidad de cada area es la parte
            # de la planta que esa area dejo de producir.
            # Todo en TM de HARINA: es la unica unidad comun a las tres etapas
            if equipment_id:
                cap_alcance_dia = ctx['harina_eq'].get(equipment_id, 0.0)
            else:
                cap_alcance_dia = ctx['harina_dia']

            serie = []
            for ym in _months_back(month, n):
                mes = [o for o in closed if _ot_close_month(o) == ym and en_alcance(o)]
                corr = [o for o in mes if _mtype(o) == 'correctivo']
                dt_total = sum(_downtime(o) for o in mes)

                dias_m = calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]
                dias_ef = hoy.day if ym == mes_actual else dias_m
                horas = max(dias_ef * 24, 1)
                n_f = len(corr)

                # TM de harina no producidas: capacidad real del equipo parado
                tons = 0.0
                for o in mes:
                    dtx = _downtime(o)
                    if dtx > 0:
                        tons += _tons_de_ot(ctx, o, dtx)

                # Disponibilidad ponderada por capacidad del alcance
                cap_periodo = cap_alcance_dia * dias_ef
                if cap_periodo > 0:
                    perd = min(tons / cap_periodo, 1.0)
                    disp = round((1 - perd) * 100, 2)
                    uptime = horas * (1 - perd)
                else:
                    uptime = max(horas - dt_total, 0)
                    disp = round(uptime / horas * 100, 2)

                serie.append({
                    'month': ym,
                    'en_curso': ym == mes_actual,
                    'fallas': n_f,
                    'ots_cerradas': len(mes),
                    'downtime_h': round(dt_total, 1),
                    'disponibilidad_pct': disp,
                    'mtbf_h': round(uptime / n_f, 1) if n_f else None,
                    'mttr_h': round(dt_total / n_f, 1) if n_f and dt_total else None,
                    'tons_lost': round(tons, 1),
                })

            etiqueta = 'Planta completa'
            if equipment_id and equipment_id in eq_map:
                e = eq_map[equipment_id]
                etiqueta = f"[{e.tag}] {e.name}" if e.tag else e.name
            elif area_id:
                from models import Area as _Area
                a = _Area.query.get(area_id)
                etiqueta = a.name if a else f'Area {area_id}'

            return jsonify({'alcance': etiqueta, 'serie': serie})
        except Exception as e:
            logger.exception('diagnostico_evolucion error')
            return jsonify({'error': str(e)}), 500

    # ── Drill-down: OTs detras de un valor del grafico ────────────────────

    @app.route('/api/diagnostico/ots-detail', methods=['GET'])
    def diagnostico_ots_detail():
        """OTs que explican cualquier punto de los graficos del diagnostico
        (filtro dinamico de los drill-down).

        Query:
          month=YYYY-MM, window=mes|6m         ventana por mes de cierre
          desde=YYYY-MM-DD & hasta=YYYY-MM-DD  rango exacto (barras semanales)
          tipo=correctivo|proactivo|preventivo|predictivo|mejora|todas
               (default: correctivo, para Pareto y equipos criticos)
          failure_mode=..., equipment_id=N, sin_equipo=1
          con_downtime=1   solo OTs que causaron horas de parada
          programadas=1    OTs PROGRAMADAS en el rango, cualquier estado
                           (drill-down de cumplimiento)
          tons=1           agrega TM y sacos de harina no producidos por OT
        """
        try:
            hoy = dt.date.today()
            month = (request.args.get('month') or hoy.strftime('%Y-%m'))[:7]
            window = (request.args.get('window') or '6m').lower()
            fm = (request.args.get('failure_mode') or '').strip().upper()
            eq_id = request.args.get('equipment_id', type=int)
            sin_equipo = request.args.get('sin_equipo') == '1'
            tipo = (request.args.get('tipo') or 'correctivo').strip().lower()
            desde = (request.args.get('desde') or '')[:10]
            hasta = (request.args.get('hasta') or '')[:10]
            con_downtime = request.args.get('con_downtime') == '1'
            programadas = request.args.get('programadas') == '1'
            con_tons = request.args.get('tons') == '1'

            months = {month} if window == 'mes' else set(_months_back(month, 6))
            eq_map = {e.id: e for e in Equipment.query.all()}
            ctx = _contexto_capacidad() if con_tons else None

            def tipo_ok(o):
                if tipo == 'todas':
                    return True
                mt = _mtype(o)
                if tipo == 'proactivo':
                    return mt in ('preventivo', 'predictivo')
                return mt == tipo

            rows = []
            for o in WorkOrder.query.all():
                if programadas:
                    f = str(o.scheduled_date)[:10] if o.scheduled_date else ''
                    if not f:
                        continue
                    if desde and hasta:
                        if not (desde <= f <= hasta):
                            continue
                    elif f[:7] not in months:
                        continue
                    # En modo programadas el default (correctivo) no filtra:
                    # el cumplimiento se mide sobre TODO lo programado
                    if tipo != 'correctivo' and not tipo_ok(o):
                        continue
                else:
                    if not tipo_ok(o):
                        continue
                    if desde and hasta:
                        # Rango exacto: misma fecha que usan las barras
                        # semanales (solo OTs cerradas)
                        if o.status != 'Cerrada':
                            continue
                        d = o.real_end_date or o.real_start_date or o.scheduled_date
                        if not d or not (desde <= str(d)[:10] <= hasta):
                            continue
                    elif _ot_close_month(o) not in months:
                        continue
                if fm and (o.failure_mode or 'SIN MODO').strip().upper() != fm:
                    continue
                if eq_id and o.equipment_id != eq_id:
                    continue
                if sin_equipo and o.equipment_id:
                    continue
                dt_h = _downtime(o)
                if con_downtime and dt_h <= 0:
                    continue
                e = eq_map.get(o.equipment_id)
                row = {
                    'code': o.code or f'OT-{o.id}',
                    'fecha': str(o.scheduled_date if programadas else
                                 (o.real_end_date or o.scheduled_date or '-'))[:10],
                    'equipo': (f"[{e.tag}] {e.name}" if e and e.tag else (e.name if e else '-')),
                    'tipo': o.maintenance_type or '-',
                    'modo': (o.failure_mode or '-'),
                    'status': o.status,
                    'downtime_h': round(dt_h, 1),
                    'duracion_h': float(o.real_duration or 0),
                    'descripcion': (o.description or '')[:130],
                    'ejecucion': (o.execution_comments or '')[:130],
                }
                if con_tons:
                    tons = _tons_de_ot(ctx, o, dt_h) if dt_h > 0 else 0.0
                    row['tons_lost'] = round(tons, 1)
                    row['sacks_lost'] = int(tons * 1000 / SACK_KG)
                rows.append(row)

            if con_tons:
                rows.sort(key=lambda r: (-r.get('tons_lost', 0), -r['downtime_h']))
            elif programadas:
                rows.sort(key=lambda r: r['fecha'])
            else:
                rows.sort(key=lambda r: (-r['downtime_h'], r['fecha']))
            return jsonify({'total': len(rows), 'rows': rows[:80]})
        except Exception as e:
            logger.exception('diagnostico_ots_detail error')
            return jsonify({'error': str(e)}), 500

    # ── Narrativa ejecutiva con DeepSeek (asincrona) ──────────────────────
    # DeepSeek puede tardar 30-90s y los proxies (Render/gunicorn) cortan la
    # request devolviendo una pagina HTML -> "Unexpected token '<'" en el
    # navegador. Por eso el POST lanza un hilo y responde al instante con un
    # job_id; el frontend consulta GET /narrativa/<job_id> hasta tener el texto.
    # Los trabajos se guardan en la tabla narrative_jobs, NO en memoria: con
    # gunicorn corriendo varios workers, el POST que crea el trabajo y el GET
    # que lo consulta caen en procesos distintos, y el que preguntaba nunca
    # encontraba el trabajo del otro.

    def _job_get(job_id):
        from models import NarrativeJob
        return db.session.get(NarrativeJob, job_id) if job_id else None

    def _job_set(job_id, **campos):
        """Actualiza el trabajo desde el hilo de fondo, con su propia sesion."""
        from models import NarrativeJob
        with app.app_context():
            try:
                job = db.session.get(NarrativeJob, job_id)
                if not job:
                    return
                for k_, v_ in campos.items():
                    setattr(job, k_, v_)
                job.updated_at = dt.datetime.utcnow()
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception('no se pudo actualizar la narrativa %s', job_id)

    def _limpiar_jobs():
        """Borra los analisis de mas de 3 dias."""
        from models import NarrativeJob
        try:
            limite = dt.datetime.utcnow() - dt.timedelta(days=3)
            NarrativeJob.query.filter(NarrativeJob.created_at < limite).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()

    @app.route('/api/diagnostico/narrativa/<job_id>', methods=['GET'])
    def diagnostico_narrativa_status(job_id):
        job = _job_get(job_id)
        if not job:
            return jsonify({'error': 'Trabajo no encontrado (expiro o el servidor '
                                     'se reinicio). Vuelve a generar.'}), 404
        d = job.to_dict()
        # Segundos que lleva corriendo: el frontend lo muestra en vez de
        # inventarse un contador propio.
        if job.status == 'PENDIENTE' and job.created_at:
            d['esperando_s'] = round((dt.datetime.utcnow() - job.created_at).total_seconds())
        return jsonify(d)

    @app.route('/api/diagnostico/narrativa', methods=['POST'])
    def diagnostico_narrativa():
        try:
            data = request.get_json(force=True) or {}
            k = data.get('kpis_mes', {})
            kp = data.get('kpis_prev', {})
            mt = data.get('meta', {})
            en_curso = mt.get('en_curso')
            resumen = [
                f"PERIODO ANALIZADO: {mt.get('label', '?')}"
                + f" ({mt.get('desde')} a {mt.get('hasta')}, {mt.get('dias')} dias)"
                + (f" — EN CURSO, KPIs parciales" if en_curso else ""),
                f"PERIODO DE COMPARACION: {mt.get('prev_label', '?')}",
                f"OTs cerradas: {k.get('closed_total')} (correctivas {k.get('correctivas')}, "
                f"proactivas {k.get('proactivas')}, mejoras {k.get('mejoras')})",
                f"% proactivo: {k.get('proactive_pct')}% (mes anterior: {kp.get('proactive_pct')}%) — meta SMRP >75%",
                f"MTTR: {k.get('mttr_h')} h (ant: {kp.get('mttr_h')}) | MTBF: {k.get('mtbf_h')} h "
                f"(ant: {kp.get('mtbf_h')}) | Disponibilidad: {k.get('disponibilidad_pct')}% "
                f"(ant: {kp.get('disponibilidad_pct')}%) | Confiabilidad semanal: {k.get('confiabilidad_pct')}%",
                f"Downtime: {k.get('downtime_h')} h (anterior: {kp.get('downtime_h')} h)",
                f"Cumplimiento de programa: {k.get('cumplimiento_pct')}% de {k.get('programadas')} programadas — meta >90%",
                f"Respuesta aviso a cierre: {k.get('respuesta_dias')} dias",
            ]
            par = data.get('pareto_mes', {})
            if par.get('items'):
                resumen.append("PARETO DEL MES (modo: fallas / horas parada): " + "; ".join(
                    f"{i['label']}: {i['count']}/{i['downtime_h']}h" for i in par['items'][:6]))
            teq = data.get('top_equipos') or []
            if teq:
                resumen.append("TOP EQUIPOS 6 MESES (downtime): " + "; ".join(
                    f"{t['equipo']}: {t['fallas']} fallas/{t['downtime_h']}h" for t in teq[:5]))
            tr = data.get('trend') or []
            if tr:
                resumen.append("TENDENCIA (mes: %proactivo/disp%/downtime h): " + "; ".join(
                    f"{t['month']}: {t['proactive_pct']}%/{t['disponibilidad_pct']}%/{t['downtime_h']}h"
                    for t in tr[-6:]))
            sem = data.get('semanas') or []
            if sem:
                resumen.append("SEMANAS DEL MES (cerradas/correctivas/downtime h/cumplimiento): " + "; ".join(
                    f"{s.get('semana')} [{s.get('rango')}]: {s.get('closed_total')}/"
                    f"{s.get('correctivas')}/{s.get('downtime_h')}h/{s.get('cumplimiento_pct')}%"
                    + (" FUTURA" if s.get('futura') else "")
                    for s in sem))
            bl = data.get('backlog', {})
            resumen.append(f"BACKLOG: {bl.get('total')} OTs abiertas, {bl.get('con_tecnico')} con tecnico, "
                           f"{bl.get('programadas')} programadas, aging {bl.get('aging')}")
            pred = data.get('predictivo', {})
            resumen.append(f"PREDICTIVO: {pred.get('electricos')} motores electricos, megado hecho "
                           f"{pred.get('megado_hecho')}, pendiente {pred.get('megado_pendiente')}")
            alm = data.get('almacen', {})
            resumen.append(f"ALMACEN: {alm.get('bajo_minimo')}/{alm.get('items')} bajo minimo, "
                           f"{alm.get('quiebres')} quiebres")
            inf = data.get('informes', {})
            resumen.append(f"INFORMES PROVEEDOR: {inf.get('pendientes')}/{inf.get('requeridos')} pendientes")
            prod = data.get('produccion') or {}
            if prod.get('disponible'):
                cap = prod.get('capacidad', {})
                resumen.append(
                    f"CAPACIDAD REAL DE PLANTA: {cap.get('operativos')} digestores operativos "
                    f"procesan {cap.get('planta_tm_dia')} TM/dia de materia prima "
                    f"({cap.get('planta_tm_hora')} TM/h); con un rendimiento de "
                    f"{cap.get('rendimiento_pct')}% eso son {cap.get('harina_tm_dia')} TM/dia de harina. "
                    f"En el periodo la capacidad instalada fue {prod.get('capacidad_periodo_tons')} TM de harina."
                    + ("" if not cap.get('fuera_servicio') else
                       " Fuera de servicio: " + ", ".join(
                           f"{d['tag']} ({d['tm_dia']} TM/dia)" for d in cap['fuera_servicio'])))
                resumen.append(
                    f"IMPACTO EN PRODUCCION: las {prod.get('horas_paro')} h de parada dejaron de "
                    f"producir {prod.get('tons_lost_mes')} TM de harina "
                    f"({prod.get('sacks_lost_mes')} sacos de 50kg), el "
                    f"{prod.get('pct_de_capacidad')}% de la capacidad del periodo"
                    + (f" y el {prod.get('pct_de_meta')}% de la meta mensual "
                       f"({prod.get('meta_mes_tons')} TM)" if prod.get('pct_de_meta') is not None else "")
                    + f". Periodo anterior: {prod.get('tons_lost_prev')} TM. "
                    f"Acumulado 12 meses: {prod.get('tons_lost_12m')} TM "
                    f"({prod.get('sacks_lost_12m')} sacos). Top equipos por TM perdidas: "
                    + "; ".join(f"{t['equipo']}: {t['tons_lost']} TM en {t['horas_paro']} h"
                                for t in (prod.get('top_equipos') or [])[:3]))
                resumen.append(
                    "METODO: TM no producidas = horas de parada x capacidad REAL del equipo "
                    "detenido (los digestores por kg de llenada x % de llenado x llenadas al "
                    "dia). No se valora la parada de un equipo con el rendimiento de toda la "
                    "planta. NO uses otra metodologia ni recalcules estas cifras.")
                if prod.get('por_area'):
                    resumen.append("TM PERDIDAS POR AREA: " + "; ".join(
                        f"{a['area']}: {a['tons_lost']} TM ({a['sacks_lost']} sacos) "
                        f"en {a['horas_paro']} h"
                        for a in prod['por_area'][:6]))
                if (prod.get('sin_capacidad') or {}).get('ots'):
                    sc = prod['sin_capacidad']
                    resumen.append(
                        f"AVISO: {sc['ots']} OTs con {sc['horas']} h de parada quedaron fuera del "
                        f"calculo por no tener capacidad configurada en Alcance de Indicadores.")

            po = data.get('portada') or {}
            if po:
                resumen.append(f"VEREDICTO CALCULADO: {po.get('veredicto')} — {po.get('titular')}")

            pa = data.get('programa_actual')
            if pa:
                capa = pa.get('capacidad', {})
                resumen.append(f"RESTO DEL MES EN CURSO (desde {pa.get('desde')}): "
                               f"{len(pa.get('ots_programadas', []))} OTs programadas, rutinas "
                               f"{pa.get('totales_rutinas')}, capacidad restante {capa.get('horas_disponibles')}h, "
                               f"carga {capa.get('horas_programadas')}h")
            prog = data.get('programa', {})
            cap = prog.get('capacidad', {})
            resumen.append(f"PROXIMO MES ({prog.get('label')}): {len(prog.get('ots_programadas', []))} OTs "
                           f"programadas, {prog.get('ots_sin_fecha')} sin fecha, rutinas "
                           f"{prog.get('totales_rutinas')}, capacidad {cap.get('horas_disponibles')}h "
                           f"({cap.get('tecnicos')} tecnicos), carga {cap.get('horas_programadas')}h")

            system_prompt = (
                "Eres el jefe de confiabilidad de una planta industrial de procesamiento. "
                "Con los datos entregados genera un DIAGNOSTICO EJECUTIVO en espanol para "
                "presentar a gerencia y jefaturas de mantenimiento y produccion. Usa SOLO los "
                "datos proporcionados, no inventes cifras ni recalcules las toneladas. Si el "
                "periodo esta EN CURSO, indica que los KPIs son parciales y proyecta con "
                "cautela. Referencia benchmarks SMRP "
                "donde aplique (cumplimiento >90%, proactivo >75%, backlog 2-4 semanas). "
                "El analisis debe ser COMPLETO y detallado (apunta a 700-1000 palabras). "
                "El impacto en produccion se expresa SOLO en toneladas (TM) y sacos de "
                "50 kg de harina, NUNCA en dinero. "
                "Estructura EXACTA (usa estos titulos en mayusculas):\n"
                "RESUMEN EJECUTIVO\n(5-7 lineas, lo mas importante primero)\n"
                "HALLAZGOS DEL PERIODO\n(6-9 vinetas: dato -> interpretacion -> accion concreta)\n"
                "IMPACTO EN PRODUCCION\n(si hay datos: TM y sacos no producidos, % de la "
                "capacidad y de la meta, areas y equipos responsables, comparacion con el "
                "periodo anterior; explica que el calculo sale de la capacidad real de cada "
                "equipo detenido)\n"
                "TENDENCIA Y COMPARACION\n(4-6 lineas sobre la evolucion de los indicadores: "
                "MTBF, MTTR, disponibilidad, % proactivo, y el comportamiento semana a semana)\n"
                "PLAN RESTO DEL MES Y PROXIMO MES\n(prioridades de la programacion y que pedir a "
                "produccion: ventanas de parada, coordinaciones)\n"
                "RIESGOS SI NO SE ACTUA\n(3-4 vinetas)\n"
                "Tono directo y gerencial. Sin markdown de codigo, sin tablas."
            )

            from bot.llm import _get_deepseek_config
            key, url = _get_deepseek_config()
            if not key:
                return jsonify({'error': 'DEEPSEEK_API_KEY no configurada en el servidor'}), 501

            import threading
            import time as _t
            import uuid
            from models import NarrativeJob
            _limpiar_jobs()

            prompt_usuario = "\n".join(resumen)
            scope = (f"{mt.get('desde')}..{mt.get('hasta')}")[:60]

            if not request.args.get('forzar'):
                ahora = dt.datetime.utcnow()
                # Ya hay un analisis reciente de este MISMO periodo: se
                # devuelve en vez de esperar (y pagar) una generacion igual.
                previo = (NarrativeJob.query
                          .filter_by(scope=scope, status='OK')
                          .filter(NarrativeJob.created_at >= ahora - dt.timedelta(hours=6))
                          .order_by(NarrativeJob.created_at.desc()).first())
                if previo:
                    return jsonify({'job_id': previo.id, 'status': 'OK',
                                    'narrativa': previo.narrativa, 'reutilizado': True})
                # O hay uno CORRIENDO del mismo periodo: se reengancha a el en
                # vez de lanzar un segundo analisis en paralelo. Asi, si el
                # navegador se canso de esperar, al volver a pulsar retoma.
                corriendo = (NarrativeJob.query
                             .filter_by(scope=scope, status='PENDIENTE')
                             .filter(NarrativeJob.created_at >= ahora - dt.timedelta(minutes=30))
                             .order_by(NarrativeJob.created_at.desc()).first())
                if corriendo:
                    return jsonify({'job_id': corriendo.id, 'status': 'PENDIENTE',
                                    'reenganchado': True,
                                    'prompt_chars': corriendo.prompt_chars,
                                    'espera_estimada_s': max(
                                        30, 240 - int((ahora - corriendo.created_at).total_seconds()))})

            # Cuanto mas ancho el periodo, mas datos lleva el prompt y mas
            # tarda el modelo. El limite de lectura se ajusta al tamano en vez
            # de ser un numero fijo que se quedaba corto en rangos largos.
            n_chars = len(prompt_usuario)
            read_timeout = min(1500, max(600, int(n_chars / 4)))

            job_id = uuid.uuid4().hex[:12]
            job = NarrativeJob(id=job_id, status='PENDIENTE', scope=scope,
                               prompt_chars=n_chars)
            db.session.add(job)
            db.session.commit()

            def _worker():
                import requests as _rq
                t0 = _t.time()
                try:
                    r = _rq.post(url, headers={
                        'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                    }, json={
                        'model': DEEPSEEK_MODEL,
                        'messages': [
                            {'role': 'system', 'content': system_prompt},
                            {'role': 'user', 'content': prompt_usuario},
                        ],
                        'max_tokens': 3000, 'temperature': 0.3,
                        'thinking': DEEPSEEK_THINKING,
                        # (conectar, leer): el modelo puede tardar minutos en
                        # redactar; lo que no puede es dejar de responder.
                    }, timeout=(30, read_timeout))
                    tardo = round(_t.time() - t0, 1)
                    if r.status_code != 200:
                        _job_set(job_id, status='ERROR', elapsed_s=tardo,
                                 error=f'DeepSeek HTTP {r.status_code}: {r.text[:300]}')
                        return
                    texto = r.json()['choices'][0]['message']['content']
                    _job_set(job_id, status='OK', narrativa=texto, elapsed_s=tardo)
                    logger.info('narrativa %s lista en %ss (%s chars de prompt)',
                                job_id, tardo, n_chars)
                except _rq.exceptions.ReadTimeout:
                    _job_set(job_id, status='ERROR',
                             elapsed_s=round(_t.time() - t0, 1),
                             error=f'La IA dejo de responder tras {read_timeout // 60} minutos. '
                                   f'Prueba con un periodo mas corto.')
                except Exception as e:
                    _job_set(job_id, status='ERROR',
                             elapsed_s=round(_t.time() - t0, 1), error=str(e)[:400])

            threading.Thread(target=_worker, daemon=True).start()
            return jsonify({'job_id': job_id, 'status': 'PENDIENTE',
                            'prompt_chars': n_chars,
                            'espera_estimada_s': min(600, max(60, n_chars // 12))})
        except Exception as e:
            db.session.rollback()
            logger.exception('diagnostico_narrativa error')
            return jsonify({'error': str(e)}), 500

    # ── Informe HTML descargable (plantilla ejecutiva autocontenida) ──────

    @app.route('/api/diagnostico/informe', methods=['GET'])
    def diagnostico_informe():
        """Documento HTML autocontenido del diagnostico: se descarga, se
        abre sin conexion en cualquier lugar y se imprime a PDF desde el
        navegador. Siempre la misma plantilla, datos en vivo del mes pedido.

        Query: month=YYYY-MM (periodo elegido por el usuario),
               download=1 fuerza la descarga como archivo,
               narrativa_job=<id> incrusta la narrativa IA ya generada.
        """
        try:
            d = _build_diagnostico(request.args.get('month'),
                                   request.args.get('desde'),
                                   request.args.get('hasta'))
            narrativa = ''
            job = _job_get((request.args.get('narrativa_job') or '').strip())
            if job and job.status == 'OK':
                narrativa = job.narrativa or ''
            html = render_template('informe_diagnostico.html', d=d, narrativa=narrativa)
            resp = app.make_response(html)
            resp.headers['Content-Type'] = 'text/html; charset=utf-8'
            if request.args.get('download') == '1':
                fname = ("Diagnostico_Gestion_Mantenimiento_"
                         + d['meta']['label'].replace(' ', '_') + ".html")
                resp.headers['Content-Disposition'] = f'attachment; filename="{fname}"'
            return resp
        except Exception as e:
            logger.exception('diagnostico_informe error')
            return jsonify({'error': str(e)}), 500
