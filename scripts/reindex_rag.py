"""Reindexa en bot_embeddings (SINCRONO):
  - Todos los DocumentLink existentes (manuales, planos, fichas, informes).
  - OTs cerradas existentes (para capturar URLs incrustadas en execution_comments).

Ejecutar una sola vez despues del deploy. No duplica: usa ON CONFLICT.
"""
import os
from app import app

with app.app_context():
    from database import db
    from models import (
        DocumentLink, WorkOrder, MaintenanceNotice, Area, Line, Equipment,
        System, Component, RotativeAsset,
    )
    from utils.embeddings import (
        upsert_embedding, build_ot_text, build_document_link_text,
    )

    if not os.getenv('OPENAI_API_KEY'):
        print("OPENAI_API_KEY no esta seteada. Aborto.")
        raise SystemExit(1)

    # 1) DocumentLinks
    docs = DocumentLink.query.all()
    print(f"Indexando {len(docs)} DocumentLinks...")
    for doc in docs:
        parent_name = None; parent_tag = None
        category = None; brand = None; model = None
        area_name = None; line_name = None
        if doc.entity_type == 'rotative_asset':
            ra = RotativeAsset.query.get(doc.entity_id)
            if ra:
                parent_name = ra.name; parent_tag = ra.code
                category = ra.category; brand = ra.brand; model = ra.model
                area_name = ra.area.name if ra.area else None
                line_name = ra.line.name if ra.line else None
        elif doc.entity_type == 'equipment':
            eq = Equipment.query.get(doc.entity_id)
            if eq:
                parent_name = eq.name; parent_tag = eq.tag
                area_name = eq.area.name if getattr(eq, 'area', None) else None
                line_name = eq.line.name if getattr(eq, 'line', None) else None
        elif doc.entity_type == 'component':
            co = Component.query.get(doc.entity_id)
            if co:
                parent_name = co.name
        text = build_document_link_text(
            doc.to_dict(), parent_name=parent_name, parent_tag=parent_tag,
            parent_type=doc.entity_type, category=category, brand=brand, model=model,
            area=area_name, line=line_name,
        )
        metadata = {
            'url': doc.url, 'title': doc.title, 'doc_type': doc.doc_type,
            'parent_type': doc.entity_type, 'parent_id': doc.entity_id,
            'parent_tag': parent_tag, 'parent_name': parent_name,
        }
        ok = upsert_embedding(db.session, 'document_link', doc.id, text, metadata)
        print(f"  [{doc.id}] {doc.title[:50]!r} -> {'OK' if ok else 'FAIL'}")
    db.session.commit()

    # 2) OTs cerradas (para reextraer URLs en bitacora)
    wos = WorkOrder.query.filter_by(status='Cerrada').all()
    print(f"Reindexando {len(wos)} OTs cerradas...")
    for wo in wos:
        eq = Equipment.query.get(wo.equipment_id) if wo.equipment_id else None
        ar = Area.query.get(wo.area_id) if wo.area_id else None
        ln = Line.query.get(wo.line_id) if wo.line_id else None
        sy = System.query.get(wo.system_id) if wo.system_id else None
        co = Component.query.get(wo.component_id) if wo.component_id else None
        notice = MaintenanceNotice.query.get(wo.notice_id) if wo.notice_id else None
        text = build_ot_text(wo.to_dict(), equipment=eq, area=ar, line=ln,
                             system=sy, component=co, notice=notice)
        metadata = {
            'code': wo.code,
            'equipment_tag': eq.tag if eq else None,
            'failure_mode': wo.failure_mode,
        }
        ok = upsert_embedding(db.session, 'work_order', wo.id, text, metadata)
        print(f"  [{wo.code}] -> {'OK' if ok else 'FAIL'}")
    db.session.commit()
    print("Listo.")
