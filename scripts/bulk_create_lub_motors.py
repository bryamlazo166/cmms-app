#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Crear masivamente puntos de lubricacion y motores faltantes.

Que hace:
  1) Para cada componente cuyo nombre contiene "chumacera" o "cadena" y
     NO tiene un lubrication_point asociado (por component_id) -> lo crea.
     El lubricante, frecuencia y cantidad se copian del punto mas comun
     del MISMO equipo + mismo tipo. Si no hay en el equipo, busca en la
     misma linea, despues area, despues global. Si no hay nada, default
     seguro: lubricant_name=None, frequency_days=30, quantity=None.

  2) Para cada equipo que tenga al menos 1 chumacera o 1 cadena pero
     que NO tenga un rotative_asset con categoria 'Motor electrico'
     -> crea uno placeholder. Misma logica para 'Motorreductor'.
     Solo se crea PLACEHOLDER: nombre + categoria + equipo_id + status
     'Instalado'. Marca/modelo/serie quedan vacios para que tu los
     llenes despues desde la UI de Activos Rotativos.

Uso:
    # DRY RUN (default) - solo lista lo que va a crear, no escribe nada
    python scripts/bulk_create_lub_motors.py

    # APLICA cambios a la BD (la que apunte DATABASE_URL)
    python scripts/bulk_create_lub_motors.py --apply

    # Solo lubricacion (no toca motores)
    python scripts/bulk_create_lub_motors.py --apply --only-lub

    # Solo motores (no toca lubricacion)
    python scripts/bulk_create_lub_motors.py --apply --only-motors

    # Acotar a un equipo / linea / area especifico
    python scripts/bulk_create_lub_motors.py --apply --area "COCCION"
    python scripts/bulk_create_lub_motors.py --apply --equipment-id 42

Seguridad:
  - Transaccional: si algo falla, hace rollback de TODO.
  - Idempotente: corre N veces y solo crea lo que falta.
  - Antes de --apply, RECOMENDADO hacer backup:
        python scripts/backup_db.py
"""
import os
import sys
import argparse
from collections import Counter
from pathlib import Path

# Asegurar import de modulos del proyecto
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from app import app  # noqa: E402
from database import db  # noqa: E402
from models import (  # noqa: E402
    Area, Line, Equipment, System, Component,
    LubricationPoint, RotativeAsset,
)

# Categorias canonicas (case sensitive como las usa la UI)
CAT_MOTOR = 'Motor electrico'
CAT_MOTORRED = 'Motorreductor'

# Default seguro para puntos de lubricacion sin plantilla
DEFAULT_FREQ_DAYS = 30
DEFAULT_QTY_UNIT = 'g'  # gramos para grasa (la mayoria de chumaceras)


def _is_guarda(name: str) -> bool:
    """True si el componente es una GUARDA (proteccion metalica) y NO se
    lubrica. Ejemplos: 'GUARDA PARA CHUMACERA', 'GUARDA CADENA', 'GUARDA
    MOTOR'. La heuristica: la palabra 'GUARDA' aparece como token."""
    n = (name or '').strip().lower()
    # 'guarda' como palabra completa al inicio o despues de espacio
    tokens = n.replace(',', ' ').replace('-', ' ').split()
    return 'guarda' in tokens or 'guardas' in tokens


def _is_chumacera(name: str) -> bool:
    n = (name or '').strip().lower()
    if _is_guarda(name):
        return False
    return 'chumacera' in n


def _is_cadena(name: str) -> bool:
    n = (name or '').strip().lower()
    if _is_guarda(name):
        return False
    return 'cadena' in n


def _kind_of(name: str) -> str | None:
    """Devuelve 'chumacera' o 'cadena' segun el nombre del componente.
    Devuelve None para guardas (protecciones), cualquier otro componente,
    o cuando es ambiguo."""
    if _is_chumacera(name):
        return 'chumacera'
    if _is_cadena(name):
        return 'cadena'
    return None


def _next_lub_code() -> str:
    """Genera el siguiente codigo LUB-NNNN. Toma el max actual y +1."""
    rows = LubricationPoint.query.with_entities(LubricationPoint.code).all()
    max_n = 0
    for (c,) in rows:
        if not c:
            continue
        s = c.strip().upper()
        if s.startswith('LUB-'):
            try:
                n = int(s.split('-', 1)[1])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return f"LUB-{max_n + 1:04d}"


