# Propuestas — Asistente del Planificador de Mantenimiento

Objetivo: automatizar/asistir las gestiones diarias del planificador usando lo
que ya existe en este CMMS, en orden de esfuerzo/beneficio.

## Propuesta 1 — "Mi Dia" dentro del CMMS (recomendada para empezar)

Una pagina `/mi-dia` que arme sola la agenda del planificador al abrir el
sistema, leyendo datos que ya estan en la BD:

- Avisos nuevos sin atender (por criticidad).
- OTs vencidas y por vencer hoy/esta semana.
- Preventivos que vencen (lubricacion, monitoreo, inspecciones, megado).
- Compras/requerimientos pendientes de seguimiento.
- Alertas de equipos alquilados (fallas repetidas, horometros por vencer).
- Checklist personal del dia (tareas manuales que el planificador anota).

Esfuerzo: bajo (todo el dato ya existe; es una vista agregadora).
Beneficio: elimina los 30-45 min de "armar el panorama" cada manana.

## Propuesta 2 — Resumen diario automatico por Telegram

Ya existe un bot de Telegram en el proyecto (`bot/`). Agregar un job programado
(cron 6:00 am) que envie al planificador:

- 3 lineas de resumen: avisos criticos, OTs vencidas, preventivos de hoy.
- Alertas de equipos alquilados si las hay.

Esfuerzo: bajo-medio. Beneficio: el dia arranca priorizado sin abrir la PC.

## Propuesta 3 — Generador semanal de plan borrador

Boton "Generar borrador de semana" que proponga el programa semanal a partir
de: preventivos que vencen esa semana + OTs abiertas por prioridad + backlog
de requerimientos, balanceado por dia. El planificador solo ajusta y publica
(ya existe el modulo de Programa Nocturno/Plan Semanal como base).

Esfuerzo: medio. Beneficio: convierte horas de armado de programa en minutos.

## Propuesta 4 — Asistente IA conversacional sobre el CMMS

Chat dentro del CMMS ("¿que OTs vencen esta semana en Molino?", "redactame el
aviso para la fuga del reductor") conectado a la API de Claude, con acceso de
solo lectura a la BD. Puede redactar avisos, resumir historiales de equipo y
priorizar backlog.

Esfuerzo: medio-alto. Requiere API key y control de costos (ya hay telemetria
de uso de IA en el proyecto). Beneficio: asistente real de redaccion y consulta.

## Propuesta 5 — App/modulo de rondas con checklist movil (PWA)

El CMMS ya es PWA instalable. Un modulo de "rondas del planificador" con
checklists moviles (verificacion de trabajos terminados, seguridad, 5S) que
al marcar hallazgos cree avisos automaticamente.

Esfuerzo: medio. Beneficio: la caminata de planta queda registrada y genera
trabajo automaticamente.

## Recomendacion

Empezar por **1 + 2** (una semana de trabajo aprox., beneficio inmediato),
luego **3**, y evaluar **4** cuando haya presupuesto para IA.
