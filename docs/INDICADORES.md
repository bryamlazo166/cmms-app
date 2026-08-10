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
| MTBF / Confiab. (área) | ponderados por capacidad, igual que la disponibilidad | h / % | [routes/indicators_routes.py](routes/indicators_routes.py) |
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
  3. **Decidido con la jefatura de mantenimiento (ago-2026)**: la
     disponibilidad de un área es SIEMPRE la ponderada por capacidad. Se
     eliminó el cálculo en serie que se aplicaba solo a `MOLINO`: multiplicar
     la disponibilidad de sus 13 equipos daba 87 % con trece equipos al 99 %,
     aunque la línea nunca se hubiera detenido.
     El MTBF y la confiabilidad del área se ponderan igual — medirlos sobre el
     conjunto de OTs del área hacía que un área con muchos equipos pareciera
     siempre peor (COCCIÓN daba 17 h de MTBF por tener 20 equipos, cuando cada
     digestor por separado supera las 500 h). El MTTR sí es del área completa:
     es el promedio de lo que cuesta reparar una avería.

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

- `t` = **168 h (una semana)** en toda la aplicación, definido en
  `RELIABILITY_HOURS`. Antes cada pantalla usaba un `t` distinto (el periodo
  completo en Indicadores, 168 h en el Diagnóstico) y los números no eran
  comparables entre sí.
- Si `MTBF = 0` y hubo fallas → `R(t) = 0`.
- **Si no hubo fallas → `R(t) = 100%`.** Antes se igualaba el MTBF a las horas
  del periodo y la fórmula devolvía siempre `e⁻¹ = 36,79 %`: un equipo que
  nunca paró aparecía como poco confiable.

**Ejemplo**: MTBF = 600 h, horizonte de una semana:
```
R(168) = e^(−168/600) × 100 = e^(−0.28) × 100 ≈ 75.6%
```
> Se lee: «este equipo tiene 76 % de probabilidad de aguantar una semana
> completa sin fallar». Con horizontes largos el resultado tiende a cero, que
> es comportamiento esperado del modelo exponencial pero no informa nada.

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
| `Equipment.batch_capacity_kg` | Kilos de una llenada. Solo equipos por lotes (digestores). |
| `Equipment.fill_pct` | Hasta qué % se llena realmente (planta: 75%). |
| `Equipment.batches_per_day` | Llenadas en 24 h (planta: 4, ciclo de 6 h). |
| `Equipment.capacity_tm_day` | Capacidad diaria. En digestores se deriva de los campos de lote (materia prima); en secadores y molinos se captura en TM de harina. |
| `Equipment.is_production_unit` | Si True, la parada del equipo cuesta toneladas. Los equipos por lotes lo son siempre. |
| `Equipment.capacity_tm` | LEGACY: capacidad mensual. Hoy se deriva de `capacity_tm_day`. |
| `Equipment.yield_factor` | Rendimiento MP → producto (0..1). |
| `Equipment.in_service` | Si false (overhaul, parada larga) el equipo NO suma capacidad de planta. |
| `RELIABILITY_HOURS` | Horizonte de la confiabilidad: 168 h (una semana) para toda la aplicación. |

---

## 11 bis. Capacidad de planta y toneladas no producidas

Se configura en **Alcance de Indicadores** (`/configuracion-kpi`).

El proceso tiene **tres etapas en serie**, y cada una mide su capacidad en la
unidad que le corresponde:

| Etapa | Equipos | Qué hace | Capacidad medida en |
|---|---|---|---|
| Cocción | 9 digestores | **Genera** la harina | TM de materia prima (`MP`) |
| Secado | 2 secadores | La seca | TM de harina (`PRODUCTO`) |
| Molienda | 2 molinos | La muele | TM de harina (`PRODUCTO`) |

```
Digestor:  TM/día MP  = kg por llenada × % de llenado × llenadas por día ÷ 1000
           TM/día de harina = TM/día MP × rendimiento
Secador / molino:
           TM/día de harina = capacity_tm_day  (ya está en harina: procesan lo
                              que salió de cocción, NO se les vuelve a aplicar
                              el rendimiento)

Capacidad de cada etapa = Σ de sus equipos EN SERVICIO
Capacidad de planta     = la etapa MÁS LIMITADA (van en serie)
TM no producidas        = horas de parada × TM/h de harina del equipo detenido
```

Ejemplo real: digestor #1 = 8 000 kg × 75 % × 4 llenadas = **24 TM/día de
materia prima**; con 50 % de rendimiento son 12 TM/día de harina.

Que la planta sea la etapa más corta importa: si el molino #1 se desactiva y
solo trabaja el #2, la molienda queda a la mitad y la planta con ella, aunque
cocción y secado sigan completos.

Cinco reglas que sostienen el número:

1. **Solo restan toneladas los equipos donde se transforma el producto**
   (`is_production_unit`): los digestores, los 2 secadores y los 2 molinos.
   Los transportadores, ciclones, percoladores, fajas y vahos son auxiliares:
   si paran no se deja de producir harina por sí mismos, y contarlos valoraba
   varias veces el mismo flujo. Sus paradas siguen en los indicadores de
   mantenimiento y se informan aparte en la lámina de producción.
