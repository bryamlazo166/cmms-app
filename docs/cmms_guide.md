# Guía Maestra del CMMS — Conocimiento Operativo

> Este documento se inyecta automáticamente al contexto del bot de Telegram
> (`bot/telegram_bot.py`) para que cualquier consulta o acción se ejecute con
> el contexto correcto del negocio. **Editá libremente este archivo cuando
> cambien procesos o vocabulario**; el bot lo lee en cada conversación.

---

## 1. Contexto del negocio

- **Tipo de planta:** procesamiento industrial con líneas de digestores,
  percoladores, tornillos helicoidales (TH), molinos y secadores.
- **Zona horaria operativa:** **America/Lima (UTC-5)**. Todas las fechas/horas
  que registra y muestra el sistema están en Lima. Cuando un usuario diga
  "hoy", "anoche", "ayer", siempre interprétalo en hora Lima.
- **Operación 24/7** con turnos. Mantenimiento subcontratado y mantenimiento
  interno conviven.

## 2. Vocabulario y sinónimos (CRÍTICO para el bot)

| Si el usuario dice... | El sistema lo llama... |
|---|---|
| rodamiento, cojinete | **chumacera** (siempre) |
| molino 1, molino #1, mole 1 | **Molino #1 / M1** |
| molino 2, molino #2 | **Molino #2 / M2** |
| reductor, caja reductora | reductor |
| motor, motor eléctrico | motor electrico |
| cadena, transmisión por cadena | cadena |
| TH N, tornillo helicoidal N | **TH<N>** (ej. TH3) |
| D N, digestor N | **D<N>** (ej. D8) |
| H N, hidrolavadora N | **H<N>** (ej. H2) |
| MOLI1-LINE, MOLI2-LINE | molino 1/2 de la línea principal |

Los puntos de **lubricación** se llaman SIEMPRE "chumacera motriz" / "chumacera
conducida" (no rodamiento). El rodamiento vive dentro de la chumacera; el punto
de lubricación se nombra por la chumacera.

## 3. Códigos y nomenclatura

| Entidad | Formato | Ejemplo |
|---|---|---|
| Orden de Trabajo | `OT-NNNN` | OT-0123 |
| Aviso | `AV-NNNN` | AV-0045 |
| Parada planeada | `PP-YYYY-MM-NNN` | PP-2026-05-001 |
| Ruta de inspección | `INS-XXX` | INS-TH3 |
| Punto de lubricación | `LUB-XXX` | LUB-D9-CHM-CON |
| Lote de martillos | `LOTE-X` | LOTE-A, LOTE-B, LOTE-C |

## 4. Estados y flujos

### Órdenes de Trabajo
`Abierta → Programada → En Progreso → Cerrada` (o `No Ejecutada`).
Una OT se crea desde un Aviso o como standalone (preventivo planificado).

### Avisos
`Pendiente → En Tratamiento → Cerrado` (o `Anulado`).
- **Scope PLAN:** vinculado a equipo del árbol jerárquico.
- **Scope FUERA_PLAN:** equipo no inventariado todavía (`free_location` describe).
- **Scope GENERAL:** servicio general no atribuible a equipo concreto.

### Paradas
`is_planned=true` = parada planificada (PP). `is_planned=false` = avería.
Distinción clave para los KPIs ISO 14224.

## 5. KPIs y ISO 14224

El sistema calcula **Disponibilidad** bajo dos criterios (toggle en UI):

- **Operativa:** considera todas las paradas (planeadas + averías + externas).
  Útil para ver qué porcentaje real del tiempo la planta produjo.
- **Inherente:** solo paradas atribuibles al equipo (averías intrínsecas).
  Útil para evaluar la confiabilidad del activo en sí, sin ruido externo.

Otros KPIs estándar: MTBF, MTTR, % preventivo vs correctivo (calculado solo
sobre alcance PLAN).

## 6. Proveedor FAPMETAL — Cambio de martillos (proceso clave)

**Contexto:** FAPMETAL es el proveedor encargado de rellenar martillos con
soldadura de recarga. Realiza cambios nocturnos durante turno noche siempre
que haya producción activa.

