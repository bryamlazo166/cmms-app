"""Helpers para embeddings (RAG) usando OpenAI text-embedding-3-small + pgvector.

Funciones principales:
  - generate_embedding(text): llama a OpenAI y devuelve list[float] de 1536 dim
  - upsert_embedding(entity_type, entity_id, text, metadata=None): inserta/actualiza
  - semantic_search(query_text, top_k=5, entity_types=None): busca casos similares

Costos: text-embedding-3-small ~ $0.02 por millon de tokens (muy barato).
Un OT cerrado tipico = ~80 tokens = $0.0000016 cada uno.
"""
import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_EMBED_URL = 'https://api.openai.com/v1/embeddings'
EMBED_MODEL = 'text-embedding-3-small'  # 1536 dim, barato y bueno
EMBED_DIM = 1536


def generate_embedding(text):
    """Genera el embedding de un texto. Devuelve list[float] o None si falla."""
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY no esta seteada — embedding deshabilitado")
        return None
    if not text or not text.strip():
        return None
    try:
        r = requests.post(
            OPENAI_EMBED_URL,
            headers={
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': EMBED_MODEL,
                'input': text[:8000],  # safety: limitar tokens
            },
            timeout=30,
        )
        if r.status_code != 200:
            logger.warning(f"OpenAI embeddings error {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        return data['data'][0]['embedding']
    except Exception as e:
        logger.warning(f"generate_embedding error: {e}")
        return None


def _vec_literal(vec):
    """Convierte una lista de floats al formato literal '[v1,v2,...]' que pgvector acepta."""
    return '[' + ','.join(repr(float(x)) for x in vec) + ']'


def upsert_embedding(db_session, entity_type, entity_id, text, metadata=None):
    """Inserta o actualiza el embedding para una entidad. Devuelve True/False.

    db_session: la sesion SQLAlchemy ya activa.
    """
    if not text or not entity_type or entity_id is None:
        return False
    vec = generate_embedding(text)
    if vec is None:
        return False
    vec_lit = _vec_literal(vec)
    meta_json = json.dumps(metadata or {})
    try:
        from sqlalchemy import text as sql_text
        db_session.execute(sql_text("""
            INSERT INTO bot_embeddings (entity_type, entity_id, text_chunk, embedding, metadata, created_at, updated_at)
            VALUES (:et, :eid, :txt, CAST(:vec AS vector), CAST(:meta AS jsonb), NOW(), NOW())
            ON CONFLICT (entity_type, entity_id) DO UPDATE
              SET text_chunk = EXCLUDED.text_chunk,
                  embedding  = EXCLUDED.embedding,
                  metadata   = EXCLUDED.metadata,
                  updated_at = NOW()
        """), {"et": entity_type, "eid": entity_id, "txt": text[:8000], "vec": vec_lit, "meta": meta_json})
        return True
    except Exception as e:
        logger.warning(f"upsert_embedding error: {e}")
        return False


def semantic_search(db_session, query_text, top_k=5, entity_types=None):
    """Busca los top_k chunks mas similares al texto de consulta.

    Devuelve: lista de dicts {entity_type, entity_id, text_chunk, similarity, metadata}.
    similarity = 1 - cosine_distance, rango 0..1 (mayor = mas similar).
    """
    if not query_text:
        return []
    vec = generate_embedding(query_text)
    if vec is None:
        return []
    vec_lit = _vec_literal(vec)
    try:
        from sqlalchemy import text as sql_text
        if entity_types:
            type_filter = "AND entity_type = ANY(:types)"
            params = {"vec": vec_lit, "k": top_k, "types": list(entity_types)}
        else:
            type_filter = ""
            params = {"vec": vec_lit, "k": top_k}
        sql = f"""
            SELECT entity_type, entity_id, text_chunk, metadata,
                   1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM bot_embeddings
            WHERE embedding IS NOT NULL {type_filter}
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """
        rows = db_session.execute(sql_text(sql), params).fetchall()
        results = []
        for r in rows:
            meta = r[3] if isinstance(r[3], dict) else {}
            results.append({
                'entity_type': r[0],
                'entity_id': r[1],
                'text_chunk': r[2],
                'metadata': meta,
                'similarity': float(r[4]) if r[4] is not None else 0.0,
            })
        return results
    except Exception as e:
        logger.warning(f"semantic_search error: {e}")
        return []


def delete_embedding(db_session, entity_type, entity_id):
    """Elimina el embedding de una entidad (cuando se borra del sistema)."""
    try:
        from sqlalchemy import text as sql_text
        db_session.execute(sql_text(
            "DELETE FROM bot_embeddings WHERE entity_type = :et AND entity_id = :eid"
        ), {"et": entity_type, "eid": entity_id})
        return True
    except Exception as e:
        logger.warning(f"delete_embedding error: {e}")
        return False


# ── Helpers para construir el texto a indexar (rico en contexto) ──────────

def build_ot_text(wo, equipment=None, area=None, line=None, system=None, component=None,
                  notice=None):
    """Construye el texto descriptivo de una OT para embedding."""
    parts = []
    parts.append(f"OT {wo.get('code') or '-'}")
    if wo.get('status'):
        parts.append(f"({wo['status']})")
    parts.append("\n")
    eq_label = ''
    if equipment:
        eq_label = f"[{equipment.tag or '-'}] {equipment.name or '-'}"
    parts.append(f"Equipo: {eq_label or '-'}")
    if area:
        parts.append(f" | Area: {area.name}")
    if line:
        parts.append(f" | Linea: {line.name}")
    parts.append("\n")
    if system:
        parts.append(f"Sistema: {system.name}")
    if component:
        parts.append(f" | Componente: {component.name}")
    parts.append("\n")
    if wo.get('maintenance_type'):
        parts.append(f"Tipo: {wo['maintenance_type']}\n")
    if wo.get('failure_mode'):
        parts.append(f"Modo de falla: {wo['failure_mode']}\n")
    if wo.get('description'):
        parts.append(f"Descripcion: {wo['description']}\n")
    if wo.get('execution_comments'):
        parts.append(f"Trabajo realizado: {wo['execution_comments']}\n")
    if wo.get('real_duration'):
        parts.append(f"Duracion real: {wo['real_duration']} h\n")
    if wo.get('caused_downtime') and wo.get('downtime_hours'):
        parts.append(f"Causo parada: {wo['downtime_hours']} h\n")
    if notice:
        parts.append(f"Aviso origen: {notice.code or notice.id} — {notice.description or ''}\n")
    return ''.join(parts).strip()


def build_notice_text(notice, equipment=None, area=None, line=None, component=None):
    """Construye el texto descriptivo de un Aviso para embedding."""
    parts = []
    parts.append(f"AVISO {notice.code or 'AV-' + str(notice.id)}\n")
    eq_label = ''
    if equipment:
        eq_label = f"[{equipment.tag or '-'}] {equipment.name or '-'}"
    parts.append(f"Equipo: {eq_label or notice.free_location or '-'}")
    if area:
        parts.append(f" | Area: {area.name}")
    if line:
        parts.append(f" | Linea: {line.name}")
    parts.append("\n")
    if component:
        parts.append(f"Componente: {component.name}\n")
    if notice.failure_mode:
        parts.append(f"Modo de falla: {notice.failure_mode}\n")
    if getattr(notice, 'failure_category', None):
        parts.append(f"Categoria: {notice.failure_category}\n")
    if getattr(notice, 'blockage_object', None):
        parts.append(f"Objeto de bloqueo: {notice.blockage_object}\n")
    if notice.criticality:
        parts.append(f"Criticidad: {notice.criticality}\n")
    if notice.description:
        parts.append(f"Descripcion: {notice.description}\n")
    return ''.join(parts).strip()