def _next_rotative_code() -> str:
    """Genera el siguiente codigo RA-NNNN."""
    rows = RotativeAsset.query.with_entities(RotativeAsset.code).all()
    max_n = 0
    for (c,) in rows:
        if not c:
            continue
        s = c.strip().upper()
        if s.startswith('RA-'):
            try:
                n = int(s.split('-', 1)[1])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return f"RA-{max_n + 1:04d}"


def _mode_or_first(values):
    """Devuelve el valor mas comun (excluyendo None/vacios)."""
    clean = [v for v in values if v not in (None, '', 0)]
    if not clean:
        return None
    return Counter(clean).most_common(1)[0][0]


def _find_template(component, kind: str, all_points):
    """Busca plantilla de lubricante/freq/qty para un componente del tipo dado.
    Orden: mismo equipo -> misma linea -> misma area -> global. Filtra por
    'kind' (chumacera o cadena) mirando el nombre del componente del punto."""
    equipment_id = None
    line_id = None
    area_id = None
    if component.system and component.system.equipment:
        eq = component.system.equipment
        equipment_id = eq.id
        line_id = eq.line_id
        if eq.line and eq.line.area_id:
            area_id = eq.line.area_id

    def _matches(pt):
        # Solo puntos cuyo componente sea del mismo kind
        if not pt.component:
            return False
        return _kind_of(pt.component.name) == kind

    scopes = [
        ('equipo',  lambda p: p.equipment_id == equipment_id),
        ('linea',   lambda p: p.line_id == line_id),
        ('area',    lambda p: p.area_id == area_id),
        ('global',  lambda p: True),
    ]
    for scope_name, scope_filter in scopes:
        candidates = [p for p in all_points if scope_filter(p) and _matches(p)]
        if candidates:
            lub = _mode_or_first([p.lubricant_name for p in candidates])
            freq = _mode_or_first([p.frequency_days for p in candidates]) or DEFAULT_FREQ_DAYS
            qty = _mode_or_first([p.quantity_nominal for p in candidates])
            unit = _mode_or_first([p.quantity_unit for p in candidates]) or DEFAULT_QTY_UNIT
            return {
                'lubricant_name': lub,
                'frequency_days': int(freq),
                'quantity_nominal': qty,
                'quantity_unit': unit,
                'source': scope_name,
            }
    return {
        'lubricant_name': None,
        'frequency_days': DEFAULT_FREQ_DAYS,
        'quantity_nominal': None,
        'quantity_unit': DEFAULT_QTY_UNIT,
        'source': 'default',
    }


def _equipment_filter(args):
    """Construye un filtro SQLAlchemy para acotar a un area/linea/equipo."""
    q = Equipment.query
    if args.equipment_id:
        q = q.filter(Equipment.id == args.equipment_id)
    if args.line:
        q = q.join(Line, Equipment.line_id == Line.id).filter(Line.name.ilike(f'%{args.line}%'))
    if args.area:
        q = q.join(Line, Equipment.line_id == Line.id) \
             .join(Area, Line.area_id == Area.id) \
             .filter(Area.name.ilike(f'%{args.area}%'))
    return q


