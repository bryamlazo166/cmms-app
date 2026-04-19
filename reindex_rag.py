"""Reindexa en bot_embeddings:
  - Todos los DocumentLink existentes (manuales, planos, fichas, informes).
  - OTs cerradas existentes (para capturar URLs incrustadas en execution_comments).

Ejecutar una sola vez despues del deploy. No bloquea ni duplica: usa ON CONFLICT.
"""
import os
import time
from app import app

with app.app_context():
    from database import db
    from models import DocumentLink, WorkOrder
    from bot.telegram_bot import _index_entity_async

    if not os.getenv('OPENAI_API_KEY'):
        print("OPENAI_API_KEY no esta seteada. Aborto.")
        raise SystemExit(1)

    # 1) DocumentLinks
    doc_ids = [d.id for d in DocumentLink.query.all()]
    print(f"Encolando {len(doc_ids)} DocumentLinks...")
    for did in doc_ids:
        _index_entity_async(app, 'document_link', did)

    # 2) OTs cerradas (para reextraer URLs en bitacora)
    wo_ids = [w.id for w in WorkOrder.query.filter_by(status='Cerrada').all()]
    print(f"Encolando {len(wo_ids)} OTs cerradas...")
    for wid in wo_ids:
        _index_entity_async(app, 'work_order', wid)

    # Los threads corren en background; esperamos un poco para que terminen
    total = len(doc_ids) + len(wo_ids)
    print(f"Esperando indexacion asincrona (~{max(5, total // 4)}s)...")
    time.sleep(max(5, total // 4))
    print("Listo. Verifica con: SELECT entity_type, COUNT(*) FROM bot_embeddings GROUP BY 1;")