2. **Generar no es procesar.** El rendimiento se aplica una sola vez, en
   cocción. A un secador o un molino no se le vuelve a aplicar: su capacidad
   ya está expresada en harina (`eq_capacity_basis`).
3. **Cada equipo aporta su propia capacidad.** Si para un digestor de nueve se
   pierde lo de ese digestor, no el rendimiento de toda la planta. Valorar la
   parada de un equipo con la cifra del área era lo que hacía que un mes
   reportara más toneladas perdidas de las que la planta produce.
4. **Las paradas que cruzan meses se reparten** entre los días que cubren, en
   vez de cargarse enteras al mes en que se cerró la OT.
5. **Techo físico**: la pérdida de un periodo nunca supera la capacidad
   instalada de esos días.

La **disponibilidad de planta** del diagnóstico usa la misma cuenta:
`1 − (TM no procesadas ÷ TM que se podían procesar)`. Es ponderada por
capacidad porque los digestores trabajan en paralelo; restar la suma bruta de
sus horas de parada, como si estuvieran en serie, daba disponibilidades de 0 %
con la planta operando.

**La capacidad no se carga a mano.** `ProductionGoal.monthly_avg_yield_tons` y
`operating_hours_month` quedan solo como respaldo para áreas sin ningún equipo
con capacidad configurada. Mientras el área tenga equipos productivos en
servicio, *Producción vs Mantenimiento* usa `tons_per_hour = capacidad del área
÷ 24` y horas de calendario del periodo — la misma cuenta que la presentación de
indicadores. Con la cifra manual las tres áreas pedían **98,8 %** de
disponibilidad (compartían el mismo rendimiento cargado a mano) mientras la
presentación pedía 86,5 / 84,9 / 70,8 %: dos pantallas con dos respuestas para
el mismo mes. La disponibilidad que muestra *Producción* es la **operativa** (la
castiga todo paro, que es lo que producción realmente tuvo); la presentación
muestra la **inherente**. Ambas se calculan siempre y una prueba verifica que
coinciden.

Los equipos sin capacidad configurada no suman toneladas: el diagnóstico avisa
cuántas OTs y horas quedaron fuera, y el botón *Completar capacidades vacías*
las rellena heredando la capacidad de la línea o repartiendo la planta entre
equipos gemelos.

---

## 11 ter. Indicadores de Mantenimiento (presentación semanal y mensual)

Módulo `/indicadores-mensuales`. Corre **en paralelo** al Diagnóstico Mensual
y su regla es no hablar de toneladas: el único dato de producción que entra es
la meta, y solo para despejar cuánta disponibilidad hace falta.

### Periodización

El informe se presenta al cierre de cada semana y al cierre del mes, así que
hay dos ejes:

| Vista | Eje X | Para qué |
|---|---|---|
| **Semanal** | S1 … Sn del mes elegido, truncado a la semana que se presenta | Al cerrar la semana 2 se ven S1 y S2; al cerrar la 3, S1–S3 |
| **Mensual** | El mes cerrado contra los N meses anteriores | El cierre de mes |

Las semanas son **bloques de 7 días contados desde el día 1**, no semanas ISO.
Una semana ISO se reparte entre dos meses y entonces las semanas dejarían de
sumar el mes; con bloques desde el día 1 la partición es exacta y verificable:
`Σ fallas de las semanas = fallas del mes` y lo mismo con las horas de paro.
Si el último bloque queda con menos de 3 días se absorbe en el anterior, para
no presentar una «semana» de un día.

- Julio (31 días) → S1 1–7 · S2 8–14 · S3 15–21 · S4 22–28 · S5 29–31
- Junio (30 días) → S1 1–7 · S2 8–14 · S3 15–21 · **S4 22–30**
- Febrero (28 días) → cuatro semanas exactas

En la vista semanal cada barra es el resultado de **esa semana sola** y la
línea naranja es el **acumulado del mes** (del día 1 al cierre de esa semana),
que es lo que responde «¿cómo va el mes?». El acumulado de la última semana
es, por construcción, el indicador mensual.

Una OT se asigna a un periodo por su **fecha de cierre real**
(`real_end_date` → `real_start_date` → `scheduled_date`), la misma regla que
usa la vista mensual. Por eso las semanas cuadran con el mes sin prorrateo.

### Agregación

Todo se calcula **equipo por equipo** con `_calc_indicators` y se **pondera por
capacidad** al subir a línea, área y planta — disponibilidad, MTBF y
confiabilidad. El MTTR no se pondera: es `horas de paro ÷ averías`, el tiempo
medio de reparación. El indicador **PLANTA** es la ponderación de todos los
equipos de las áreas de proceso (cocción, secado, molienda).

### Disponibilidad requerida

```
disponibilidad requerida = meta del periodo ÷ capacidad del periodo
presupuesto de parada    = (1 − requerida) × horas del periodo
consumido                = (1 − disponibilidad real) × horas del periodo
```

