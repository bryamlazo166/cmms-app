"""Helpers de resolucion fuzzy/taxonomia para el bot Telegram.

Centraliza:
  - Diccionario de sinonimos de componentes (rodamiento -> chumacera, etc.)
  - Tokenizacion/normalizacion para matching libre
  - Resolucion de equipment/component a partir de tag/nombre con fallback fuzzy
  - Resolucion de taxonomia jerarquica (equipment_tag/system_name/component_name
    -> equipment_id/system_id/component_id/line_id/area_id)

Este modulo no depende de bot.telegram_bot — todas las acciones lo importan
directamente para evitar circular imports. SQL crudo via sqlalchemy.text.

Convencion: las funciones se exponen SIN prefijo `_` (estilo limpio).
bot/telegram_bot.py las re-exporta con prefijo `_` para compatibilidad
hacia atras con codigo legacy.
"""
import logging
import re

logger = logging.getLogger(__name__)


# ── Diccionario maestro de sinonimos ─────────────────────────────────────────

COMPONENT_SYNONYMS = {
    'motor': ['motor electrico', 'motor', 'mtr'],
    'motor electrico': ['motor electrico', 'motor', 'mtr'],
    'motorreductor': ['motorreductor', 'motor reductor', 'mtr-red', 'mtrred'],
    'reductor': ['reductor', 'caja reductora', 'red', 'gearbox'],
    'caja reductora': ['caja reductora', 'reductor', 'red'],
    'chumacera motriz': ['chumacera motriz', 'chumacera lado motriz', 'chum motriz', 'chumacera mot',
                         'rodamiento motriz', 'cojinete motriz', 'soporte motriz'],
    'chumacera conducida': ['chumacera conducida', 'chumacera lado conducido', 'chum conducida', 'chumacera con',
                            'rodamiento conducido', 'cojinete conducido', 'soporte conducido'],
    'chumacera': ['chumacera', 'chum', 'rodamiento', 'cojinete', 'soporte de rodamiento'],
    'faja': ['faja', 'banda', 'correa'],
    'cadena': ['cadena'],
    'rodamiento': ['rodamiento', 'cojinete', 'balinera', 'bearing'],
    'valvula': ['valvula', 'vavula', 'valve'],
    'sello': ['sello', 'reten', 'oring', 'o-ring', 'retentor'],
    'acople': ['acople', 'acoplamiento', 'copla', 'coupling'],
    'pinon': ['pinon', 'piñon', 'engranaje', 'gear'],
    'eje': ['eje', 'flecha', 'shaft'],
    'rodillo': ['rodillo', 'polin', 'roller'],
    # En los TH (transportadores helicoidales) el personal dice "espira",
    # "disco" o "tornillo" para referirse al componente HELICE del arbol.
    'helice': ['helice', 'hélice', 'espira', 'espiral', 'disco helicoidal',
               'discos del tornillo', 'disco del tornillo', 'tornillo helicoidal',
               'tornillo sin fin', 'sinfin', 'sin fin', 'gusano'],
    'transportador': ['transportador', 'faja transportadora', 'banda transportadora', 'conveyor'],
    'bomba': ['bomba', 'pump', 'bba'],
    'compresor': ['compresor', 'compressor'],
    'ventilador': ['ventilador', 'fan', 'soplador', 'extractor', 'blower'],
    'tablero': ['tablero', 'tablero electrico', 'panel electrico', 'gabinete'],
    'variador': ['variador', 'variador de frecuencia', 'vfd', 'inverter', 'drive'],
    'sensor': ['sensor', 'transductor', 'detector'],
    'manguera': ['manguera', 'manguera hidraulica', 'flexible'],
    'tuberia': ['tuberia', 'pipe', 'cañeria', 'caneria'],
    'filtro': ['filtro', 'filter'],
    'piston': ['piston', 'cilindro'],
    'tornillo': ['tornillo', 'perno', 'bolt'],
    'tolva': ['tolva', 'hopper'],
    'tripode': ['tripode', 'trípode'],
    'molino': ['molino', 'mill'],
    'percolador': ['percolador'],
    'digestor': ['digestor', 'digester'],
    'hidrolavadora': ['hidrolavadora', 'hidro lavadora'],
}