**Modelo operativo:** 3 lotes físicos en circulación:
- 2 lotes **instalados** (uno en Molino #1, uno en Molino #2).
- 1 lote **en tránsito** (en FAPMETAL siendo rellenado, o ya rellenado en
  stock esperando próximo cambio).

**Cada lote:** 72 martillos. Total en circulación: 216 martillos.

**Ciclo típico:** Día N se cambia M1 (lote actual sale a FAPMETAL, lote del
stock entra). Día N+1 se cambia M2 (mismo flujo). Y así sucesivamente.
**Duración estimada por cambio:** ~1 hora.

**Servicios incluidos en cada cambio:**
1. Retiro del lote instalado en el molino.
2. Instalación del lote rellenado del stock.
3. Lubricación de chumacera motriz.
4. Lubricación de chumacera conducida.

**Auditoría trimestral:** FAPMETAL envía informe cada 3 meses con la cantidad
de martillos rellenados. El sistema concilia en `/martillos` → "Conciliación".
Si las cifras de FAPMETAL no coinciden con lo registrado en el sistema, hay
sospecha de cobro inflado.

**Fin de vida del lote:** cuando los martillos están muy desgastados (típico
8-12 rellenados), se compra un lote nuevo y se descarta el viejo.

**Módulo en el sistema:** `/martillos`. Endpoints: `/api/hammer-batches/*`.

## 7. Lubricación

- Vocabulario: "chumacera motriz" / "chumacera conducida" / "cadena" / "reductor".
- El bot SIEMPRE usa "chumacera" cuando el usuario dice rodamiento o cojinete.
- Frecuencia por punto definida en `lubrication_points.frequency_days`.
- Quien lubrica: **MANTENIMIENTO** (interno), **FAPMETAL** (externo), o
  nombre de técnico (ej. **Marcos Campos**).
- Cada ejecución puede reportar fugas o anomalías; si las hay, el sistema crea
  automáticamente un aviso vinculado.

## 8. Inspecciones

- Las rutas tienen frecuencia (ej. semanal, quincenal, mensual).
- Resultado: `OK` o `CON_HALLAZGOS`.
- Si `findings_count > 0`, el sistema crea automáticamente un aviso vinculado
  para cada hallazgo agregado o un aviso resumen.

## 9. Roles y permisos

| Rol | Alcance típico |
|---|---|
| `admin` | Todo (configura permisos, roles, datos maestros) |
| `jefe_mtto` | Toda la operación de mantenimiento, indicadores |
| `planner` | OTs, avisos, programación, plan semanal |
| `supervisor` | Ejecución diaria, paradas |
| `tecnico` | Carga ejecución de OTs y lubricaciones |
| `operador` | Solo crea avisos |
| `almacenero` | Almacén, herramientas, compras |
| `gerencia` | Solo lectura de KPIs y reportes |

## 10. Convenciones para el bot al ejecutar acciones

- **Fechas relativas:** "hoy" = `today_lima()`, "ayer" = un día antes,
  "anteayer" = dos días antes, "el viernes pasado" = el viernes inmediato
  anterior. SIEMPRE en hora Lima.
- **Voz nocturna:** si el usuario dice "anoche" entre 00:00 y 12:00, se
  refiere al turno noche del día anterior (no a "hace 2h").
- **Componentes con sinónimos:** aplica el vocabulario de la sección 2 ANTES
  de buscar en el árbol.
- **Cuando el sistema infiere lotes/puntos automáticamente** (ej. cambio de
  martillos sin especificar lote), no preguntes ni dudes — el sistema solo
  infiere si hay un candidato único. Si hay ambigüedad, devolverá error
  explicando qué falta.
- **Confirmaciones críticas:** las acciones destructivas
  (`delete_lubrication`, `replicate_specs` mode=replace) NUNCA se ejecutan
  sin que el usuario haya dicho expresamente "borra", "reemplaza", "sobreescribe".

## 11. Módulos y dónde encontrarlos

| Módulo | URL | API |
|---|---|---|
| Dashboard | `/` | — |
| Avisos | `/avisos` | `/api/notices` |
| Órdenes de Trabajo | `/ordenes` | `/api/work-orders` |
| Paradas | `/paradas` | `/api/shutdowns` |
| Lubricación | `/lubricacion` | `/api/lubrication` |
| Inspecciones | `/inspecciones` | `/api/inspection` |
| Monitoreo | `/monitoreo` | `/api/monitoring` |
| Espesores | `/espesores` | `/api/thickness` |
| Activos rotativos | `/activos-rotativos` | `/api/rotative-assets` |
| Martillos (FAPMETAL) | `/martillos` | `/api/hammer-batches` |
| Almacén | `/almacen` | `/api/warehouse` |
| Compras | `/compras` | `/api/purchase` |
| Indicadores | `/indicadores` | `/api/indicators` |
| Plan semanal | `/programa-nocturno` | `/api/weekly-plans` |
| Cockpit | `/cockpit` | — |

## 12. Casos especiales / "gotchas" (importante para el bot)

- **TH3 ≠ TH alimentador del secador 2.** El usuario puede decir "TH2A" y
  referirse al "tornillo helicoidal alimentador del secador 2" cuyo tag real
  es `TH2A-SECA`. Siempre verifica el tag en la lista EQUIPOS del contexto.
- **Hidrolavadora 2 = H2.** No confundir con H22 o similares.
- **Digestor 5 ≠ Digestor 8.** Si el usuario dice un número, NUNCA aproximes
  al "más parecido". Si no encuentras el equipo exacto, devolver
  `action:"none"` con `reply` pidiendo confirmación.
- **Si FAPMETAL "infla" cifras en su informe trimestral**, el módulo
  `/martillos` → "Conciliación FAPMETAL" muestra la discrepancia con cifras
  de sistema. Usá ese reporte para validar.

## 13. TODO (cosas que el usuario aún debe documentar acá)

- [ ] Listado completo de equipos críticos con sus tags reales.
- [ ] Tabla de relación equipo → proveedor responsable de mantenimiento.
- [ ] Frecuencias estándar de lubricación por tipo de chumacera.
- [ ] Umbral de descarte de martillos (cantidad de rellenados).
- [ ] Política de stock mínimo de repuestos críticos.
- [ ] Plan anual de paradas mayores.