En vista semanal la meta mensual se **prorratea por días**. El porcentaje
requerido no cambia (meta y capacidad escalan juntas); lo que cambia, y es lo
útil, es el presupuesto: en una semana son 168 h de margen, no 744.

El *consumido* son horas **equivalentes de área**, no la suma bruta de
horas-equipo: los 9 digestores trabajan en paralelo y esa suma supera las horas
del mes, con lo que el saldo salía negativo aunque el área cumpliera la meta.

Si una etapa necesita más de 100 %, la lámina lo dice explícitamente: la meta
está por encima de la capacidad instalada y es una conversación sobre la meta o
sobre ampliar capacidad, no sobre mantenimiento.

### Cumplimiento del programa preventivo

El programa preventivo **no son solo las OTs**. La lubricación, las rutas de
inspección y el monitoreo de condición son mantenimiento preventivo y viven en
sus propias tablas (`lubrication_points` / `lubrication_executions`, etc.), con
su frecuencia y sus ejecuciones, sin pasar nunca por `WorkOrder`. Contando solo
órdenes, julio 2026 mostraba 33 actividades preventivas al 100 % cuando en
realidad se habían hecho 396 lubricaciones: el indicador declaraba cumplimiento
perfecto sobre el 8 % del trabajo.

| Fuente | Programado | Ejecutado |
|---|---|---|
| OT preventiva / predictiva | OTs con `scheduled_date` en el periodo | las que además están `Cerrada` |
| Lubricación | `Σ días del periodo ÷ frequency_days` de cada punto activo | `LubricationExecution` en el periodo |
| Rutas de inspección | igual, sobre `inspection_routes` | `InspectionExecution` en el periodo |
| Monitoreo de condición | igual, sobre `monitoring_points` | `MonitoringReading` en el periodo |

Para las rutinas, «programado» es el **plan teórico** que declara la frecuencia
configurada, no una lista de tareas emitidas: un punto de 15 días pide 2,07
servicios en un mes de 31 y 0,47 en una semana. Un punto sobre un equipo fuera
de servicio no exige servicio — si se contara, el programa se incumpliría por un
equipo que no opera.

Las fuentes **no se funden en un solo número**: la lubricación aplastaría a las
OTs y el cumplimiento dejaría de decir si los preventivos mecánicos se hicieron.
Se apilan por fuente, cada una con su porcentaje, más el total. El indicador
anterior (solo OTs) se conserva en `solo_ot` para no perder la serie histórica.

**Programas en vigor.** Que un programa esté cargado no significa que esté en
vigor: las rutas de inspección pueden tener sus 22 rutas creadas y alguna
ejecución de prueba mientras se implantan, y cobrarles el plan teórico hunde el
cumplimiento con trabajo que todavía no se le exige a nadie. No se resuelve con
una heurística sobre los datos — una ejecución suelta no distingue «programa en
marcha» de «prueba» — así que es una declaración explícita, guardada en
`AppSetting['preventivo_fuentes']` (por defecto `OT,LUB`) y editable desde la
propia lámina 05, donde queda a la vista de quien presencia la presentación. Las
fuentes fuera de vigor se listan igual, con su plan teórico, pero no entran al
indicador. Las OTs siempre entran.

El ajuste se lee **en cada petición**, sin cachear, para que al cambiarlo el
número se corrija de inmediato aunque responda otro worker de gunicorn.

### Detalle bajo demanda

En pantalla van solo los indicadores globales (planta y área). Al hacer click
en cualquier barra o punto se abre `/api/presentacion/detalle`, que devuelve
para ese área y ese rango: el resumen, los indicadores equipo por equipo y las
OTs cerradas con sus horas de paro clasificadas en planificado / avería. El
resumen del detalle es el mismo número que muestra el gráfico — hay una prueba
que lo verifica, para que el drill-down no contradiga a la lámina en plena
reunión.

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
- **Presentación semanal / mensual**: [routes/presentacion_routes.py](routes/presentacion_routes.py)
  (`_bloques_semana`, `_periodos`, `_ponderar`, `_cumplimiento`, `presentacion_detalle`).
- **Metodología en pantalla**: [routes/metodologia_routes.py](routes/metodologia_routes.py)
  — módulo `/metodologia-indicadores`, la versión viva de este documento: cada
  fórmula con su sustitución sobre los números reales del periodo y las OTs que
  la alimentan. Incluye las **tres etapas resueltas equipo por equipo** —
  digestores por llenadas con rendimiento, secadores y molinos por su capacidad
  ya expresada en harina — y cuál es el cuello de botella. Una prueba verifica
  que reconstruye el mismo número que muestra la presentación.
- **Espesores**: [routes/thickness_routes.py](routes/thickness_routes.py)
  (semáforo, análisis predictivo, vida residual).
- **Plan semanal**: [routes/reports_routes.py](routes/reports_routes.py)
  (`_collect_weekly_plan_payload`, `export_weekly_plan_excel`).
- **Disciplina mecánico/eléctrico**: [utils/specialty_helpers.py](utils/specialty_helpers.py).
