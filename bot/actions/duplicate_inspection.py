"""Accion: duplicar ruta de inspeccion a uno o varios equipos."""
import logging

logger = logging.getLogger(__name__)


def duplicate_inspection_route(app, data):
    """Duplica una ruta de inspeccion a equipos destino.

    data esperada:
      - source_route_code | source_route_id: ruta origen
      - target_equipment_tags: lista de tags (ej: ["D6", "D7"])
      - target_equipment_ids: alternativa por id
      - frequency_days, warning_days: opcionales (override)
      - code_template, name_template: opcionales

    Returns: (result_dict, error | None) donde result_dict contiene
    source/created/skipped igual que el endpoint REST.
    """
    with app.app_context():
        from database import db as _db
        from sqlalchemy import text as _text
        try:
            source_id = data.get('source_route_id')
            source_code = (data.get('source_route_code') or '').strip()
            if not source_id and not source_code:
                return None, "Falta source_route_code o source_route_id"

            # Resolver source_id si solo tenemos codigo
            if not source_id and source_code:
                row = _db.session.execute(_text("""
                    SELECT id FROM inspection_routes WHERE code = :c LIMIT 1
                """), {"c": source_code}).fetchone()
                if not row:
                    return None, f"Ruta '{source_code}' no encontrada"
                source_id = row[0]

            # Resolver target_equipment_ids desde tags si vienen como texto
            target_ids = list(data.get('target_equipment_ids') or [])
            target_tags = data.get('target_equipment_tags') or []
            for tag in target_tags:
                if not tag:
                    continue
                tag_norm = str(tag).strip().upper()
                eq_row = _db.session.execute(_text("""
                    SELECT id FROM equipments WHERE UPPER(tag) = :t LIMIT 1
                """), {"t": tag_norm}).fetchone()
                if eq_row and eq_row[0] not in target_ids:
                    target_ids.append(eq_row[0])

            if not target_ids:
                return None, "No se pudo resolver ningun equipo destino"

            # Llamar al endpoint REST internamente para reusar la logica
            client = app.test_client()
            body = {
                'target_equipment_ids': target_ids,
                'code_template': data.get('code_template') or None,
                'name_template': data.get('name_template') or None,
                'frequency_days': data.get('frequency_days'),
                'warning_days': data.get('warning_days'),
                'copy_items': data.get('copy_items', True),
            }
            resp = client.post(
                f'/api/inspection/routes/{source_id}/duplicate',
                json=body,
                content_type='application/json',
            )
            if resp.status_code != 201:
                payload = resp.get_json() or {}
                return None, payload.get('error') or f"HTTP {resp.status_code}"
            return resp.get_json(), None
        except Exception as e:
            logger.exception("duplicate_inspection_route (bot) error")
            return None, str(e)