def run_lubrication(args, log):
    log("\n===== FASE 1: PUNTOS DE LUBRICACION FALTANTES =====")

    # Universo de componentes chumacera/cadena en equipos del scope
    eq_ids = {e.id for e in _equipment_filter(args).all()}
    if not eq_ids:
        log("  (sin equipos en el scope)")
        return 0

    components = (
        Component.query
        .join(System, Component.system_id == System.id)
        .filter(System.equipment_id.in_(eq_ids))
        .all()
    )

    targets = [c for c in components if _kind_of(c.name)]
    log(f"  Componentes chumacera/cadena en scope: {len(targets)}")

    # Cargar lubrication_points existentes una sola vez (para plantillas + check)
    all_points = LubricationPoint.query.filter(LubricationPoint.is_active == True).all()
    existing_component_ids = {p.component_id for p in all_points if p.component_id}

    to_create = [c for c in targets if c.id not in existing_component_ids]
    log(f"  Ya tienen punto: {len(targets) - len(to_create)}")
    log(f"  Faltan crear:    {len(to_create)}")
    if not to_create:
        return 0

    created = 0
    log("\n  Detalle de creacion:")
    log(f"  {'Area':<14} {'Linea':<18} {'Equipo':<28} {'Componente':<40} {'Lubricante':<22} {'Freq':>4} {'Origen':<8}")
    log(f"  {'-'*14} {'-'*18} {'-'*28} {'-'*40} {'-'*22} {'-'*4} {'-'*8}")

    next_code_n = None  # se calcula al primer uso

    for c in sorted(to_create, key=lambda x: (
            x.system.equipment.name if (x.system and x.system.equipment) else '',
            x.name)):
        kind = _kind_of(c.name)
        tpl = _find_template(c, kind, all_points)

        eq = c.system.equipment if c.system else None
        eq_name = eq.name if eq else '(sin equipo)'
        eq_id = eq.id if eq else None
        line_id = eq.line_id if eq else None
        line_name = eq.line.name if (eq and eq.line) else '(sin linea)'
        area_id = eq.line.area_id if (eq and eq.line) else None
        area_name = eq.line.area.name if (eq and eq.line and eq.line.area) else '(sin area)'

        if next_code_n is None:
            base = _next_lub_code()
            next_code_n = int(base.split('-', 1)[1])
            code = base
        else:
            next_code_n += 1
            code = f"LUB-{next_code_n:04d}"

        log(f"  {area_name[:14]:<14} {line_name[:18]:<18} {eq_name[:28]:<28} {c.name[:40]:<40} "
            f"{(tpl['lubricant_name'] or '(vacio)')[:22]:<22} "
            f"{tpl['frequency_days']:>4} "
            f"{tpl['source']:<8}")

        if args.apply:
            point = LubricationPoint(
                code=code,
                name=f"Lubricacion {c.name}",
                description=f"Punto generado automaticamente para {kind} '{c.name}'",
                area_id=area_id,
                line_id=line_id,
                equipment_id=eq_id,
                system_id=c.system_id,
                component_id=c.id,
                lubricant_name=tpl['lubricant_name'],
                quantity_nominal=tpl['quantity_nominal'],
                quantity_unit=tpl['quantity_unit'],
                frequency_days=tpl['frequency_days'],
                warning_days=3,
                semaphore_status='PENDIENTE',
                is_active=True,
            )
            db.session.add(point)
            # Lo agregamos al cache para que las siguientes plantillas
            # puedan usarlo si comparten equipo/linea/area.
            all_points.append(point)
        created += 1

    return created


