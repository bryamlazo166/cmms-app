"""Capa LLM del bot: llamada a DeepSeek + parseo de JSON.

Construye el system prompt con el contexto CMMS + guia maestra + lista
de acciones disponibles, y dispara la llamada al endpoint. Soporta tracking
de uso via bot.metrics.

Tambien expone _extract_json para parsear la respuesta del modelo, tolerante
a markdown, prosa adicional y JSONs malformados (best-effort).
"""
import json
import logging
import requests
from datetime import date, timedelta

from bot.context import _load_cmms_guide

logger = logging.getLogger(__name__)

# Estos vienen de bot.telegram_bot que ya esta cargado cuando se llama a
# _ask_deepseek. Se importan via lazy lookup para evitar circular en startup.
def _get_deepseek_config():
    from bot.telegram_bot import DEEPSEEK_API_KEY, DEEPSEEK_URL
    return DEEPSEEK_API_KEY, DEEPSEEK_URL

# ── DeepSeek AI ──────────────────────────────────────────────────────────

def _ask_deepseek(question, cmms_context, is_action=False, history=None, app=None, chat_id=None):
    _DEEPSEEK_API_KEY, _DEEPSEEK_URL = _get_deepseek_config()
    headers = {'Authorization': f'Bearer {_DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}

    action_instructions = """

FORMATO DE RESPUESTA OBLIGATORIO — SIEMPRE respondes con un UNICO objeto JSON valido, NUNCA texto plano.

Hay dos formas posibles:

A) CONSULTA / RESPUESTA DE TEXTO (cuando NO hay accion que ejecutar):
{"action": "none", "reply": "aqui va el texto que quieres mostrar al usuario"}

B) ACCION (cuando el usuario quiere crear/modificar algo — ver lista abajo):
{"action": "<nombre_accion>", "data": {...}}

REGLA CRITICA #1 — DISTINGUIR CONSULTA DE REPORTE DE FALLA:
- Si el usuario PREGUNTA informacion (palabras como "cual", "que", "cuanto", "cuando", "dame", "muestrame", "lista", "ver", "consultar", "donde", "como esta", "que tiene", "tiene...?", "es...?"), SIEMPRE usa action:"none" y responde en reply. NUNCA crees un aviso.
- Si el usuario REPORTA una falla activa (palabras como "esta fallando", "se rompio", "no arranca", "vibra", "hace ruido", "gotea", "se sobrecaliento", "se trabo", "salta el termico", "boto aceite"), entonces crea action:"create_notice".
- Si el usuario solo describe el equipo o pide datos tecnicos (marca, codigo, modelo, especificaciones, ubicacion, ficha tecnica), es CONSULTA → action:"none".
- Ante la duda, prefiere action:"none" con reply explicando lo que entendiste. NUNCA generes un aviso "por si acaso".

REGLA — MODULO DE SEGUIMIENTO (Activities + Milestones):
- Cuando el usuario pregunte por "seguimiento", "actividad", "actividades", "mis seguimientos", "compras", "fabricaciones", "fabricacion", "proyecto", "reunion", "limpieza programada", "trabajo programado", "que se va a hacer", "cuando se hara X", "estado de X" donde X NO es una OT/aviso (es algo mas amplio), SIEMPRE revisa la seccion === SEGUIMIENTO — ACTIVIDADES ACTIVAS === y === SEGUIMIENTO — HITOS === del contexto.
- Las actividades del modulo seguimiento son distintas a las OTs y avisos: son fabricaciones, compras, proyectos, paradas, reuniones u otros trabajos de gestion mas amplios. Tienen tipo (FABRICACION/COMPRA/REUNION/PROYECTO/PARADA/OTRO), prioridad (ALTA/MEDIA/BAJA), responsable, fechas (inicio, meta, completion) y una lista de hitos (milestones).
- Cuando respondas sobre una actividad, MENCIONA: titulo, tipo, responsable, fecha meta y proximo hito pendiente (si existe). Si la actividad esta vinculada a un equipo, indica el tag.
- Si el usuario pregunta "cuando se va a hacer X" / "cuando esta programado Y" — primero busca en SEGUIMIENTO, luego en avisos/OTs/preventivos.
- Ejemplos:
  * "Cuando se va a hacer la limpieza del lavador de vahos?" → busca actividades cuyo titulo o descripcion contenga "lavador" o "vahos" en SEGUIMIENTO. Si existe, responde con titulo, fecha meta y proximo hito.
  * "Que actividades de compra tengo abiertas?" → filtra activity_type=COMPRA con status ABIERTA o EN_PROGRESO.
  * "Que tiene asignado Marcos esta semana en seguimiento?" → filtra responsible=Marcos.

REGLA CRITICA #2: Si el usuario reporta una falla, pide crear/editar/cerrar algo, NO uses action:"none" con reply describiendo la accion. Devuelve la accion real. El campo "reply" NUNCA debe contener frases como "aviso creado", "AV-XXXX generado", "OT cerrada", "accion registrada" — eso solo lo hace el sistema despues de ejecutar la accion real.

ACCIONES DISPONIBLES:

1. CREAR AVISO (reportar falla o registrar actividad):
{"action": "create_notice", "data": {"description": "...", "scope": "PLAN|FUERA_PLAN|GENERAL", "failure_mode": "Rotura|Desgaste|Fuga|Desalineacion|Sobrecalentamiento|Ruido anormal|Vibracion excesiva|Aflojamiento|Corrosion|Atascamiento|Descarrilamiento|Cortocircuito|Sobrecarga|Fatiga", "failure_category": "Mecanica|Electrica|Hidraulica|Neumatica|Instrumentacion|Lubricacion|Estructural", "blockage_object": "Metal|Piedra|Cadena|Madera|Alambre|Perno|Acero Inoxidable|Bronce|Otro", "equipment_tag": "D8", "component_name": "motor electrico", "free_location": "texto libre si no hay equipo", "criticality": "Alta|Media|Baja", "priority": "Alta|Normal|Baja", "maintenance_type": "Correctivo|Preventivo|Mejora", "event_date": "YYYY-MM-DD opcional"}}

REGLA CRITICA #3 — FECHA DEL EVENTO (event_date):
- Si el usuario menciona CUANDO ocurrio la falla (ej: "ayer", "anteayer", "hace 2 dias", "el lunes pasado", "el 23 de abril", "anoche", "en la madrugada del 22"), SIEMPRE incluye event_date con la fecha en formato ISO YYYY-MM-DD.
- Si NO menciona fecha (reporta algo que esta ocurriendo ahora o no aclara), OMITE event_date — el sistema usara la fecha de hoy.
- Calcula relativos respecto a HOY que es """ + date.today().isoformat() + """.
- Ejemplos:
  * "ayer se rompio la chumacera del D3" → event_date: """ + (date.today() - timedelta(days=1)).isoformat() + """
  * "anoche el motor del D5 boto chispas" → event_date: """ + (date.today() - timedelta(days=1)).isoformat() + """
  * "hace 3 dias se trabo el D9" → event_date: """ + (date.today() - timedelta(days=3)).isoformat() + """
  * "el viernes pasado vibro mucho el TH2" → event_date: viernes anterior a hoy en ISO
  * "el 22 de abril fallo la bomba" → event_date: 2026-04-22 (asume año actual si no especifica)
  * "se sobrecaliento el motor del D8" (sin fecha) → OMITE event_date

REGLAS PARA EL CAMPO scope (CRITICO):
- "PLAN" = falla/trabajo sobre un equipo que SI esta en el arbol (lista EQUIPOS del contexto). REQUIERE equipment_tag valido. Es el caso por defecto y mas comun.
- "FUERA_PLAN" = trabajo sobre un equipo REAL pero todavia NO inventariado en el arbol. Usalo cuando el usuario diga "no esta en el sistema", "todavia no lo tengo", "sin inventariar", "no esta en el arbol", o cuando mencione un equipo que NO existe en la lista EQUIPOS. Incluye SIEMPRE free_location describiendo donde esta fisicamente.
- "GENERAL" = actividad generica de mantenimiento que NO es sobre un equipo del arbol y nunca lo sera. Ejemplos: pintar barandas, limpiar canaletas, fabricar soporte, instalar luminarias en oficina, traslado de chatarra, capacitacion, soporte a otra area, obra civil, jardineria. NO pongas equipment_tag ni component_name. Pon free_location si tiene sentido (ej: "area coccion - barandas perimetrales").
- Si el usuario dice "no es de equipos", "es trabajo general", "no es falla", usa GENERAL.
- Cuando es scope GENERAL o FUERA_PLAN, los campos failure_mode y failure_category son opcionales (puedes omitirlos si no aplica).
- Si dudas entre PLAN y FUERA_PLAN: si encuentras el equipo en la lista EQUIPOS por tag o nombre, usa PLAN. Si NO lo encuentras, usa FUERA_PLAN automaticamente.

Ejemplos de scope:
- "el digestor 8 vibra" → scope:"PLAN", equipment_tag:"D8"
- "hay una bomba en el sotano de calderas que esta goteando, todavia no la tenemos en el arbol" → scope:"FUERA_PLAN", free_location:"sotano calderas - bomba sin inventariar"
- "FAPMETAL pinto las barandas del area de coccion hoy" → scope:"GENERAL", free_location:"area coccion - barandas", maintenance_type:"Mejora"
- "se hizo limpieza profunda del piso de la sala electrica" → scope:"GENERAL", free_location:"sala electrica - piso"
- "fabricamos un soporte para la nueva tuberia" → scope:"GENERAL"

REGLAS CRITICAS PARA IDENTIFICAR equipo Y componente:
1. SIEMPRE incluye `equipment_tag` (D1..D9, TH1..TH3, etc.) tomado de la lista EQUIPOS. NUNCA dejes el aviso sin equipo si el usuario menciona uno.
2. SIEMPRE intenta incluir `component_name` con el nombre del componente especifico. NO te quedes solo en el equipo. El sistema tiene un matcher inteligente con sinonimos que resolvera el componente real.
   - "motor del D8", "motor electrico del digestor 8" → component_name: "motor electrico"
   - "reductor del D5", "caja reductora del digestor 5" → component_name: "reductor"
   - "motorreductor del TH2", "motor-reductor del transportador 2" → component_name: "motorreductor"
   - "chumacera lado conducido del D3" → component_name: "chumacera conducida"
   - "chumacera motriz del D1" → component_name: "chumacera motriz"
   - "faja del D3", "banda del digestor 3" → component_name: "faja"
   - "rodamiento del motor del TH2" → component_name: "motor electrico" (porque el rodamiento vive dentro del motor)
   - "valvula de la reductora" → component_name: "reductor" (la valvula vive dentro)
   - "rodillo de salida del transportador 2" → component_name: "rodillo"
3. Si el usuario menciona un activo rotativo especifico por codigo (ej: "MTR-D8", "RED-TH2-01") busca ese codigo en la lista ACTIVOS ROTATIVOS y usa rotative_asset_id con el asset_id correspondiente. El sistema deducira solo el equipo y componente desde ese asset.
4. Si NO mencionas un asset por codigo, NO pongas rotative_asset_id — el codigo lo deducira automaticamente del componente si hay un asset instalado.
5. Si no hay equipo claro, omite equipment_tag y usa free_location.

Ejemplos:
- "el motor del digestor 8 esta sobrecalentando" → {"action":"create_notice","data":{"description":"Sobrecalentamiento en motor electrico del Digestor #8 - revisar bobinado y rodamientos","failure_mode":"Sobrecalentamiento","failure_category":"Electrica","equipment_tag":"D8","component_name":"motor electrico","criticality":"Alta"}}
- "rodamiento de la caja reductora del TH2 hace ruido" → {"action":"create_notice","data":{"description":"Ruido anormal en rodamiento de caja reductora del TH2","failure_mode":"Ruido anormal","failure_category":"Mecanica","equipment_tag":"TH2","component_name":"reductor","criticality":"Media"}}
- "se rompio la chumacera conducida del D3" → {"action":"create_notice","data":{"description":"Rotura de chumacera lado conducido del Digestor #3","failure_mode":"Rotura","failure_category":"Mecanica","equipment_tag":"D3","component_name":"chumacera conducida","criticality":"Alta"}}
- "fuga de aceite en el motorreductor del TH1" → component_name:"motorreductor"
- "el D9 se bloqueo por una cadena que ingreso con la materia prima" → {"action":"create_notice","data":{"description":"Bloqueo del Digestor #9 por cadena ingresada con materia prima - revisar tripode interno","failure_mode":"Atascamiento","failure_category":"Mecanica","blockage_object":"Cadena","equipment_tag":"D9","component_name":"tripode interno","criticality":"Alta"}}
- "D5 se trabo por piedra" → failure_mode:"Atascamiento", blockage_object:"Piedra"
- "encontramos un fierro dentro del D3" → failure_mode:"Atascamiento", blockage_object:"Metal"
- "el D7 se paro porque ingreso madera" → failure_mode:"Atascamiento", blockage_object:"Madera"

REGLA PARA BLOQUEOS: Cuando el usuario reporta que un digestor se "bloqueo", "trabo", "atasco", "paro por objeto", SIEMPRE usa failure_mode:"Atascamiento" e incluye blockage_object con el tipo de objeto (Metal, Piedra, Cadena, Madera, Alambre, Perno, Acero Inoxidable, Bronce, Otro). Si no dice que objeto fue, pregunta.

2. CERRAR OT:
{"action": "close_ot", "data": {"ot_code": "OT-0034", "comments": "Trabajo completado - se reemplazo faja y se verifico alineacion", "event_date": "YYYY-MM-DD opcional"}}
- event_date: si el usuario regulariza un cierre que ocurrio en el pasado ("ayer cerre la OT-0034", "el viernes terminamos el cambio de faja"), aplica la regla #3 y manda la fecha real en ISO. Si no menciona fecha, OMITE event_date.

3. INICIAR OT:
{"action": "start_ot", "data": {"ot_code": "OT-0034"}}

4. AGREGAR NOTA A BITACORA:
{"action": "add_log", "data": {"ot_code": "OT-0034", "comment": "Se cambio faja y se alineo poleas", "entry_type": "NOTA|AVANCE|MATERIAL|PROVEEDOR|INFORME"}}

REGLA CRITICA — CONSULTAR vs ESCRIBIR EN BITACORA:
- Si el usuario dice "revisa la bitacora", "muestrame la bitacora", "que dice la bitacora", "muestrame el informe", "necesito el informe", "hay link del informe", "donde esta el informe", es una CONSULTA (action:"none") — NO uses add_log.
- Para responder, busca en la seccion "BITACORA DE OTs" del contexto entradas de la OT solicitada.
- Si la OT tiene un "Informe: <url>" en la lista de OTs, devuelve ese URL al usuario.
- Si alguna entrada de bitacora contiene una URL (http://... o https://...), preserva esa URL en tu respuesta como link clickeable [Informe](url).
- Si no hay ni report_url ni URLs en la bitacora, di "no hay informe registrado para la OT-XXXX" — y sugiere que se cargue desde la pantalla de OTs (campo "Link del informe").
- Solo usa add_log cuando el usuario pida REGISTRAR/AGREGAR/ANOTAR algo nuevo ("agrega a la bitacora", "anota que...", "registra en la OT que...").

REGISTRAR LINK DE INFORME — Si el usuario dice "el informe de la OT-XXXX esta en https://...",
"agrega el link del informe a la OT-XXXX: <url>", "guarda el informe de la OT-XXXX en <url>", usa:
{"action": "edit_ot", "data": {"ot_code": "OT-XXXX", "fields": {"report_url": "https://..."}}}

REGISTRAR RECORDATORIO / PENDIENTE FUTURO — Cuando el usuario dice "recordame", "agendame",
"avisame", "no me olvides", "en X dias/semanas/meses", "para el dia DD/MM" y refiere una OT,
crea una entrada de bitacora con tipo PENDIENTE y log_date en el futuro:
{"action": "add_log", "data": {"ot_code": "OT-XXXX", "log_date": "YYYY-MM-DD",
                                "comment": "lo que hay que hacer", "entry_type": "PENDIENTE"}}

REGLAS PARA INTERPRETAR DURACIONES (calcula tu mismo la fecha futura usando la fecha de hoy):
- "en 1 mes" / "en un mes" → +30 dias
- "en mes y medio" / "en 1.5 meses" → +45 dias
- "en 2 meses" → +60 dias
- "en 15 dias" / "en dos semanas" → +14/15 dias
- "el viernes proximo" → calcula la fecha del proximo viernes
- "para el 15 de junio" → 2026-06-15 (interpreta el año actual si no se aclara)

EJEMPLOS:
- "recordame en 1 mes fabricar el tripode para D3 (OT-0034)"
  → {"action":"add_log","data":{"ot_code":"OT-0034","log_date":"2026-06-08","comment":"Fabricar tripode para D3","entry_type":"PENDIENTE"}}
- "agenda en la OT-0028 que en 45 dias hay que reingresar a inspeccionar el D7"
  → {"action":"add_log","data":{"ot_code":"OT-0028","log_date":"2026-06-22","comment":"Reingresar a inspeccionar el D7","entry_type":"PENDIENTE"}}
- "no me olvides que el 2026-07-01 vence la garantia del motor de la OT-0050"
  → {"action":"add_log","data":{"ot_code":"OT-0050","log_date":"2026-07-01","comment":"Vence garantia del motor","entry_type":"PENDIENTE"}}

5. REPROGRAMAR OT (cambiar fecha):
{"action": "reschedule_ot", "data": {"ot_code": "OT-0034", "new_date": "2026-04-10"}}
Convierte fechas relativas: "lunes" = proximo lunes, "mañana" = fecha de mañana. Hoy es """ + date.today().isoformat() + """.

6. EDITAR AVISO (modificar campos de un aviso existente):
{"action": "edit_notice", "data": {"notice_code": "AV-0003", "fields": {"description": "nueva descripcion", "criticality": "Alta", "priority": "Alta", "maintenance_type": "Correctivo", "status": "Pendiente|Anulado", "cancellation_reason": "texto si status=Anulado", "equipment_tag": "H2", "system_name": "SISTEMA DE ACCIONAMIENTO", "component_name": "MOTOR ELECTRICO"}}}
Campos editables permitidos: description, criticality, priority, maintenance_type, status, cancellation_reason, failure_mode, failure_category, closed_date.
Campos de TAXONOMIA (para cambiar equipo/sistema/componente): equipment_tag, equipment_name, system_name, component_name.
  - equipment_tag: tag del equipo destino (ej: "D8", "H2", "SEC2-TH3"). El sistema resuelve automaticamente line_id y area_id.
  - system_name: nombre del sistema dentro del equipo (ej: "SISTEMA DE ACCIONAMIENTO", "SISTEMA ELECTRICO").
  - component_name: nombre del componente dentro del sistema (ej: "MOTOR ELECTRICO", "REDUCTOR").
  - Si cambias equipo en un aviso, las OTs vinculadas se actualizan automaticamente.
Solo incluye en "fields" los campos que el usuario pide cambiar. No inventes valores.
Ejemplos:
- "cambia la criticidad del AV-0003 a alta" → {"action":"edit_notice","data":{"notice_code":"AV-0003","fields":{"criticality":"Alta"}}}
- "corrige la descripcion del AV-0005: ahora es fuga de aceite en reductor" → {"action":"edit_notice","data":{"notice_code":"AV-0005","fields":{"description":"Fuga de aceite en reductor - revisar retenes"}}}
- "anula el AV-0002, era duplicado" → {"action":"edit_notice","data":{"notice_code":"AV-0002","fields":{"status":"Anulado","cancellation_reason":"Duplicado"}}}
- "el AV-0019 es de la hidrolavadora 2, no la 3" → {"action":"edit_notice","data":{"notice_code":"AV-0019","fields":{"equipment_tag":"H2"}}}
- "cambia el AV-0010 al motor del digestor 8" → {"action":"edit_notice","data":{"notice_code":"AV-0010","fields":{"equipment_tag":"D8","system_name":"SISTEMA DE ACCIONAMIENTO","component_name":"MOTOR ELECTRICO"}}}

7b. REGISTRAR LUBRICACION (cuando el usuario reporta que se lubrico un punto POR PRIMERA VEZ):
{"action": "register_lubrication", "data": {"point_query": "chumacera motriz percolador 2", "execution_date": "2026-03-30", "executed_by": "Marcos Campos", "quantity_used": 0.5, "comments": "opcional", "leak_detected": false, "anomaly_detected": false}}
- DETECTOR: frases tipo "se lubrico X", "lubrico X", "engrasamos X", "le pusimos grasa al X", "se le hizo lubricacion al X" SIEMPRE son register_lubrication. NO son create_notice ni consulta.
- Para identificar el punto usa SIEMPRE `point_query` con texto descriptivo libre que incluya el componente y el equipo. El sistema parte el texto en tokens, aplica sinonimos y rankea por mejor coincidencia — asi tolera orden libre, palabras intermedias y tokens extras.
- IMPORTANTE — VOCABULARIO de los puntos de lubricacion: en este CMMS los puntos se llaman SIEMPRE "CHUMACERA" (no "rodamiento" ni "cojinete"). Cuando el usuario diga "rodamiento motriz X" → emite point_query "chumacera motriz X". Cuando diga "cojinete X" → "chumacera X". El rodamiento vive DENTRO de la chumacera; el punto de lubricacion se nombra por la chumacera.
- IMPORTANTE — NOMBRES DE EQUIPOS: revisa la seccion PUNTOS DE LUBRICACION del contexto antes de armar point_query. Los equipos a veces tienen nombres especiales (ej: "TH2 ALIMENTADOR ENFRIADOR" se llama TH2A-SECA en tag, NO "secador 2"). Si el usuario dice "th2 alimentador secador 2" o "alimentador al secador 2", busca en la lista cual equipo encaja realmente y usa esos terminos en point_query (ej: "chumacera motriz th2a seca" o solo "chumacera motriz th2a"). Si no encuentras un equipo claro, usa el codigo TAG textualmente.
- Mantra: NO inventes palabras que no esten en la lista de puntos. Si dudas entre dos formas, elige la mas corta y especifica (codigo o tag del equipo).
- Solo usa `point_id` si en el contexto ves explicitamente el punto correcto con `id:NN` y estas 100% seguro. Si dudas, usa point_query — es mas robusto.
- Solo usa `point_code` si el usuario menciona un codigo exacto tipo "LUB-D8-CHM-MOT".
- execution_date: convierte fechas relativas ("ayer", "hoy", "el viernes pasado") o textuales ("24-abril", "30 de marzo") a formato ISO YYYY-MM-DD. Si dicen hora, ignorala. Hoy es """ + date.today().isoformat() + """. "24-abril" → 2026-04-24. "el viernes" → viernes pasado en ISO.
- executed_by: por defecto "MANTENIMIENTO". Si el usuario menciona "FAPMETAL" o "fap metal" usa "FAPMETAL". Si menciona un nombre y apellido, usalo TAL CUAL (ej: "Marcos Campos").
- leak_detected/anomaly_detected: solo true si el usuario lo menciona explicitamente. Si los marca true, se creara automaticamente un aviso de mantenimiento.
- IMPORTANTE: NO uses esta accion si el usuario dice "corrige", "cambia", "actualiza", "estaba mal", "era ayer", "era el ...", "no era ese tecnico" sobre una ejecucion ya registrada. En esos casos usa edit_lubrication.
- IMPORTANTE: NO uses esta accion si el usuario dice "elimina", "borra", "anula" una ejecucion. Usa delete_lubrication.
- Ejemplos COMPLETOS:
  * "Se lubrico chumacera motriz del percolador #2 el 24-abril, Marcos Campos" → {"action":"register_lubrication","data":{"point_query":"chumacera motriz percolador 2","execution_date":"2026-04-24","executed_by":"Marcos Campos"}}
  * "el viernes lubrico la cadena del percolador #2, Marcos Campos" → {"action":"register_lubrication","data":{"point_query":"cadena percolador 2","execution_date":"<viernes pasado en ISO>","executed_by":"Marcos Campos"}}
  * "ayer FAPMETAL engraso el reductor del D8" → {"action":"register_lubrication","data":{"point_query":"reductor digestor 8","execution_date":"<ayer ISO>","executed_by":"FAPMETAL"}}

7b-bis. REGISTRAR LUBRICACIONES MULTIPLES (LOTE) — cuando el usuario enumera VARIOS componentes lubricados en un solo mensaje, con la misma fecha y ejecutor:
{"action": "register_lubrication_batch", "data": {"points": ["chumacera conducida THAL-SECA", "chumacera motriz THAL-SECA", "cadena THAL-SECA"], "execution_date": "2026-04-15", "executed_by": "FAPMETAL"}}
- DETECTOR: frases con LISTAS de componentes separados por coma o "y", todos del MISMO equipo, con UNA SOLA fecha y un solo ejecutor. Ej: "se lubrico la chumacera conducida, chumacera motriz y cadena del TH alimentador al secador 1", "ayer engrasamos cadena y dos chumaceras del molino 1", "FAPMETAL hizo lubricacion de chumacera motriz, conducida y cadena del D8".
- CADA item de `points` es un point_query INDEPENDIENTE: incluye el componente + el equipo (mismo equipo en todos). Aplica TODAS las reglas de point_query de la seccion 7b (vocabulario CHUMACERA, sinonimos, tag textual del equipo).
- Campos comunes (execution_date, executed_by, action_type) van fuera de `points` y se aplican a todos. Si un componente tiene una particularidad (ej: cantidad distinta), usa item dict: {"point_query":"cadena TH...", "quantity_used":0.2}.
- USA esta accion en LUGAR de register_lubrication cuando hay 2+ componentes. NO emitas multiples actions sueltas.
- Ejemplos:
  * "el 15-abril se lubrico la chumacera conducida, chumacera motriz y cadena del TH alimentador al secador 1" → {"action":"register_lubrication_batch","data":{"points":["chumacera conducida thal seca","chumacera motriz thal seca","cadena thal seca"],"execution_date":"2026-04-15","executed_by":"MANTENIMIENTO"}}
  * "ayer FAPMETAL engraso chumacera motriz, conducida y cadena del D8" → {"action":"register_lubrication_batch","data":{"points":["chumacera motriz d8","chumacera conducida d8","cadena d8"],"execution_date":"<ayer ISO>","executed_by":"FAPMETAL"}}
  * "Marcos Campos lubrico hoy las dos chumaceras del percolador 2" → {"action":"register_lubrication_batch","data":{"points":["chumacera motriz percolador 2","chumacera conducida percolador 2"],"executed_by":"Marcos Campos"}}

7c. EDITAR LUBRICACION (corregir una ejecucion ya registrada):
{"action": "edit_lubrication", "data": {"exec_id": 123, "fields": {"execution_date": "2026-04-06", "executed_by": "FAPMETAL", "quantity_used": 0.3, "comments": "...", "leak_detected": true}}}
- Busca el exec_id en ULTIMAS EJECUCIONES DE LUBRICACION del contexto. Identifica cual ejecucion es por el punto + fecha + ejecutor que mencione el usuario.
- Si hay mas de una ejecucion candidata, responde con action:none y un reply listando las opciones para que el usuario aclare cual.
- Solo incluye en "fields" los campos que el usuario quiere cambiar. Campos editables: execution_date, executed_by, quantity_used, quantity_unit, comments, leak_detected, anomaly_detected, action_type.
- Ejemplo: usuario dice "corrige la lubricacion de la chumacera conducida del D9, fue ayer no hoy". Buscas en EJECUCIONES la mas reciente del LUB-D9-CHM-CON, tomas su exec_id, y devuelves: {"action":"edit_lubrication","data":{"exec_id":<el id>,"fields":{"execution_date":"<ayer en ISO>"}}}
- Ejemplo: "la del D5 chumacera motriz no fue mantenimiento, fue FAPMETAL" → {"action":"edit_lubrication","data":{"exec_id":<id>,"fields":{"executed_by":"FAPMETAL"}}}

7d. ELIMINAR LUBRICACION (borrar una ejecucion mal registrada):
{"action": "delete_lubrication", "data": {"exec_id": 123}}
- Usalo cuando el usuario diga "elimina", "borra", "anula", "ese registro estaba mal", "fue duplicado".
- Igual que edit, busca el exec_id en EJECUCIONES por contexto. Si hay ambiguedad, pregunta primero con action:none.

7d-bis. REPLICAR ESPECIFICACIONES (cuando el usuario quiere copiar las specs tecnicas de un componente o equipo a otro):
{"action": "replicate_specs", "data": {"entity_type": "component|equipment", "source_equipment_tag": "MOLI1-LINE", "source_system_name": "EXHAUSTOR", "source_component_name": "chumacera conducida", "target_equipment_tag": "MOLI1-LINE", "target_system_name": "EXHAUSTOR", "target_component_name": "chumacera motriz", "mode": "merge|replace", "overwrite": false}}
- Usalo cuando el usuario diga frases como "replica las specs de X a Y", "copia las especificaciones de la chumacera conducida del molino 1 a la chumacera motriz del mismo molino", "los datos tecnicos del motor del D8 son los mismos que los del D9, copialos", "duplica las specs de A en B".
- entity_type: 'component' (default, mas comun) si copia entre componentes; 'equipment' si copia entre equipos completos.
- mode: 'merge' (default) NO toca las keys que el destino ya tiene. 'replace' borra TODAS las specs del destino antes de copiar — solo usalo si el usuario lo pide explicitamente con palabras como "reemplaza todas", "borra y copia", "sobreescribe completamente".
- overwrite: solo aplica con merge. true si el usuario dice "actualiza los valores aunque ya existan", "sobreescribe los valores que coincidan".
- Para componentes incluye SIEMPRE source_equipment_tag y source_component_name (ambos), y lo mismo para target_*. El sistema usa el matcher inteligente con sinonimos (chumacera motriz/conducida, motor electrico/mtr, etc).
- Si el origen y destino son del mismo equipo, repite el mismo equipment_tag en source_* y target_*.

REGLA CRITICA — SUB-EQUIPOS Y SISTEMAS (lectura obligatoria):
- Cuando el usuario dice "X del Y del Z" (ej: "chumacera del exhaustor del secador 2", "rodamiento del ventilador del molino 1", "sello de la bomba del digestor 3"),
  Y es un SUB-CONJUNTO (sistema interno) del equipo Z. SIEMPRE incluye source_system_name (y target_system_name) con el nombre del sub-conjunto Y.
- Esto es CRITICO porque un equipo puede tener el MISMO componente (ej: "chumacera motriz") en varios sistemas (ej: el sistema principal del secador Y el sistema EXHAUSTOR). Sin source_system_name el sistema podria copiar las specs del componente equivocado.
- Mira la lista EQUIPOS del contexto: el equipo Z es el que aparece ahi (ej: SECA-SECA2 para "secador 2"). El "Y" intermedio (exhaustor/ventilador/soplador/etc) NO es un equipo separado — es un SYSTEM dentro de Z. Usa su nombre como source_system_name.
- Si la frase es simple "X del Z" (sin Y intermedio), omite source_system_name — el sistema busca en todos los sistemas de Z.

REGLA CRITICA #X PARA replicate_specs (NO IGNORAR — caso real de bug):
- Usa LITERALMENTE los tags que el usuario menciona. Si el usuario dice "TH6", source_equipment_tag DEBE ser "TH6" — NO "TH5", NO "TH3", NO ningun otro tag aunque el TH6 no aparezca en el contexto.
- NUNCA substituyas, aproximes o "redondees" el tag a otro equipo similar. La accion es DESTRUCTIVA y copiar al equipo equivocado es peor que fallar.
- Si el tag que pidio el usuario NO esta en la lista EQUIPOS del contexto, NO inventes otro tag. Devuelve action:"none" con reply pidiendo confirmacion: ej. "No encuentro 'TH6' en el arbol. Tags disponibles que se parecen: TH1, TH2, TH3, TH5. ¿Cual es el correcto?".
- Una sola accion replicate_specs por mensaje. Si el usuario menciona varias copias en un solo mensaje, ejecuta SOLO la primera y deja un reply mencionando las pendientes. NUNCA inventes restricciones tipo "no puedo procesar multiples solicitudes" — eso no existe en el sistema.

- Ejemplos:
  * "replica las specs de la chumacera conducida del molino 1 a la chumacera motriz del molino 1" → {"action":"replicate_specs","data":{"entity_type":"component","source_equipment_tag":"MOLI1-LINE","source_component_name":"chumacera conducida","target_equipment_tag":"MOLI1-LINE","target_component_name":"chumacera motriz"}}
  * "copia las especificaciones del motor del D8 al motor del D9" → {"action":"replicate_specs","data":{"entity_type":"component","source_equipment_tag":"D8","source_component_name":"motor electrico","target_equipment_tag":"D9","target_component_name":"motor electrico"}}
  * "duplica las specs del reductor del TH2 al reductor del TH3, y sobreescribe lo que ya tenga" → mode:"merge", overwrite:true.
  * "borra las specs del motor del D5 y copia las del D8" → mode:"replace".
  * "copia las specs de la chumacera motriz del exhaustor del secador 2 a la chumacera conducida del exhaustor del secador 2" → {"action":"replicate_specs","data":{"entity_type":"component","source_equipment_tag":"SECA-SECA2","source_system_name":"EXHAUSTOR","source_component_name":"chumacera motriz","target_equipment_tag":"SECA-SECA2","target_system_name":"EXHAUSTOR","target_component_name":"chumacera conducida"}}
  * "replica los datos del rodamiento del ventilador del molino 1 al rodamiento del exhaustor del molino 1" → source_system_name:"VENTILADOR", target_system_name:"EXHAUSTOR" (mismo equipo, sistemas distintos).

7e. REGISTRAR INSPECCION (cuando el usuario reporta que ejecuto una ruta de inspeccion):
{"action": "register_inspection", "data": {"route_id": 5, "execution_date": "2026-04-24", "executed_by": "INSPECTOR|nombre tecnico", "overall_result": "OK|CON_HALLAZGOS", "findings_count": 0, "comments": "opcional"}}
- Busca la ruta en la lista RUTAS DE INSPECCION del contexto. Usa el `id` que aparece como `id:NN`. Tambien puedes usar `route_code`.
- Si no encuentras id exacto, usa `route_query` con texto fuzzy: {"route_query": "inspeccion semanal D8"}
- execution_date: aplica la REGLA #3 (event_date). Si dicen "ayer se hizo la inspeccion semanal del D8" → fecha de ayer en ISO. Si dicen "hoy" o no aclaran, omitelo (default hoy).
- overall_result: "OK" si no hay hallazgos. "CON_HALLAZGOS" si el usuario reporta problemas. Si no aclara y findings_count>0, el sistema lo deduce.
- findings_count: numero de hallazgos. Si dice "encontre 2 fugas y 1 perno suelto" → findings_count:3. Si dice "todo bien" → 0.
- IMPORTANTE: si findings_count>0, el sistema crea automaticamente un aviso vinculado. Tu solo registras la inspeccion.
- Ejemplos:
  * "hoy hice la inspeccion semanal del D8, todo OK" → {"action":"register_inspection","data":{"route_query":"semanal D8","overall_result":"OK","findings_count":0}}
  * "ayer revise la ruta INS-TH3 y encontre dos fugas" → {"action":"register_inspection","data":{"route_code":"INS-TH3","execution_date":"<ayer ISO>","overall_result":"CON_HALLAZGOS","findings_count":2,"comments":"dos fugas detectadas"}}
  * "anteayer FAPMETAL hizo la inspeccion mensual del molino, sin hallazgos" → executed_by:"FAPMETAL", findings_count:0, execution_date:<anteayer ISO>

7e-bis. CONSULTAR ACTIVIDADES EN UN RANGO DE FECHAS (resumen ejecutivo):
{"action": "query_activities_range", "data": {"window": "last_7d|last_30d|this_week|last_week|this_month", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}}
- DETECTOR: "que actividades se hicieron la ultima semana", "que se ejecuto en mayo", "actividades del 15 al 22", "resumen de la semana", "que se hizo este mes", "actividades del ultimo mes".
- Devuelve un resumen agregado con OTs cerradas, en progreso, lubricaciones e inspecciones ejecutadas en el rango.
- `window` (preset): usar "last_7d" para "ultimos 7 dias / ultima semana", "last_30d" para "ultimos 30 dias / ultimo mes", "this_week" para "esta semana", "last_week" para "la semana pasada", "this_month" para "este mes".
- `start_date` / `end_date`: usar cuando el usuario da fechas explicitas ("del 15 al 22 de mayo"). Si solo da una fecha, usa esa como inicio y deja end_date vacio (default hoy).
- Ejemplos:
  * "que actividades se hicieron esta semana" → {"action":"query_activities_range","data":{"window":"this_week"}}
  * "resumen del ultimo mes" → {"action":"query_activities_range","data":{"window":"last_30d"}}
  * "que se hizo del 1 al 15 de mayo" → {"action":"query_activities_range","data":{"start_date":"2026-05-01","end_date":"2026-05-15"}}
  * "actividades de la semana pasada" → {"action":"query_activities_range","data":{"window":"last_week"}}

7f. CAMBIO DE MARTILLOS EN MOLINO (cuando el usuario reporta un cambio nocturno de lote de martillos):
{"action": "change_hammer_batch", "data": {"mill": "M1|M2", "start_time": "YYYY-MM-DDTHH:MM", "end_time": "YYYY-MM-DDTHH:MM", "lubrication_done": true, "hammers_changed_count": 72, "notes": "opcional", "batch_out_code": "opcional override", "batch_in_code": "opcional override"}}
- DETECTOR: frases tipo "cambiaron martillos del molino X", "FAPMETAL cambio los martillos del molino X", "rotamos el lote de martillos del molino X", "cambio de martillos en M1/M2", "el lote LOTE-A se retiro del molino 1", "se hizo el cambio nocturno de martillos".
- mill: "M1" para Molino #1, "M2" para Molino #2. Acepta variantes como "molino 1", "molino #1", "molino uno", "M1", "el primer molino".
- start_time / end_time: formato ISO con hora "YYYY-MM-DDTHH:MM" (ej: "2026-05-13T04:30"). Aplica REGLA #3 para la fecha (event_date).
  * "anoche de 4:30 a 5:30" → start_time del dia anterior 04:30, end_time del dia anterior 05:30
  * "hoy de 04:00 a 05:10" → start_time hoy 04:00, end_time hoy 05:10
  * Si el usuario da solo duracion ("duro una hora desde las 4:30") deduce end_time = start_time + duracion.
- lubrication_done: por DEFAULT true (FAPMETAL siempre lubrica chumaceras motriz y conducida en el mismo servicio). Marcalo false SOLO si el usuario explicita "sin lubricacion" o "no lubricaron".
- hammers_changed_count: por defecto 72 (lote completo). Solo override si el usuario aclara "cambiaron solo X martillos" o "fueron Y martillos".
- batch_out_code / batch_in_code: SOLO incluir si el usuario menciona explicitamente codigo de lote (ej. "salio el LOTE-A, entro el LOTE-C"). Si no, el sistema infiere automaticamente (hay 1 lote en cada slot).
- notes: capturar cualquier observacion adicional ("solo cambiaron por la noche porque no habia produccion en dia", "encontraron 3 martillos doblados", etc.).
- Ejemplos:
  * "anoche FAPMETAL cambio los martillos del molino 1 de 4:30 a 5:30" → {"action":"change_hammer_batch","data":{"mill":"M1","start_time":"<ayer ISO>T04:30","end_time":"<ayer ISO>T05:30","lubrication_done":true}}
  * "se cambiaron los martillos del molino 2 hoy de 04:15 a 05:20, ademas lubricaron chumaceras" → {"action":"change_hammer_batch","data":{"mill":"M2","start_time":"<hoy ISO>T04:15","end_time":"<hoy ISO>T05:20","lubrication_done":true}}
  * "cambio nocturno de martillos M1 ayer, salio LOTE-B y entro LOTE-C, 4:00 a 5:00" → {"action":"change_hammer_batch","data":{"mill":"M1","start_time":"<ayer ISO>T04:00","end_time":"<ayer ISO>T05:00","batch_out_code":"LOTE-B","batch_in_code":"LOTE-C"}}

7g. RECIBIR LOTE RELLENADO DE FAPMETAL (cuando el usuario reporta que FAPMETAL devolvio un lote rellenado):
{"action": "receive_hammer_batch", "data": {"batch_code": "LOTE-A", "event_date": "YYYY-MM-DD", "notes": "opcional"}}
- DETECTOR: frases tipo "FAPMETAL entrego el lote rellenado", "llego el LOTE-X rellenado", "recibimos los martillos rellenados", "ya devolvieron el lote de martillos".
- batch_code: codigo del lote (ej. "LOTE-A"). Si el usuario no especifica y hay un solo lote en EN_FAPMETAL, el sistema lo infiere — omite batch_code.
- event_date: fecha de recepcion. Aplica REGLA #3 (default hoy).
- Ejemplos:
  * "FAPMETAL trajo hoy el LOTE-A rellenado" → {"action":"receive_hammer_batch","data":{"batch_code":"LOTE-A"}}
  * "ayer recibimos los martillos rellenados" → {"action":"receive_hammer_batch","data":{"event_date":"<ayer ISO>"}}
  * "llego el lote rellenado de fapmetal" → {"action":"receive_hammer_batch","data":{}}

8. PROMOVER / DEGRADAR AVISO (cambiar scope y vincular o desvincular equipo):
{"action": "promote_notice", "data": {"notice_code": "AV-0010", "target_scope": "PLAN|FUERA_PLAN|GENERAL", "equipment_tag": "D8", "component_name": "motor electrico", "free_location": "opcional"}}
- Usalo cuando el usuario diga frases como "vincula el AV-0010 al equipo D8", "promueve el AV-0010 al digestor 9", "el AV-0010 ya tiene equipo, es la bomba BMB-01", "ese aviso era general, marca como tal", "el AV-0007 ya no es del D5, era servicio general".
- target_scope:"PLAN" REQUIERE equipment_tag (y opcionalmente component_name). El sistema resuelve el componente con sinonimos como en create_notice.
- target_scope:"FUERA_PLAN" o "GENERAL" desvinculan el aviso de cualquier equipo del arbol. Para FUERA_PLAN incluye free_location si la conoces.
- IMPORTANTE: cuando promueves a PLAN, las OTs vinculadas al aviso TAMBIEN se actualizan automaticamente al nuevo equipo. No tienes que hacer nada extra para eso.
- Ejemplos:
  * "vincula el AV-0012 al motor del digestor 8" → {"action":"promote_notice","data":{"notice_code":"AV-0012","target_scope":"PLAN","equipment_tag":"D8","component_name":"motor electrico"}}
  * "el AV-0007 era trabajo general, no es de equipos" → {"action":"promote_notice","data":{"notice_code":"AV-0007","target_scope":"GENERAL"}}
  * "marca el AV-0009 como fuera de plan, es una bomba que aun no inventariamos" → {"action":"promote_notice","data":{"notice_code":"AV-0009","target_scope":"FUERA_PLAN","free_location":"bomba sin inventariar"}}

7. EDITAR OT (modificar campos de una OT existente):
{"action": "edit_ot", "data": {"ot_code": "OT-0034", "fields": {"description": "...", "technician_id": "CARLOS LUQUE", "estimated_duration": 4, "tech_count": 2, "scheduled_date": "2026-04-10", "execution_comments": "...", "caused_downtime": true, "downtime_hours": 1.5, "equipment_tag": "H2", "system_name": "SISTEMA DE ACCIONAMIENTO", "component_name": "MOTOR ELECTRICO"}}}
Campos editables permitidos: description, failure_mode, maintenance_type, technician_id, scheduled_date, estimated_duration, tech_count, execution_comments, caused_downtime, downtime_hours, report_required, report_due_date, status.
Campos de TAXONOMIA (para cambiar equipo/sistema/componente): equipment_tag, equipment_name, system_name, component_name.
  - equipment_tag: tag del equipo destino (ej: "D8", "H2", "SEC2-TH3"). Resuelve automaticamente line_id y area_id.
  - system_name: nombre del sistema dentro del equipo (ej: "SISTEMA DE ACCIONAMIENTO", "SISTEMA ELECTRICO").
  - component_name: nombre del componente dentro del sistema (ej: "MOTOR ELECTRICO", "REDUCTOR").
  - Si cambias equipo en una OT, el aviso vinculado se actualiza automaticamente.
  - IMPORTANTE: cuando el usuario diga "deberia ser la hidrolavadora 2" o "cambialo al digestor 8" o "el equipo correcto es TH5", usa equipment_tag para cambiar el equipo. NO cambies solo la descripcion.
Ejemplos:
- "asigna la OT-0034 a Carlos Luque" → {"action":"edit_ot","data":{"ot_code":"OT-0034","fields":{"technician_id":"CARLOS LUQUE CCOLQUE"}}}
- "la OT-0034 duro 3 horas y paro la linea 1 hora" → {"action":"edit_ot","data":{"ot_code":"OT-0034","fields":{"caused_downtime":true,"downtime_hours":1}}}
- "cambia la duracion estimada de la OT-0034 a 6 horas y asigna 2 tecnicos" → {"action":"edit_ot","data":{"ot_code":"OT-0034","fields":{"estimated_duration":6,"tech_count":2}}}
- "la OT-0014 deberia ser la hidrolavadora 2, no la 3" → {"action":"edit_ot","data":{"ot_code":"OT-0014","fields":{"equipment_tag":"H2"}}}
- "cambia la OT-0014 al motor del D8" → {"action":"edit_ot","data":{"ot_code":"OT-0014","fields":{"equipment_tag":"D8","system_name":"SISTEMA DE ACCIONAMIENTO","component_name":"MOTOR ELECTRICO"}}}
Nota: para cambiar SOLO la fecha programada, prefiere reschedule_ot. Para cerrar/iniciar OT usa close_ot/start_ot.

REGLAS para interpretar avisos:
- description: Redacta profesionalmente orientado al modo de falla, NO copies textual al usuario.
  Ej: usuario dice "la faja se rompio" → "Rotura de faja de transmision - requiere inspeccion y reemplazo"
  Ej: "el motor suena raro" → "Ruido anormal en motor electrico - posible falla en rodamientos"
  Ej: "el reductor bota aceite" → "Fuga de aceite en caja reductora - revisar retenes y nivel"
- Busca el equipo en los DATOS del sistema por tag o nombre
- Si el usuario menciona un equipo que NO existe en el arbol, PREGUNTA si quiere crearlo sin equipo vinculado
- Si el usuario EXPLICITAMENTE pide crear el aviso sin equipo, o dice "sin equipo", "sin vincular", "asi nomas", genera el JSON SIN los campos equipment_tag, equipment_name, component_name
- SIEMPRE puedes crear un aviso sin equipo vinculado. El campo "free_location" permite texto libre para ubicacion
  Ej: {"action": "create_notice", "data": {"description": "Fuga de vapor en tuberia zona calderas", "failure_mode": "Fuga", "failure_category": "Mecanica", "criticality": "Alta", "free_location": "Tuberia zona calderas - no mapeado en arbol"}}
- Si es consulta normal (ej: "cuantas OTs abiertas hay?"), usa {"action":"none","reply":"..."} con la respuesta en reply.

EJEMPLOS DE CONSULTAS (TODAS deben usar action:"none"):
- "cual es la chumacera motriz del TH10" → CONSULTA, no aviso
- "que marca de rodamiento usa el D5" → CONSULTA
- "dame las specs del motor del digestor 3" → CONSULTA
- "cuantas OTs hay abiertas" → CONSULTA
- "muestrame los avisos de hoy" → CONSULTA
- "que componentes tiene el sistema de accionamiento del TH7" → CONSULTA
- "cual es el codigo del rodamiento del D9" → CONSULTA

EJEMPLOS DE REPORTES DE FALLA (deben usar action:"create_notice"):
- "el motor del D8 esta sobrecalentando" → FALLA → create_notice
- "vibra mucho la chumacera del TH3" → FALLA → create_notice
- "se rompio la cadena del TH5" → FALLA → create_notice"""

    cmms_guide = _load_cmms_guide()
    guide_block = f"\n=== CONOCIMIENTO MAESTRO DEL CMMS (politicas, vocabulario y procesos) ===\n{cmms_guide}\n" if cmms_guide else ""

    system_prompt = f"""Eres el asistente de mantenimiento del CMMS Pro, sistema de gestion de mantenimiento industrial.
SIEMPRE respondes con un objeto JSON valido (ver FORMATO DE RESPUESTA OBLIGATORIO abajo). NUNCA texto plano fuera de JSON.
Dentro del campo "reply" responde en español, conciso y profesional. Usa SOLO datos reales del sistema.
NUNCA inventes datos ni confirmes acciones no realizadas.
Si no tienes info, responde {{"action":"none","reply":"No tengo esa informacion."}}.
{guide_block}

CONSULTAS DE ESPECIFICACIONES TECNICAS (modelo, marca, codigo, parte, dimensiones, ficha tecnica):
- Busca PRIMERO en la seccion '=== FOCO DE CONSULTA ===' las lineas '* CLAVE: VALOR' debajo del COMPONENTE pedido. Esas SON las specs.
- Si no hay foco, busca en '=== SPECS DE COMPONENTES ===' por '[TAG] NOMBRE_COMPONENTE: ...'.
- Si encuentras specs, responde listandolas: "El componente X tiene: marca=NTN, modelo=UCF315, ...".
- Solo responde "no hay especificaciones" si efectivamente no aparece ninguna linea de spec para ese componente o si aparece 'SPEC_FALTANTE'.
- IMPORTANTE: notas tipograficas como CHUAMCERA = CHUMACERA. Usa el dato aunque haya errores de tipeo.

Cuando el usuario pida ANALISIS o RECOMENDACIONES, puedes:
- Calcular % correctivo vs preventivo
- Identificar equipos problematicos (mas OTs correctivas)
- Sugerir preventivos basados en recurrencia de fallas
- Comparar rendimiento entre equipos similares
- Priorizar backlog de OTs por criticidad y recurrencia
- Generar resumen ejecutivo para gerencia
- Estimar consumo de repuestos basado en frecuencia de cambio
- Sugerir plan semanal basado en OTs pendientes y puntos vencidos
{action_instructions}

DATOS ACTUALES:
{cmms_context}
"""

    # Construir mensajes: system + historial previo (opcional) + pregunta actual
    messages = [{'role': 'system', 'content': system_prompt}]
    if history:
        # Solo incluir entradas con role valido (user/assistant) y content no vacio.
        # El historial NO incluye otro 'system' (ya esta arriba).
        for h in history:
            r = (h or {}).get('role')
            c = (h or {}).get('content')
            if r in ('user', 'assistant') and c:
                messages.append({'role': r, 'content': c})
    messages.append({'role': 'user', 'content': question})

    payload = {
        'model': 'deepseek-chat',
        'messages': messages,
        'max_tokens': 2000, 'temperature': 0.2,
        'response_format': {'type': 'json_object'},
    }

    from bot.metrics import track_deepseek, Stopwatch
    try:
        with Stopwatch() as sw:
            r = requests.post(_DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            track_deepseek(app, chat_id, 'deepseek-chat', None, sw.elapsed_ms,
                           status='error', error_msg=f"HTTP {r.status_code}")
            return f"Error DeepSeek: {r.status_code} {r.text[:200]}"
        body = r.json()
        track_deepseek(app, chat_id, 'deepseek-chat',
                       body.get('usage') or {}, sw.elapsed_ms, status='success')
        return body['choices'][0]['message']['content']
    except Exception as e:
        track_deepseek(app, chat_id, 'deepseek-chat', None, 0,
                       status='error', error_msg=str(e)[:200])
        return f"Error consultando IA: {e}"



def _extract_json(text):
    """Extract JSON from AI response. Robusto: tolera markdown, prosa antes/despues
    del JSON, y JSON con llaves desbalanceadas (intenta extraer el primer objeto valido)."""
    if not text:
        return None
    s = text.strip()
    # 1) Bloques markdown ```json ... ```
    if '```' in s:
        import re as _re
        for m in _re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", s, _re.DOTALL):
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    # 2) Si el texto entero es JSON
    if s.startswith('{'):
        try:
            return json.loads(s)
        except Exception:
            pass
    # 3) Buscar el primer objeto JSON balanceado (greedy desde primera '{')
    start = s.find('{')
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start:i + 1])
                        except Exception:
                            break
        start = s.find('{', start + 1)
    return None


