#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Indexa todas las OTs cerradas y todos los avisos en bot_embeddings.

Idempotente: usa upsert, asi que se puede correr multiples veces sin duplicar.
Costo estimado: ~$0.0001 por cada 100 entidades (despreciable).
"""
import os
import sys
import time
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_URL = os.getenv('DATABASE_URL')

# Conectar via psycopg2 directo (mas rapido para bulk, sin overhead de Flask)
import requests
import json

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    print("ERROR: OPENAI_API_KEY no esta en .env. Agregarla y reintentar.")
    sys.exit(1)


def gen_embed(text):
    r = requests.post(
        'https://api.openai.com/v1/embeddings',
        headers={'Authorization': f'Bearer {OPENAI_API_KEY}'},
        json={'model': 'text-embedding-3-small', 'input': text[:8000]},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"  ! OpenAI error {r.status_code}: {r.text[:150]}")
        return None
    return r.json()['data'][0]['embedding']


def vec_lit(vec):
    return '[' + ','.join(repr(float(x)) for x in vec) + ']'


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── OTs (cerradas o no) ───
    cur.execute("""
        SELECT wo.id, wo.code, wo.status, wo.description, wo.maintenance_type,
               wo.failure_mode, wo.execution_comments, wo.real_duration,
               wo.caused_downtime, wo.downtime_hours,
               e.name AS eq_name, e.tag AS eq_tag,
               a.name AS area_name, l.name AS line_name,
               s.name AS sys_name, c.name AS comp_name,
               n.code AS notice_code, n.description AS notice_desc
        FROM work_orders wo
        LEFT JOIN equipments e  ON wo.equipment_id  = e.id
        LEFT JOIN areas a       ON wo.area_id       = a.id
        LEFT JOIN lines l       ON wo.line_id       = l.id
        LEFT JOIN systems s     ON wo.system_id     = s.id
        LEFT JOIN components c  ON wo.component_id  = c.id
        LEFT JOIN maintenance_notices n ON wo.notice_id = n.id
        WHERE wo.status = 'Cerrada'  -- solo OTs cerradas (las de mas valor para RAG)
    """)
    ots = cur.fetchall()
    print(f"OTs cerradas a indexar: {len(ots)}")

    indexed = 0
    for wo in ots:
        parts = [f"OT {wo['code'] or wo['id']} (cerrada)\n"]
        eq_lbl = f"[{wo['eq_tag'] or '-'}] {wo['eq_name'] or '-'}"
        parts.append(f"Equipo: {eq_lbl}")
        if wo['area_name']: parts.append(f" | Area: {wo['area_name']}")
        if wo['line_name']: parts.append(f" | Linea: {wo['line_name']}")
        parts.append("\n")
        if wo['sys_name']:  parts.append(f"Sistema: {wo['sys_name']}")
        if wo['comp_name']: parts.append(f" | Componente: {wo['comp_name']}")
        parts.append("\n")
        if wo['maintenance_type']: parts.append(f"Tipo: {wo['maintenance_type']}\n")
        if wo['failure_mode']:     parts.append(f"Modo de falla: {wo['failure_mode']}\n")
        if wo['description']:      parts.append(f"Descripcion: {wo['description']}\n")
        if wo['execution_comments']: parts.append(f"Trabajo realizado: {wo['execution_comments']}\n")
        if wo['real_duration']:    parts.append(f"Duracion: {wo['real_duration']} h\n")
        if wo['caused_downtime'] and wo['downtime_hours']:
            parts.append(f"Causo parada de produccion: {wo['downtime_hours']} h\n")
        if wo['notice_code']:
            parts.append(f"Aviso origen: {wo['notice_code']} — {wo['notice_desc'] or ''}\n")

        text = ''.join(parts).strip()
        emb = gen_embed(text)
        if not emb:
            continue

        meta = {
            'code': wo['code'],
            'equipment_tag': wo['eq_tag'],
            'equipment_name': wo['eq_name'],
            'failure_mode': wo['failure_mode'],
        }
        cur.execute("""
            INSERT INTO bot_embeddings (entity_type, entity_id, text_chunk, embedding, metadata, created_at, updated_at)
            VALUES (%s, %s, %s, %s::vector, %s::jsonb, NOW(), NOW())
            ON CONFLICT (entity_type, entity_id) DO UPDATE
              SET text_chunk = EXCLUDED.text_chunk,
                  embedding  = EXCLUDED.embedding,
                  metadata   = EXCLUDED.metadata,
                  updated_at = NOW()
        """, ('work_order', wo['id'], text, vec_lit(emb), json.dumps(meta)))
        indexed += 1
        if indexed % 5 == 0:
            conn.commit()
            print(f"  ... {indexed}/{len(ots)} OTs indexadas")

    conn.commit()
    print(f"OTs indexadas: {indexed}/{len(ots)}")

    # ── Avisos (todos, no solo cerrados) ────
    cur.execute("""
        SELECT n.id, n.code, n.description, n.failure_mode, n.failure_category,
               n.blockage_object, n.criticality, n.status, n.free_location,
               e.name AS eq_name, e.tag AS eq_tag,
               a.name AS area_name, l.name AS line_name,
               c.name AS comp_name
        FROM maintenance_notices n
        LEFT JOIN equipments e  ON n.equipment_id  = e.id
        LEFT JOIN areas a       ON n.area_id       = a.id
        LEFT JOIN lines l       ON n.line_id       = l.id
        LEFT JOIN components c  ON n.component_id  = c.id
    """)
    avisos = cur.fetchall()
    print(f"\nAvisos a indexar: {len(avisos)}")

    indexed = 0
    for av in avisos:
        parts = [f"AVISO {av['code'] or 'AV-' + str(av['id'])}\n"]
        eq_lbl = f"[{av['eq_tag'] or '-'}] {av['eq_name'] or '-'}" if av['eq_name'] else (av['free_location'] or '-')
        parts.append(f"Equipo/Ubicacion: {eq_lbl}")
        if av['area_name']: parts.append(f" | Area: {av['area_name']}")
        if av['line_name']: parts.append(f" | Linea: {av['line_name']}")
        parts.append("\n")
        if av['comp_name']:        parts.append(f"Componente: {av['comp_name']}\n")
        if av['failure_mode']:     parts.append(f"Modo de falla: {av['failure_mode']}\n")
        if av['failure_category']: parts.append(f"Categoria: {av['failure_category']}\n")
        if av['blockage_object']:  parts.append(f"Objeto de bloqueo: {av['blockage_object']}\n")
        if av['criticality']:      parts.append(f"Criticidad: {av['criticality']}\n")
        if av['status']:           parts.append(f"Estado: {av['status']}\n")
        if av['description']:      parts.append(f"Descripcion: {av['description']}\n")

        text = ''.join(parts).strip()
        emb = gen_embed(text)
        if not emb:
            continue
        meta = {
            'code': av['code'],
            'equipment_tag': av['eq_tag'],
            'equipment_name': av['eq_name'],
            'failure_mode': av['failure_mode'],
            'criticality': av['criticality'],
        }
        cur.execute("""
            INSERT INTO bot_embeddings (entity_type, entity_id, text_chunk, embedding, metadata, created_at, updated_at)
            VALUES (%s, %s, %s, %s::vector, %s::jsonb, NOW(), NOW())
            ON CONFLICT (entity_type, entity_id) DO UPDATE
              SET text_chunk = EXCLUDED.text_chunk,
                  embedding  = EXCLUDED.embedding,
                  metadata   = EXCLUDED.metadata,
                  updated_at = NOW()
        """, ('notice', av['id'], text, vec_lit(emb), json.dumps(meta)))
        indexed += 1
        if indexed % 5 == 0:
            conn.commit()
            print(f"  ... {indexed}/{len(avisos)} avisos indexados")

    conn.commit()
    print(f"Avisos indexados: {indexed}/{len(avisos)}")

    cur.close()
    conn.close()
    print("\n=== INDEXADO COMPLETO ===")


if __name__ == '__main__':
    try:
        t0 = time.time()
        main()
        print(f"\nTiempo total: {time.time()-t0:.1f}s")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