def run_motors(args, log):
    log("\n===== FASE 2: MOTORES ELECTRICOS / MOTORREDUCTORES FALTANTES =====")

    eq_ids = {e.id for e in _equipment_filter(args).all()}
    if not eq_ids:
        log("  (sin equipos en el scope)")
        return 0

    # Equipos con chumaceras/cadenas (rotativos) -> deben tener motor
    eqs_with_rotating = set()
    components = (
        Component.query
        .join(System, Component.system_id == System.id)
        .filter(System.equipment_id.in_(eq_ids))
        .all()
    )
    for c in components:
        if _kind_of(c.name) and c.system and c.system.equipment_id:
            eqs_with_rotating.add(c.system.equipment_id)

    log(f"  Equipos rotativos (con chumacera/cadena) en scope: {len(eqs_with_rotating)}")

    # Si --th-only, restringir a equipos cuyo nombre empieza con "TH" + espacio
    # o "TH" seguido de digito (TH1, TH ALIMENTADOR, TH 1 SALIDA, etc.).
    # Excluye "OTHER", "WITH", etc. exigiendo TH al inicio del nombre.
    if args.th_only:
        eqs_all = {e.id: e for e in Equipment.query.filter(Equipment.id.in_(eqs_with_rotating)).all()}
        before = len(eqs_with_rotating)
        def _is_th(name: str) -> bool:
            n = (name or '').strip().upper()
            return n == 'TH' or n.startswith('TH ') or (len(n) >= 3 and n.startswith('TH') and n[2].isdigit())
        eqs_with_rotating = {eid for eid in eqs_with_rotating if _is_th(eqs_all[eid].name)}
        log(f"  Filtro --th-only aplicado: {before} -> {len(eqs_with_rotating)} equipos TH")

    if not eqs_with_rotating:
        return 0

    # Motores existentes por equipo
    rotative = (
        RotativeAsset.query
        .filter(RotativeAsset.equipment_id.in_(eqs_with_rotating))
        .all()
    )
    has_motor = {}     # eq_id -> bool
    has_redmot = {}    # eq_id -> bool
    for ra in rotative:
        cat = (ra.category or '').strip().lower()
        if 'reductor' in cat or 'motorreductor' in cat:
            has_redmot[ra.equipment_id] = True
        elif 'motor' in cat:
            has_motor[ra.equipment_id] = True

    # Mapa de equipos
    eqs = {e.id: e for e in Equipment.query.filter(Equipment.id.in_(eqs_with_rotating)).all()}

    created = 0
    log("\n  Detalle de creacion:")
    log(f"  {'Area':<14} {'Linea':<18} {'Equipo':<28} {'Categoria a crear':<22} {'Codigo':<10}")
    log(f"  {'-'*14} {'-'*18} {'-'*28} {'-'*22} {'-'*10}")

    next_code_n = None

    def _alloc_code():
        nonlocal next_code_n
        if next_code_n is None:
            base = _next_rotative_code()
            next_code_n = int(base.split('-', 1)[1])
            return base
        next_code_n += 1
        return f"RA-{next_code_n:04d}"

    for eq_id in sorted(eqs_with_rotating):
        eq = eqs.get(eq_id)
        if not eq:
            continue

        needs_motor = not has_motor.get(eq_id)
        needs_redmot = not has_redmot.get(eq_id)

        if not needs_motor and not needs_redmot:
            continue

        line_name = eq.line.name if eq.line else '(sin linea)'
        area_name = eq.line.area.name if (eq.line and eq.line.area) else '(sin area)'

        for need, category, label in (
            (needs_motor,  CAT_MOTOR,    'Motor electrico'),
            (needs_redmot, CAT_MOTORRED, 'Motorreductor'),
        ):
            if not need:
                continue
            code = _alloc_code()
            log(f"  {area_name[:14]:<14} {line_name[:18]:<18} {eq.name[:28]:<28} {label:<22} {code:<10}")
            if args.apply:
                asset = RotativeAsset(
                    code=code,
                    name=f"{label} {eq.name}",
                    category=category,
                    status='Instalado',
                    is_active=True,
                    area_id=eq.line.area_id if eq.line else None,
                    line_id=eq.line_id,
                    equipment_id=eq.id,
                    notes='Placeholder generado automaticamente. Completar marca/modelo/serie.',
                )
                db.session.add(asset)
            created += 1

    return created


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true',
                        help='Aplica los cambios. Sin esta flag es DRY RUN.')
    parser.add_argument('--only-lub', action='store_true',
                        help='Solo procesa puntos de lubricacion.')
    parser.add_argument('--only-motors', action='store_true',
                        help='Solo procesa motores/motorreductores.')
    parser.add_argument('--equipment-id', type=int, default=None,
                        help='Acotar a un equipment_id especifico.')
    parser.add_argument('--line', type=str, default=None,
                        help='Acotar por nombre de linea (LIKE).')
    parser.add_argument('--area', type=str, default=None,
                        help='Acotar por nombre de area (LIKE).')
    parser.add_argument('--th-only', action='store_true',
                        help='En FASE 2: solo crear motores/motorreductores '
                             'para equipos cuyo nombre empieza con "TH" '
                             '(transportadores helicoidales / sinfines).')
    parser.add_argument('--log-file', type=str, default=None,
                        help='Guarda el log en archivo (ademas de stdout).')
    args = parser.parse_args()

    log_lines = []
    def log(msg=''):
        print(msg)
        log_lines.append(msg)

    mode = 'APPLY (escribe a BD)' if args.apply else 'DRY RUN (no escribe)'
    log(f"=== bulk_create_lub_motors.py === {mode}")
    db_url = os.getenv('DATABASE_URL', '(no DATABASE_URL)')
    # Ocultar password si esta en la URL
    if '@' in db_url:
        masked = db_url.split('@', 1)[0].rsplit(':', 1)[0] + ':****@' + db_url.split('@', 1)[1]
    else:
        masked = db_url
    log(f"DATABASE_URL: {masked}")

    with app.app_context():
        total_lub = 0
        total_motors = 0
        try:
            if not args.only_motors:
                total_lub = run_lubrication(args, log)
            if not args.only_lub:
                total_motors = run_motors(args, log)

            if args.apply:
                db.session.commit()
                log(f"\n[OK] Cambios aplicados. Lubricacion creados: {total_lub}, Motores creados: {total_motors}")
            else:
                db.session.rollback()
                log(f"\n[DRY-RUN] Cambios NO aplicados. Lubricacion que crearia: {total_lub}, Motores que crearia: {total_motors}")
                log("Para aplicar, repite con --apply.")
        except Exception as e:
            db.session.rollback()
            log(f"\n[ERROR] {type(e).__name__}: {e}")
            log("Rollback hecho. No se modifico nada.")
            raise

    if args.log_file:
        Path(args.log_file).write_text('\n'.join(log_lines), encoding='utf-8')
        print(f"\nLog guardado en: {args.log_file}")


if __name__ == '__main__':
    main()