FUZZY_STOPWORDS = {
    'el', 'la', 'los', 'las', 'del', 'de', 'al', 'un', 'una', 'lo', 'que',
    'y', 'o', 'en', 'con', 'sin', 'por', 'para', 'su', 'se', 'es',
}


# ── Aliases de equipos a nivel sistema (baseline, no requieren BD) ──────────
#
# Convencion: clave = patron que el usuario escribe (case-insensitive, palabra
# completa), valor = texto que reemplaza al patron en el mensaje antes de que
# el bot extraiga tags. Mantener las expansiones cortas y usar tags reales que
# el resolvedor de contexto reconozca (TH3, D2, etc.). Los aliases mas largos
# se aplican primero para evitar matches parciales.
#
# Para alias personales del usuario, usar /alias en Telegram (se guardan en BD
# y se aplican DESPUES de estos del sistema).
SYSTEM_EQUIPMENT_ALIASES = {
    'th finos': 'TH3',
    'th fino': 'TH3',
    'transportador fino': 'TH3',
    'transportador finos': 'TH3',
    'helicoidal fino': 'TH3',
    'helicoidal finos': 'TH3',
}


def expand_equipment_aliases(text_msg):
    """Reemplaza aliases de equipo del sistema en el mensaje.

    Devuelve (texto_expandido, lista_aliases_aplicados).
    Match por palabra completa, case-insensitive. Mantiene la nota original
    entre parentesis para que el usuario vea como se interpreto.
    """
    if not text_msg:
        return text_msg, []
    expanded = text_msg
    applied = []
    # Aplicar primero los aliases mas largos para evitar matches parciales
    # (ej: 'th fino' antes que 'fino' si en el futuro agregamos uno mas corto).
    keys = sorted(SYSTEM_EQUIPMENT_ALIASES.keys(), key=lambda k: -len(k))
    for alias_l in keys:
        pattern = r'\b' + re.escape(alias_l) + r'\b'
        if re.search(pattern, expanded, flags=re.IGNORECASE):
            expansion = SYSTEM_EQUIPMENT_ALIASES[alias_l]
            replacement = f"{expansion} (alias: {alias_l})"
            expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
            applied.append((alias_l, expansion))
    return expanded, applied


# ── Tokenizacion y matching fuzzy ────────────────────────────────────────────

def fuzzy_tokens(query):
    """Tokeniza una consulta libre: descarta stopwords y tokens cortos no numericos."""
    if not query:
        return []
    out = []
    for t in re.split(r"[\s,;/#-]+", str(query).lower()):
        if not t or t in FUZZY_STOPWORDS:
            continue
        if len(t) >= 2 or t.isdigit():
            out.append(t)
    return out


def build_fuzzy_where(tokens, columns, params, prefix='ft'):
    """Construye una clausula WHERE que exige que TODOS los tokens aparezcan
    (con sinonimos expandidos) en al menos una de las columnas dadas. Muta `params`.
    Retorna el SQL del AND-clause (vacio si no hay tokens).
    """
    if not tokens:
        return ''
    where_parts = []
    for i, t in enumerate(tokens):
        alts = {t}
        for key, syns in COMPONENT_SYNONYMS.items():
            if t in key or any(t in s for s in syns):
                alts.update(syns)
                alts.add(key)
        sub_or = []
        for j, a in enumerate(alts):
            k = f"{prefix}{i}_{j}"
            params[k] = f"%{a}%"
            cols = ' OR '.join(f"{c} ILIKE :{k}" for c in columns)
            sub_or.append(f"({cols})")
        if sub_or:
            where_parts.append("(" + " OR ".join(sub_or) + ")")
    return ' AND '.join(where_parts)


def normalize_token(t):
    """Strip accents and normalize masc/fem endings so 'conducido' ~ 'conducida'."""
    import unicodedata
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('ascii').lower()
    for end in ('idas', 'idos', 'ida', 'ido', 'as', 'os', 'a', 'o', 'es', 's'):
        if len(t) > len(end) + 2 and t.endswith(end):
            return t[:-len(end)]
    return t


