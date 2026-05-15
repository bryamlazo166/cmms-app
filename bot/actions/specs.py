"""Accion: replicar especificaciones tecnicas entre equipos o componentes."""
import logging

logger = logging.getLogger(__name__)


def replicate_specs(app, data):
    """Replica las specs (tecnicas) de un componente o equipo a otro.

    data esperado:
      - source_equipment_tag, source_component_name (entity_type='component')
        o solo source_equipment_tag (entity_type='equipment')
      - target_equipment_tag, target_component_name (idem destino)
      - mode: 'merge' (default) | 'replace'
      - overwrite: bool (solo aplica con merge)
      - entity_type: 'component' (default) | 'equipment'

    Returns: (resumen_str, error_str | None).
    """
    from bot.resolvers import smart_component_match as _smart_component_match
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text
        try:
            entity_type = (data.get('entity_type') or 'component').lower()
            if entity_type not in ('component', 'equipment'):
                return None, "entity_type debe ser 'component' o 'equipment'"
            mode = (data.get('mode') or 'merge').lower()
            if mode not in ('merge', 'replace'):
                return None, "mode debe ser 'merge' o 'replace'"
            overwrite = bool(data.get('overwrite', False))

            def resolve(prefix):
                """Resuelve (eq_id, comp_id, sys_id, tag) para origen o destino.

                CRITICAL: si el usuario/LLM proveyo un tag explicito y NO existe
                en BD, devolvemos eq_id=None SIN fallback fuzzy. Esto evita que
                copiemos specs al equipo equivocado por similitud de nombre
                (caso: usuario pide TH6, LLM substituye por TH5).

                Si viene `<prefix>_system_name` (ej: 'exhaustor'), se pasa
                como system_hint al matcher para desambiguar cuando un equipo
                tiene el mismo componente en varios sistemas.
                """
                tag = (data.get(f'{prefix}_equipment_tag') or '').strip()
                comp_name = (data.get(f'{prefix}_component_name') or '').strip()
                sys_hint = (data.get(f'{prefix}_system_name') or '').strip() or None
                eq_id = comp_id = sys_id = None
                tag_provided = bool(tag)
                if tag:
                    r = _db.session.execute(
                        text("SELECT id FROM equipments WHERE UPPER(tag) = UPPER(:t)"),
                        {"t": tag}
                    ).fetchone()
                    if r:
                        eq_id = r[0]
                if not eq_id and not tag_provided and data.get(f'{prefix}_equipment_name'):
                    r = _db.session.execute(
                        text("SELECT id FROM equipments WHERE LOWER(name) LIKE :n LIMIT 1"),
                        {"n": f"%{data[f'{prefix}_equipment_name'].lower()}%"}
                    ).fetchone()
                    if r:
                        eq_id = r[0]
                if eq_id and comp_name and entity_type == 'component':
                    res = _smart_component_match(_db, text, eq_id, comp_name,
                                                 system_hint=sys_hint)
                    if res:
                        comp_id, sys_id = res[0], res[1]
                return eq_id, comp_id, sys_id, tag

            src_eq, src_comp, src_sys, src_tag = resolve('source')
            tgt_eq, tgt_comp, tgt_sys, tgt_tag = resolve('target')

            if src_tag and not src_eq:
                near = _db.session.execute(
                    text("SELECT tag FROM equipments WHERE UPPER(tag) LIKE UPPER(:t) ORDER BY tag LIMIT 5"),
                    {"t": f"%{src_tag}%"}
                ).fetchall()
                hint = (' Tags similares: ' + ', '.join(r[0] for r in near)) if near else ''
                return None, f"Equipo origen '{src_tag}' no existe.{hint}"
            if tgt_tag and not tgt_eq:
                near = _db.session.execute(
                    text("SELECT tag FROM equipments WHERE UPPER(tag) LIKE UPPER(:t) ORDER BY tag LIMIT 5"),
                    {"t": f"%{tgt_tag}%"}
                ).fetchall()
                hint = (' Tags similares: ' + ', '.join(r[0] for r in near)) if near else ''
                return None, f"Equipo destino '{tgt_tag}' no existe.{hint}"

            if entity_type == 'component':
                if not src_comp:
                    return None, f"No encontre el componente origen ({data.get('source_component_name')} en {data.get('source_equipment_tag')})"
                if not tgt_comp:
                    return None, f"No encontre el componente destino ({data.get('target_component_name')} en {data.get('target_equipment_tag')})"
                if src_comp == tgt_comp:
                    return None, "Origen y destino son el mismo componente"
                source_id, target_id = src_comp, tgt_comp
                table = 'component_specs'
                fk = 'component_id'
                # Incluir nombre del sistema para que el label distinga entre
                # componentes con el mismo nombre en sistemas distintos
                # (ej: "SECA-SECA2/EXHAUSTOR/CHUMACERA MOTRIZ").
                names = _db.session.execute(text("""
                    SELECT c.id, e.tag, s.name, c.name FROM components c
                    JOIN systems s ON c.system_id = s.id
                    JOIN equipments e ON s.equipment_id = e.id
                    WHERE c.id IN (:s, :t)
                """), {"s": source_id, "t": target_id}).fetchall()
                name_map = {r[0]: f"{r[1]}/{r[2]}/{r[3]}" for r in names}
                src_label = name_map.get(source_id, str(source_id))
                tgt_label = name_map.get(target_id, str(target_id))
            else:
                if not src_eq or not tgt_eq:
                    return None, "Faltan source_equipment_tag y/o target_equipment_tag"
                if src_eq == tgt_eq:
                    return None, "Origen y destino son el mismo equipo"
                source_id, target_id = src_eq, tgt_eq
                table = 'equipment_specs'
                fk = 'equipment_id'
                tags = _db.session.execute(
                    text("SELECT id, tag FROM equipments WHERE id IN (:s, :t)"),
                    {"s": source_id, "t": target_id}
                ).fetchall()
                tmap = {r[0]: r[1] for r in tags}
                src_label = tmap.get(source_id, str(source_id))
                tgt_label = tmap.get(target_id, str(target_id))

            src_specs = _db.session.execute(text(f"""
                SELECT id, key_name, value_text, unit, order_index
                FROM {table} WHERE {fk} = :id ORDER BY order_index
            """), {"id": source_id}).fetchall()
            if not src_specs:
                # Sugerencia inteligente para entity_type='component':
                # si hay OTROS componentes en el mismo equipo con el mismo
                # nombre y CON specs, listarlos. Asi el usuario puede pedir
                # explicitamente el sistema correcto.
                hint = ""
                if entity_type == 'component' and src_comp:
                    try:
                        siblings = _db.session.execute(text("""
                            SELECT c.id, s.name AS sys_name, c.name AS comp_name,
                                   (SELECT count(*) FROM component_specs cs WHERE cs.component_id = c.id) AS n_specs
                            FROM components c
                            JOIN systems s ON c.system_id = s.id
                            WHERE s.equipment_id = :eid
                              AND LOWER(c.name) = (SELECT LOWER(name) FROM components WHERE id = :cid)
                              AND c.id != :cid
                        """), {"eid": src_eq, "cid": src_comp}).fetchall()
                        with_specs = [s for s in siblings if s[3] > 0]
                        if with_specs:
                            opts = ', '.join(f"sistema '{s[1]}' ({s[3]} specs)" for s in with_specs)
                            hint = f"\nOtros componentes con el mismo nombre en el equipo SI tienen specs: {opts}.\nReintenta indicando el sistema. Ej: 'copia las specs de la chumacera motriz del exhaustor del secador 2 a ...'."
                    except Exception:
                        pass
                return None, f"El origen {src_label} no tiene specs cargadas.{hint}"

            if mode == 'replace':
                _db.session.execute(text(f"DELETE FROM {table} WHERE {fk} = :id"), {"id": target_id})

            existing_rows = _db.session.execute(text(f"""
                SELECT id, key_name, order_index FROM {table} WHERE {fk} = :id
            """), {"id": target_id}).fetchall()
            existing = {r[1].strip().lower(): r[0] for r in existing_rows}
            max_order = max((r[2] for r in existing_rows), default=0)

            copied = overwritten = skipped = 0
            for s in src_specs:
                key_norm = s[1].strip().lower()
                if key_norm in existing:
                    if mode == 'merge' and overwrite:
                        _db.session.execute(text(f"""
                            UPDATE {table} SET value_text = :v, unit = :u WHERE id = :id
                        """), {"v": s[2], "u": s[3], "id": existing[key_norm]})
                        overwritten += 1
                    else:
                        skipped += 1
                    continue
                max_order += 1
                _db.session.execute(text(f"""
                    INSERT INTO {table} ({fk}, key_name, value_text, unit, order_index)
                    VALUES (:id, :k, :v, :u, :o)
                """), {"id": target_id, "k": s[1], "v": s[2], "u": s[3], "o": max_order})
                copied += 1

            _db.session.commit()
            _db.session.remove()
            summary = (f"{src_label} -> {tgt_label}\n"
                       f"Copiadas: {copied} | "
                       f"Sobreescritas: {overwritten} | "
                       f"Omitidas: {skipped} (de {len(src_specs)} en origen)")
            return summary, None
        except Exception as e:
            _db.session.rollback()
            try:
                _db.session.remove()
            except Exception:
                pass
            logger.error(f"replicate_specs error: {e}")
            return None, str(e)
