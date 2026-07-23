# Indicadores del CMMS — Documentación de fórmulas

Documento de referencia de cómo se calculan los indicadores que se muestran
en el dashboard, en el módulo de Reportes (Reporte Ejecutivo) y en el módulo
de Indicadores (drill-down por Área → Línea → Equipo).

> **Fuente del código**: cualquier discrepancia entre este documento y el código
> debe resolverse leyendo los archivos referenciados — el código es la fuente
> de verdad.

---

## Tabla resumen

| Indicador | Fórmula | Unidad | Donde vive |
|---|---|---|---|
| MTBF | `uptime / n_fallas` | horas | [routes/indicators_routes.py](routes/indicators_routes.py) (`_calc_indicators`) |
| MTTR | `downtime_total / n_fallas` | horas | [routes/indicators_routes.py](routes/indicators_routes.py) (`_calc_indicators`) |
| Disp. Operativa | `(T − Pp − Pn) / T × 100` | % | [routes/indicators_routes.py](routes/indicators_routes.py) (`_calc_indicators`) |
| Disp. Inherente | `(T − Pp − Pn) / (T − Pp) × 100` | % | [routes/indicators_routes.py](routes/indicators_routes.py) (`_calc_indicators`) |
| Confiabilidad R(t) | `e^(−t/MTBF) × 100` | % | [routes/indicators_routes.py:55-58](routes/indicators_routes.py#L55-L58) |
| Disp. ponderada (área) | `Σ(disp_eq × cap_eq) / Σ(cap_eq)` | % | [routes/indicators_routes.py:159-177](routes/indicators_routes.py#L159-L177) |
| Disp. en serie (área) | `∏(disp_eq_i)` | % | [routes/indicators_routes.py:139-153](routes/indicators_routes.py#L139-L153) |
| Cumplimiento | `OTs cerradas / OTs programadas × 100` | % | [routes/reports_routes.py:392](routes/reports_routes.py#L392) |
| Horas de paro | `Σ downtime_hours (OTs con caused_downtime=True)` | horas | [routes/indicators_routes.py:28-49](routes/indicators_routes.py#L28-L49) |
| Costo de OTs | `Σ (qty × costo_unitario_warehouse) por OT` | S/. | [routes/reports_routes.py:367-372](routes/reports_routes.py#L367-L372) |
| Capacidad nominal | `Equipment.capacity_tm` o fallback legacy | TM/mes | [utils/kpi_helpers.py:22-29](utils/kpi_helpers.py#L22-L29) |
| Yield factor | `Equipment.yield_factor` | 0..1 | [utils/kpi_helpers.py:32-34](utils/kpi_helpers.py#L32-L34) |
| Producción teórica | `cap × yield × (horas_op / horas_calendario)` | TM | [utils/kpi_helpers.py:44-61](utils/kpi_helpers.py#L44-L61) |

---

## 1. MTBF — Mean Time Between Failures

**Definición**: tiempo promedio entre fallas que detuvieron al equipo.

```
MTBF = uptime / n_fallas
uptime = total_horas - Σ downtime_hours
```

**Detalles**:
- Solo cuentan como falla las OTs con `caused_downtime = True` y
  `downtime_hours > 0`.
- Si una OT no marcó `downtime_hours` pero tiene `real_duration` y
  `caused_downtime = True`, se usa `real_duration` como fallback.
  Ver [routes/indicators_routes.py:28-45](routes/indicators_routes.py#L28-L45).
- Si no hay fallas en el periodo: `MTBF = total_horas` (sin denominador
  que dividir, asumimos perfecto uptime).
- `total_horas` se calcula como `días_periodo × 24`. La ventana de tiempo
  es `(end_date - start_date).days + 1`.

**Ejemplo**: en un periodo de 30 días = 720 h, con 3 fallas que sumaron
24 h de paro:
```
MTBF = (720 − 24) / 3 = 232 h
```

---

## 2. MTTR — Mean Time To Repair

**Definición**: tiempo promedio que toma reparar una falla.

```
MTTR = Σ downtime_hours / n_fallas
```

- Si no hay fallas: `MTTR = 0`.
- Es independiente del calendario — solo importa el promedio por falla.

**Ejemplo**: con 3 fallas que sumaron 24 h de paro:
```
MTTR = 24 / 3 = 8 h
```

---

## 3. Disponibilidad

**Definición**: porcentaje del tiempo que el equipo estuvo operativo.

Todo el downtime registrado se clasifica en **paro planificado (Pp)** o
**paro no planificado / avería (Pn)** y con eso se calculan SIEMPRE las dos
disponibilidades (`T` = horas del periodo = días × 24):

```
Disponibilidad OPERATIVA  = (T − Pp − Pn) / T        × 100
Disponibilidad INHERENTE  = (T − Pp − Pn) / (T − Pp) × 100
```

- **Operativa**: lo que producción realmente tuvo disponible. La castiga
  TODO paro (correctivos, preventivos con parada, paradas programadas).
- **Inherente** (ISO 14224): salud del activo. Solo la castigan las
  averías; el tiempo de mantenimiento planificado se excluye de la base
  de tiempo. Siempre se cumple `inherente ≥ operativa`, y la brecha entre
  ambas es el costo del mantenimiento planificado.

**Clasificación del paro** (`WorkOrder.downtime_planned`):
1. Si la OT tiene el campo explícito `downtime_planned` (se marca en el
   modal de cierre como "Tipo de paro") → manda ese valor.
2. Si es NULL y la OT está vinculada a una parada (`shutdown_id`) → manda
   `Shutdown.is_planned` de la parada consolidada.
3. Si es NULL y no hay parada → se deriva del tipo de mantenimiento:
   correctivo = avería; preventivo/predictivo/mejora = planificado.

> **Regla de registro**: las horas de paro se registran SIEMPRE que el
> equipo dejó de producir, aunque el trabajo haya sido programado. Que un
> paro sea planificado no lo hace invisible — lo hace clasificable. Un
> correctivo programado se registra con sus horas y tipo de paro
> "Planificado": baja la operativa pero no la inherente.

- En el módulo de Indicadores se calcula a tres niveles:
  1. **Equipo**: fórmula directa de arriba.
  2. **Línea/Área (ponderada por capacidad)** — default:
     ```
     Disp_area = Σ (Disp_eq_i × cap_eq_i) / Σ cap_eq_i
     ```
     Pondera por `Equipment.capacity_tm` (TM/mes). Equipos con `capacity_tm = 0`
     no aportan al cálculo.
  3. **Área en SERIE**:
     ```
     Disp_area = Disp_eq_1 × Disp_eq_2 × ... × Disp_eq_n
     ```
     Se aplica solo a las áreas listadas en `SERIES_AREAS` de
     [utils/kpi_helpers.py:19](utils/kpi_helpers.py#L19) (hoy: `MOLINO`).
     Refleja procesos en serie donde si un equipo cae, toda la línea cae.

**Filtro de KPI**: solo aportan al promedio las áreas y equipos con
`include_in_kpi = True`. Eso excluye "BAJA / FUERA DE SERVICIO",
"UTILITIES", "RMP" y equipos auxiliares no productivos
([routes/indicators_routes.py:81-86](routes/indicators_routes.py#L81-L86)).

---

## 4. Confiabilidad R(t)

**Definición**: probabilidad de que el equipo opere sin fallar durante un
periodo `t`, asumiendo distribución exponencial de fallas.

```
R(t) = e^(−t/MTBF) × 100
```

- `t` = `total_horas` del periodo analizado.
- Si `MTBF = 0` y hubo fallas → `R(t) = 0`.
- Si no hubo fallas → `R(t) = 100%`.

**Ejemplo**: MTBF = 232 h, periodo = 720 h:
```
R(720) = e^(−720/232) × 100 = e^(−3.10) × 100 ≈ 4.5%
```
> Que la confiabilidad caiga rápido al evaluar periodos largos es
> comportamiento esperado del modelo exponencial.

---

## 5. Cumplimiento del programa

**Definición**: porcentaje de OTs programadas que se cerraron a tiempo.

```
Cumplimiento = (OTs_cerradas / OTs_programadas) × 100
```

- `OTs_programadas` = OTs con `scheduled_date` dentro de la ventana.
- `OTs_cerradas` = OTs programadas con `status = 'Cerrada'`.
- Si `OTs_programadas = 0` → cumplimiento por defecto **100%** (no hay
  nada que medir, no penalizar).

Ver [routes/reports_routes.py:392](routes/reports_routes.py#L392) (reporte
ejecutivo) y [routes/reports_routes.py:808](routes/reports_routes.py#L808)
(plan semanal).

---

## 6. Horas de paro y Pareto de indisponibilidad

**Horas de paro**: suma de `downtime_hours` de OTs cerradas con
`caused_downtime = True` en el periodo.

**Pareto de indisponibilidad**: agrupa esas horas por `failure_mode`
(modo de falla declarado en el aviso/OT) y las ordena descendente.
Modos sin clasificación se etiquetan como **"Sin clasificar"**.

---

## 7. Costo de OTs

```
Costo_OT = Σ (cantidad_material × costo_unitario_warehouse)
```

- Solo cuentan materiales con `item_type = 'warehouse'` (vinculados a un
  ítem de almacén con costo registrado).
- Materiales tipo "compra directa" sin vínculo a almacén no se contabilizan
  aquí (entran por el módulo de Compras).
- Hoy `Valor Total = $0.00` en almacén porque la mayoría de ítems no
  tienen `unit_cost` poblado.

Ver [routes/reports_routes.py:367-372](routes/reports_routes.py#L367-L372).

---

## 8. Producción y rendimiento

### Capacidad nominal

```
cap = Equipment.capacity_tm  (TM/mes)
```

Si es NULL, fallback al diccionario legacy
[utils/kpi_helpers.py:13-16](utils/kpi_helpers.py#L13-L16):

```python
EQUIPMENT_CAPACITY = {
    'D1': 8000, 'D2': 8000, 'D3': 8000, 'D4': 6000, 'D5': 7000,
    'D6': 12000, 'D7': 12000, 'D8': 12000, 'D9': 12000,
}
```

### Horas de calendario por equipo

```
horas_op = días_laborables_periodo × shift_hours_per_day
```

Donde:
- `shift_hours_per_day` = jornada del equipo (default 24 h).
- `work_days_per_week` = días laborables/semana (default 7).
  Si es < 7, asume descanso empezando por domingo, luego sábado, etc.

Ver [utils/kpi_helpers.py:44-61](utils/kpi_helpers.py#L44-L61).

### Yield factor

```
yield = Equipment.yield_factor  (0..1, default 1.0)
```

Representa el rendimiento materia prima → producto final. Por ejemplo,
`yield = 0.21` significa que de cada TM de materia prima procesada salen
0.21 TM de producto.

### Paradas planificadas

`planned_downtime_for_equipment` (en [utils/kpi_helpers.py:64-90](utils/kpi_helpers.py#L64-L90))
suma horas de paradas (`Shutdown`) en estado `COMPLETADA | EN_CURSO |
PLANIFICADA` que afecten al área del equipo. Para paradas `PARCIAL` se
valida que el área esté incluida en `ShutdownArea`.

---

## 9. Disponibilidad de espesores (UT)

Distinto a la disponibilidad operativa. En el módulo de Espesores cada
**punto** tiene tres umbrales:

| Estado | Condición |
|---|---|
| **NORMAL** | `valor > alarm_thickness` |
| **ALERTA** | `scrap < valor ≤ alarm` |
| **CRITICO** | `valor ≤ scrap` |

El **semáforo del equipo** se calcula como:
- `ROJO` si hay ≥1 punto crítico
- `AMARILLO` si hay ≥1 punto en alerta (pero ninguno crítico)
- `VERDE` si todos los puntos están normales

Ver [routes/thickness_routes.py:21-29](routes/thickness_routes.py#L21-L29).

### Análisis predictivo de vida residual

Por punto medido al menos 2 veces:

```
pendiente b = (n·Σxy − Σx·Σy) / (n·Σx² − (Σx)²)
desgaste mensual = |b| × 30.44 mm/mes
vida residual = (último_valor − scrap) / desgaste_mensual
```

Niveles de urgencia ([routes/thickness_routes.py:482-491](routes/thickness_routes.py#L482-L491)):
- **CRITICO**: vida ≤ 1 mes → REEMPLAZO INMEDIATO
- **URGENTE**: vida ≤ 3 meses → fabricar AHORA
- **PLANIFICAR**: vida ≤ 6 meses → programar fabricación

---

## 10. Cumplimiento de Plan Semanal / Programa Nocturno

```
Cumplimiento_plan = (items_EJECUTADO / total_items) × 100
```

Estados posibles de `WeeklyPlanItem.status`:
- `PLANIFICADO` (default)
- `EJECUTADO` → genera OT automática y actualiza `next_due_date` del
  origen (lub/insp/mon).
- `OMITIDO` → no cuenta en cumplimiento, requiere justificación.

**Disciplina por ítem** ([utils/specialty_helpers.py:90-110](utils/specialty_helpers.py#L90-L110)):
1. Si la OT vinculada tiene personal asignado → usa la especialidad del personal.
2. Si `source_type = 'lubrication'` → MECANICO.
3. Sino, infiere por palabras clave en `description` / `source_name` /
   `equipment_tag`.

---

## 11. Definiciones de campos clave

| Campo | Significado |
|---|---|
| `caused_downtime` | OT que detuvo el equipo (true/false). Solo estos suman al MTBF/MTTR/Disponibilidad. |
| `downtime_hours` | Horas que el equipo estuvo detenido por esta OT. Si NULL pero caused_downtime=true, usa `real_duration`. |
| `downtime_planned` | Tipo de paro: true = planificado (solo baja la Disp. Operativa), false = avería (baja ambas). NULL = se deriva del tipo de mantenimiento / parada vinculada. |
| `scheduled_date` | Fecha planificada (define la ventana del cumplimiento). |
| `real_start_date` / `real_end_date` | Cuándo se ejecutó realmente. |
| `real_duration` | Horas-hombre reales (no necesariamente downtime). |
| `Equipment.include_in_kpi` | Si false, el equipo NO aporta al MTBF/MTTR/Disp. del área. |
| `Area.include_in_kpi` | Si false, el área no aparece en el dashboard de indicadores. |
| `Equipment.capacity_tm` | Capacidad nominal mensual en toneladas métricas. |
| `Equipment.yield_factor` | Rendimiento MP → producto (0..1). |
| `SERIES_AREAS` | Set de áreas cuya disponibilidad se calcula multiplicando equipos en serie. |

---

## 12. Cómo verificar manualmente un cálculo

1. **Pega la ventana de fechas** (ej. `2026-04-01 a 2026-04-30`).
2. **Filtra OTs cerradas** con `scheduled_date` o `real_end_date` en la
   ventana.
3. **Identifica fallas**: OTs con `caused_downtime = true` y
   `downtime_hours > 0`.
4. **Suma**: `downtime_total = Σ downtime_hours`.
5. **Calcula** (separando `Pp` = paro planificado, `Pn` = averías):
   - `total_horas (T) = días × 24` (a nivel equipo, sin filtros de jornada)
   - `uptime = T − Pp − Pn`
   - `MTBF = uptime / n_fallas`
   - `Disp Operativa = uptime / T × 100`
   - `Disp Inherente = uptime / (T − Pp) × 100`
6. **Compara** contra el dashboard. Si difieren > 1%, revisa que estés
   excluyendo OTs sin `caused_downtime` y respetando el filtro
   `include_in_kpi`.

---

## 13. Archivos relevantes

- **Cálculo central**: [routes/indicators_routes.py](routes/indicators_routes.py)
  (`_calc_indicators`, `indicators_by_area`, `indicators_by_equipment`).
- **Reporte ejecutivo**: [routes/reports_routes.py](routes/reports_routes.py)
  (`get_executive_reports`, `breakdown` por nivel area/línea/equipo).
- **Helpers compartidos**: [utils/kpi_helpers.py](utils/kpi_helpers.py)
  (capacidad, jornada, calendar hours, paradas planificadas).
- **Producción vs mantenimiento**: [routes/production_routes.py](routes/production_routes.py).
- **Espesores**: [routes/thickness_routes.py](routes/thickness_routes.py)
  (semáforo, análisis predictivo, vida residual).
- **Plan semanal**: [routes/reports_routes.py](routes/reports_routes.py)
  (`_collect_weekly_plan_payload`, `export_weekly_plan_excel`).
- **Disciplina mecánico/eléctrico**: [utils/specialty_helpers.py](utils/specialty_helpers.py).
