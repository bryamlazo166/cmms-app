"""Glosario aprendido del bot.

El usuario ensena al bot equivalencias locales (apodos, abreviaturas,
codigos internos) y el bot las expande en cada mensaje antes de procesar.

Ejemplos:
  'fapmetal' -> 'FAB METAL SAC'
  'el negro' -> 'chumacera oxidada del D8'
  'thal-sec' -> 'TH ALIMENTADOR SECADOR 1'
"""
import re
import logging

logger = logging.getLogger(__name__)


# Cache en memoria del glosario (refrescado periodicamente desde DB).
# Estructura: {(chat_id_or_none, lower_alias): expansion}
# chat_id es None para aliases globales.
_alias_cache = {}
_cache_loaded = False


def load_aliases(db_session):
    """Carga (o recarga) todos los aliases activos en memoria.

    Se llama en background al arrancar y cuando se modifica algun alias.
    """
    global _alias_cache, _cache_loaded
    try:
        from sqlalchemy import text
        rows = db_session.execute(text("""
            SELECT alias, expansion, chat_id
            FROM bot_aliases
            WHERE is_active = TRUE
            ORDER BY usage_count DESC, id ASC
        """)).fetchall()
        new_cache = {}
        for r in rows:
            alias_l = (r[0] or '').strip().lower()
            if not alias_l:
                continue
            new_cache[(r[2], alias_l)] = r[1]
        _alias_cache = new_cache
        _cache_loaded = True
        return len(new_cache)
    except Exception as e:
        logger.warning(f"load_aliases error: {e}")
        return 0


def expand_message(text_msg, chat_id, db_session=None):
    """Expande aliases dentro de un mensaje.

    Devuelve (texto_expandido, lista_de_aliases_aplicados).
    """
    if not text_msg:
        return text_msg, []
    if not _cache_loaded and db_session is not None:
        load_aliases(db_session)
    if not _alias_cache:
        return text_msg, []

    expanded = text_msg
    applied = []
    # Buscar primero aliases del chat especifico, luego globales
    keys = sorted(_alias_cache.keys(), key=lambda k: (-len(k[1]), k[1]))  # mas largos primero
    for (cid, alias_l) in keys:
        if cid is not None and cid != chat_id:
            continue
        # Match palabra completa, case-insensitive
        pattern = r'\b' + re.escape(alias_l) + r'\b'
        if re.search(pattern, expanded, flags=re.IGNORECASE):
            expansion = _alias_cache[(cid, alias_l)]
            # Reemplazar manteniendo nota original entre parentesis
            replacement = f"{expansion} (alias: {alias_l})"
            expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
            applied.append((alias_l, expansion))
    return expanded, applied


def save_alias(db_session, alias, expansion, chat_id=None, category=None, created_by=None):
    """Guarda o actualiza un alias. Devuelve (ok, mensaje)."""
    alias_clean = (alias or '').strip()
    expansion_clean = (expansion or '').strip()
    if not alias_clean or not expansion_clean:
        return False, "Falta alias o expansion"
    if len(alias_clean) > 120 or len(expansion_clean) > 1000:
        return False, "Alias o expansion demasiado largos"
    try:
        from sqlalchemy import text
        # Upsert manual (PostgreSQL ON CONFLICT requiere indice exacto)
        existing = db_session.execute(text("""
            SELECT id FROM bot_aliases
            WHERE LOWER(alias) = LOWER(:a) AND is_active = TRUE
        """), {"a": alias_clean}).fetchone()
        if existing:
            db_session.execute(text("""
                UPDATE bot_aliases
                SET expansion = :e, category = :c, updated_at = NOW(), chat_id = :cid
                WHERE id = :id
            """), {"e": expansion_clean, "c": category, "cid": chat_id, "id": existing[0]})
            action = "actualizado"
        else:
            db_session.execute(text("""
                INSERT INTO bot_aliases (alias, expansion, category, chat_id, created_by)
                VALUES (:a, :e, :c, :cid, :cb)
            """), {"a": alias_clean, "e": expansion_clean, "c": category,
                   "cid": chat_id, "cb": created_by})
            action = "guardado"
        db_session.commit()
        # Refrescar cache
        load_aliases(db_session)
        return True, f"Alias {action}: '{alias_clean}' -> '{expansion_clean}'"
    except Exception as e:
        db_session.rollback()
        return False, f"Error: {e}"


def delete_alias(db_session, alias):
    """Marca un alias como inactivo (soft delete). Devuelve (ok, mensaje)."""
    alias_clean = (alias or '').strip()
    if not alias_clean:
        return False, "Falta alias"
    try:
        from sqlalchemy import text
        result = db_session.execute(text("""
            UPDATE bot_aliases
            SET is_active = FALSE, updated_at = NOW()
            WHERE LOWER(alias) = LOWER(:a) AND is_active = TRUE
        """), {"a": alias_clean})
        db_session.commit()
        load_aliases(db_session)
        if result.rowcount > 0:
            return True, f"Alias '{alias_clean}' eliminado"
        return False, f"No existe alias '{alias_clean}'"
    except Exception as e:
        db_session.rollback()
        return False, f"Error: {e}"


def list_aliases(db_session, chat_id=None, limit=50):
    """Devuelve lista de aliases activos. Si chat_id se da, incluye globales + del chat."""
    try:
        from sqlalchemy import text
        if chat_id is None:
            sql = """
                SELECT alias, expansion, category, usage_count
                FROM bot_aliases WHERE is_active = TRUE
                ORDER BY chat_id IS NULL, usage_count DESC, alias ASC
                LIMIT :lim
            """
            params = {"lim": limit}
        else:
            sql = """
                SELECT alias, expansion, category, usage_count
                FROM bot_aliases
                WHERE is_active = TRUE AND (chat_id IS NULL OR chat_id = :cid)
                ORDER BY chat_id IS NULL, usage_count DESC, alias ASC
                LIMIT :lim
            """
            params = {"cid": chat_id, "lim": limit}
        rows = db_session.execute(text(sql), params).fetchall()
        return [{
            'alias': r[0], 'expansion': r[1],
            'category': r[2], 'usage_count': r[3]
        } for r in rows]
    except Exception as e:
        logger.warning(f"list_aliases error: {e}")
        return []


def increment_usage(db_session, aliases_used):
    """Incrementa usage_count para aliases que se aplicaron (para priorizar populares)."""
    if not aliases_used:
        return
    try:
        from sqlalchemy import text
        for alias, _ in aliases_used:
            db_session.execute(text("""
                UPDATE bot_aliases SET usage_count = usage_count + 1, updated_at = NOW()
                WHERE LOWER(alias) = LOWER(:a) AND is_active = TRUE
            """), {"a": alias})
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.warning(f"increment_usage error: {e}")