def score_fuzzy_candidates(tokens, candidates, blob_fn):
    """Puntua candidatos por solapamiento de tokens normalizados.

    Retorna (best | None, second_score).
    """
    user_norm = {normalize_token(t) for t in tokens}
    scored = []
    for cand in candidates:
        text_blob = (blob_fn(cand) or '').lower()
        cand_norm = {
            normalize_token(t)
            for t in re.split(r"[\s,;/#-]+", text_blob)
            if t and (len(t) >= 2 or t.isdigit())
        }
        scored.append((len(user_norm & cand_norm), cand))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, 0
    best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0
    return best[1] if best[0] > 0 else None, second


def smart_component_match(db, text_module, equipment_id, raw_name, system_hint=None):
    """Encuentra el mejor componente de un equipo dado un texto libre.

    Usa overlap de tokens con normalizacion (genero/numero) + expansion de sinonimos.

    Si `system_hint` viene (ej: 'exhaustor', 'ventilador'), prioriza componentes
    cuyo sistema padre contenga ese texto. Esto desambigua cuando un equipo
    tiene varios sistemas con componentes del mismo nombre (ej: SECA-SECA2
    tiene chumacera motriz en el sistema principal Y en el sistema EXHAUSTOR).

    Retorna (component_id, system_id) o None.
    """
    if not raw_name:
        return None
    name = raw_name.lower().strip()

    user_tokens_raw = set(name.split())
    user_tokens_norm = {normalize_token(t) for t in user_tokens_raw if len(t) > 2}

    terms = {name}
    for key, syns in COMPONENT_SYNONYMS.items():
        key_tokens_norm = {normalize_token(t) for t in key.split() if len(t) > 2}
        if key_tokens_norm and key_tokens_norm.issubset(user_tokens_norm):
            terms.update(syns)
            terms.add(key)
            continue
        for syn in syns:
            syn_tokens_norm = {normalize_token(t) for t in syn.split() if len(t) > 2}
            if syn_tokens_norm and syn_tokens_norm.issubset(user_tokens_norm):
                terms.add(key)
                terms.update(syns)
                break

    # Trae sys_name junto al componente para poder priorizar por system_hint
    rows = db.session.execute(text_module("""
        SELECT c.id, c.name, c.system_id, s.name FROM components c
        JOIN systems s ON c.system_id = s.id
        WHERE s.equipment_id = :eid
    """), {"eid": equipment_id}).fetchall()
    if not rows:
        return None

    # Expandir el hint con sinonimos para tolerar "soplador" == "ventilador" == "extractor"
    hint_terms = set()
    if system_hint:
        hint_low = system_hint.lower().strip()
        if hint_low:
            hint_terms.add(hint_low)
            for key, syns in COMPONENT_SYNONYMS.items():
                if hint_low == key or hint_low in syns:
                    hint_terms.update(syns)
                    hint_terms.add(key)
                    break

    best = None
    best_score = 0
    for cid, cname, sid, sname in rows:
        cname_low = (cname or '').lower()
        sname_low = (sname or '').lower()
        comp_tokens_norm = {normalize_token(t) for t in cname_low.split() if len(t) > 2}
        score = 0
        for term in terms:
            if term and term in cname_low:
                score += 10 + len(term)
        overlap = user_tokens_norm & comp_tokens_norm
        score += len(overlap) * 5
        if comp_tokens_norm and comp_tokens_norm.issubset(user_tokens_norm):
            score += 20
        # Bonus fuerte si el sistema padre matchea el hint del usuario.
        # Esto rompe empates entre componentes con el mismo nombre en
        # distintos sistemas del mismo equipo.
        if hint_terms:
            if any(h in sname_low for h in hint_terms):
                score += 50
            else:
                # Penalizacion suave: si dio hint pero este sistema no coincide,
                # baja la prioridad. No descartamos por completo para tolerar
                # casos donde el hint es parte del nombre del componente y no
                # del sistema.
                score -= 5
        if score > best_score:
            best_score = score
            best = (cid, sid)

    return best if best_score > 0 else None


# ── Resolucion de equipment/jerarquia ────────────────────────────────────────

def resolve_equipment(db, text_module, data):
    """Resuelve IDs de equipment/component a partir de tags/nombres en `data`.

    Prioridad: IDs explicitos > tag/nombre fuzzy. Tambien resuelve
    rotative_asset_id y back-fillea los niveles faltantes desde el.

    Retorna (equipment_id, line_id, area_id, system_id, component_id, rotative_asset_id).
    """
    equipment_id = line_id = area_id = system_id = component_id = None
    rotative_asset_id = None

    # 1) IDs directos (preferido)
    if data.get('equipment_id'):
        equipment_id = int(data['equipment_id'])
    if data.get('component_id'):
        component_id = int(data['component_id'])
    if data.get('system_id'):
        system_id = int(data['system_id'])
    if data.get('rotative_asset_id'):
        rotative_asset_id = int(data['rotative_asset_id'])

    # 2) Fuzzy fallbacks si no hay IDs
    if not equipment_id:
        if data.get('equipment_tag'):
            row = db.session.execute(text_module("SELECT id, line_id FROM equipments WHERE tag = :t"), {"t": data['equipment_tag']}).fetchone()
            if row:
                equipment_id, line_id = row[0], row[1]
        elif data.get('equipment_name'):
            row = db.session.execute(text_module("SELECT id, line_id FROM equipments WHERE LOWER(name) LIKE :n LIMIT 1"), {"n": f"%{data['equipment_name'].lower()}%"}).fetchone()
            if row:
                equipment_id, line_id = row[0], row[1]

    # 3) Derivar equipo/componente desde el activo rotativo
    if rotative_asset_id:
        r = db.session.execute(text_module("""
            SELECT equipment_id, component_id FROM rotative_assets WHERE id = :id
        """), {"id": rotative_asset_id}).fetchone()
        if r:
            equipment_id = equipment_id or r[0]
            component_id = component_id or r[1]

    # 4) Si hay componente pero no equipo, derivar equipo desde el componente
    if component_id and not equipment_id:
        r = db.session.execute(text_module("""
            SELECT s.equipment_id, c.system_id FROM components c
            JOIN systems s ON c.system_id = s.id
            WHERE c.id = :cid
        """), {"cid": component_id}).fetchone()
        if r:
            equipment_id = r[0]
            system_id = system_id or r[1]

    # 5) line_id desde equipo si falta
    if equipment_id and not line_id:
        r = db.session.execute(text_module("SELECT line_id FROM equipments WHERE id = :id"), {"id": equipment_id}).fetchone()
        if r:
            line_id = r[0]

    # 6) area_id desde linea
    if line_id:
        r = db.session.execute(text_module("SELECT area_id FROM lines WHERE id = :id"), {"id": line_id}).fetchone()
        if r:
            area_id = r[0]

    # 7) Componente fuzzy fallback. Si vino system_name (ej: 'exhaustor'),
    # se pasa como hint para desambiguar componentes homonimos en sistemas
    # distintos del mismo equipo.
    if equipment_id and not component_id and data.get('component_name'):
        component_id, system_id = smart_component_match(
            db, text_module, equipment_id, data['component_name'],
            system_hint=data.get('system_name'),
        ) or (None, None)
        if component_id and not rotative_asset_id:
            r = db.session.execute(text_module("""
                SELECT id FROM rotative_assets
                WHERE component_id = :c AND is_active = true LIMIT 1
            """), {"c": component_id}).fetchone()
            if r:
                rotative_asset_id = r[0]

    # 8) system_id desde componente si falta
    if component_id and not system_id:
        r = db.session.execute(text_module("SELECT system_id FROM components WHERE id = :id"), {"id": component_id}).fetchone()
        if r:
            system_id = r[0]

    return equipment_id, line_id, area_id, system_id, component_id, rotative_asset_id


def resolve_taxonomy(db_session, fields):
    """Resuelve equipment_tag/system_name/component_name a FK ids.

    Acepta claves virtuales (equipment_tag, system_name, component_name) y las
    reemplaza con columnas FK reales (equipment_id, system_id, component_id,
    line_id, area_id).

    Retorna (resolved_fields_dict, resolved_names_list, error | None).
    """
    from sqlalchemy import text
    resolved = {}
    names = []

    eq_tag = fields.pop('equipment_tag', None)
    eq_name = fields.pop('equipment_name', None)
    sys_name = fields.pop('system_name', None)
    comp_name = fields.pop('component_name', None)

    # Resolve equipment
    eq_row = None
    if eq_tag:
        tag_norm = re.sub(r'\s+', '', (eq_tag or '').upper().replace('#', ''))
        eq_row = db_session.execute(text(
            "SELECT e.id, e.name, e.tag, l.id, l.area_id "
            "FROM equipments e LEFT JOIN lines l ON e.line_id=l.id "
            "WHERE UPPER(REPLACE(REPLACE(e.tag,'#',''),' ','')) = :t LIMIT 1"
        ), {"t": tag_norm}).fetchone()
        if not eq_row:
            eq_row = db_session.execute(text(
                "SELECT e.id, e.name, e.tag, l.id, l.area_id "
                "FROM equipments e LEFT JOIN lines l ON e.line_id=l.id "
                "WHERE UPPER(REPLACE(REPLACE(e.name,'#',''),' ','')) = :t LIMIT 1"
            ), {"t": tag_norm}).fetchone()
    elif eq_name:
        name_norm = re.sub(r'\s+', '', (eq_name or '').upper().replace('#', ''))
        eq_row = db_session.execute(text(
            "SELECT e.id, e.name, e.tag, l.id, l.area_id "
            "FROM equipments e LEFT JOIN lines l ON e.line_id=l.id "
            "WHERE UPPER(REPLACE(REPLACE(e.name,'#',''),' ','')) = :n "
            "   OR UPPER(REPLACE(REPLACE(e.tag,'#',''),' ','')) = :n LIMIT 1"
        ), {"n": name_norm}).fetchone()

    if eq_row:
        resolved['equipment_id'] = eq_row[0]
        resolved['line_id'] = eq_row[3]
        resolved['area_id'] = eq_row[4]
        names.append(f"equipo: {eq_row[2]} {eq_row[1]}")

    eq_id = resolved.get('equipment_id') or fields.get('equipment_id')

    # Resolve system
    if sys_name and eq_id:
        sys_row = db_session.execute(text(
            "SELECT id, name FROM systems "
            "WHERE equipment_id = :eid AND UPPER(name) = UPPER(:n) LIMIT 1"
        ), {"eid": eq_id, "n": sys_name.strip()}).fetchone()
        if sys_row:
            resolved['system_id'] = sys_row[0]
            names.append(f"sistema: {sys_row[1]}")

    sys_id = resolved.get('system_id') or fields.get('system_id')

    # Resolve component
    if comp_name and sys_id:
        comp_row = db_session.execute(text(
            "SELECT id, name FROM components "
            "WHERE system_id = :sid AND UPPER(name) = UPPER(:n) LIMIT 1"
        ), {"sid": sys_id, "n": comp_name.strip()}).fetchone()
        if comp_row:
            resolved['component_id'] = comp_row[0]
            names.append(f"componente: {comp_row[1]}")
    elif comp_name and eq_id and not sys_id:
        comp_row = db_session.execute(text(
            "SELECT c.id, c.name, s.id AS sid, s.name AS sname FROM components c "
            "JOIN systems s ON c.system_id=s.id "
            "WHERE s.equipment_id = :eid AND UPPER(c.name) = UPPER(:n) LIMIT 1"
        ), {"eid": eq_id, "n": comp_name.strip()}).fetchone()
        if comp_row:
            resolved['component_id'] = comp_row[0]
            resolved['system_id'] = comp_row[2]
            names.append(f"sistema: {comp_row[3]}, componente: {comp_row[1]}")

    return resolved, names, None
