# CMMS Power BI — MANTENIMIENTO.pbip

Dashboard ejecutivo del CMMS conectado a Supabase Postgres. Modo **Import** sobre **DSN ODBC**.

---

## 1. Requisitos para abrir y refrescar

### 1.1 Power BI Desktop
- Versión recomendada: **2.130+ (CY24SU09+)**.
- Debe estar habilitada la opción `File → Options → Preview features → Power BI Project (.pbip) save option`.

### 1.2 DSN ODBC `CMMS_Supabase`
Todas las particiones M usan `Odbc.DataSource("dsn=CMMS_Supabase", ...)`. Sin este DSN el refresh falla.

**Crear el DSN (Windows):**
1. Instalar el driver **PostgreSQL Unicode (x64)** desde [psqlODBC](https://odbc.postgresql.org/).
2. `Win + R` → `odbcad32.exe` → pestaña **DSN de usuario** → **Agregar** → seleccionar `PostgreSQL Unicode(x64)`.
3. Rellenar:
   - **Data Source**: `CMMS_Supabase`
   - **Server**: `aws-0-us-west-2.pooler.supabase.com`
   - **Port**: `6543`
   - **Database**: `postgres`
   - **SSL Mode**: `require`
   - **Username**: `powerbi_reader.zxgksjwszqqvwoyfrekw`
   - **Password**: solicitar al administrador del proyecto.
4. Probar conexión → debe responder OK.

---

## 2. Estructura del proyecto

```
powerbi/
├── MANTENIMIENTO.pbip                  → archivo a abrir en PBI Desktop
├── MANTENIMIENTO.SemanticModel/        → modelo (TMDL)
│   └── definition/
│       ├── model.tmdl                  → metadata global + refs
│       ├── relationships.tmdl          → 30+ relaciones del star schema
│       ├── expressions.tmdl            → (vacío, particiones M inline)
│       ├── database.tmdl
│       └── tables/
│           ├── DimFecha.tmdl           → calendario 2024–2030
│           ├── DimAreas.tmdl, DimLineas.tmdl, DimEquipos.tmdl,
│           │   DimSistemas.tmdl, DimComponentes.tmdl, DimTecnicos.tmdl
│           ├── FactOTs.tmdl, FactAvisos.tmdl, FactInspecciones.tmdl,
│           │   FactLubricacion.tmdl, FactParadas.tmdl
│           ├── ot_personnel.tmdl, ot_materials.tmdl  → puentes (costos)
│           ├── thickness_readings.tmdl                → puente (espesores)
│           ├── shutdown_areas.tmdl                    → puente (paradas)
│           └── _Medidas.tmdl           → 60+ medidas DAX organizadas por carpeta
└── MANTENIMIENTO.Report/               → visuales (JSON)
    ├── definition/
    │   ├── report.json                 → usa theme Industrial_Dark
    │   └── pages/                      → 12 páginas
    └── StaticResources/
        └── SharedResources/
            └── BaseThemes/
                ├── CY26SU02.json       → base PBI
                └── Industrial_Dark.json → theme custom enterprise
```

---

## 3. Modelo de datos (star schema)

```
            DimAreas ──┐
                       ├── DimLineas ── DimEquipos ── DimSistemas ── DimComponentes
                       │                              │
                       │                              ▼
                       │                          DimTecnicos
                       │
        ┌──────────────┼──────────────┬──────────────┬────────────┐
        ▼              ▼              ▼              ▼            ▼
     FactOTs ─── FactAvisos ── FactLubricacion ── FactInspecciones ── FactParadas
        │                                              │
        ├── ot_personnel ──► DimTecnicos              thickness_readings
        └── ot_materials                              shutdown_areas
                                                          │
                                                       DimAreas
                                                          │
                                                       DimFecha (todas las Fact*.Fecha)
```

Fecha activa por defecto:
- `FactOTs.[Fecha Programada]` (las otras fechas son inactivas — usar `USERELATIONSHIP` en DAX si quieres analizar por inicio o fin real).
- `FactAvisos.[Fecha Reporte]`
- `FactLubricacion.[Próxima Aplicación]`
- `FactInspecciones.[Fecha Inspección]`
- `FactParadas.[Fecha Parada]`

---

## 4. Medidas clave (carpeta `_Medidas`)

| Carpeta | Medida | Cálculo |
|---|---|---|
| **Parametros** | `Tarifa Hora Hombre` | $50/h (ajustar) |
| | `Precio Promedio Material` | $100/u (ajustar) |
| | `Horas Calendario` | 8760 (año) — usar 720 (mes) si filtras por mes |
| **KPIs Principales** | `Total OTs`, `OTs Abiertas`, `OTs Cerradas`, `Horas Parada Total` | |
| | `MTTR` | DuraciónCerradas / OTsCerradas |
| | `MTBF` | (HorasCalendario − HorasParada) / Fallas |
| | `Disponibilidad` | MTBF / (MTBF + MTTR) |
| | `Confiabilidad` | exp(−720/MTBF) → confiabilidad a 30 días |
| **Costos** | `Horas MO Total`, `Cantidad Materiales` | suman desde ot_personnel / ot_materials |
| | `Costo Mano de Obra` | Horas MO × Tarifa |
| | `Costo Materiales` | Cantidad × Precio |
| | `Costo Total Mantenimiento`, `Costo Promedio por OT`, `% Costo Correctivo` | |
| **Órdenes de Trabajo** | `OTs Correctivas`, `Preventivas`, `Predictivas` | |
| | `Ratio Preventivo vs Correctivo`, `Cumplimiento Plan`, `Backlog OTs` | |
| **Confiabilidad** | `MTBF por Equipo`, `MTTR por Equipo`, `Disponibilidad por Equipo` | |
| | `Ranking Equipo Fallas`, `Pareto Fallas Acumulado`, `OEE Estimado` | |
| **Técnicos** | `OTs por Técnico`, `Horas por Técnico`, `Eficiencia Técnico` | |
| **Lubricación** | `Lubricaciones Completadas/Pendientes/Vencidas/Críticas` | basado en semáforo |
| **Avisos** | `Avisos Abiertos`, `Avisos con OT`, `% Conversión Aviso a OT`, `Tiempo Respuesta Aviso (h)`, `Avisos Críticos` | |
| **Paradas** | `Horas Parada Planta`, `Overtime Paradas`, `% Cumplimiento Parada` | |
| **Inspecciones** | `Espesor Promedio/Mínimo (mm)`, `Lecturas Críticas/Alerta`, `% Cumplimiento Inspecciones` | |
| **Tendencias** | `OTs Mes Anterior`, `Variación OTs MoM`, `Tendencia Disponibilidad`, `Variación Costo MoM` | |

---

## 5. Flujo de refresh

1. Abrir `MANTENIMIENTO.pbip` en Power BI Desktop.
2. La primera vez PBI puede pedir credenciales del DSN. Seleccionar **Database**, ingresar usuario/contraseña del DSN (los mismos del paso 1.2).
3. **Inicio → Actualizar** (o `Ctrl+Alt+F5`).
4. Tiempo estimado de refresh full: 1–3 min según volumen.

---

## 6. Publicar a Power BI Service

1. **Archivo → Publicar → Publicar en Power BI** → elegir workspace.
2. En Power BI Service:
   - **Configuración del dataset → Credenciales del origen de datos** → editar `Odbc:dsn=CMMS_Supabase` → introducir credenciales.
   - **Gateway de datos**: si el DSN existe solo en tu máquina necesitas un **Personal Gateway** o **Standard Gateway** apuntando a esa máquina. Para producción usar Standard Gateway en un servidor con DSN configurado.
3. **Programación de actualización**: configurar refresh diario.

---

## 7. Cambios aplicados en esta refactorización (Fase A)

### Bugs corregidos
- `DimComponentes`: usaba `equipment_id` inexistente; ahora correctamente referencia `system_id`.
- `FactAvisos`: severidad mapeaba a `specialty` (especialidad); ahora a `criticality`. Número OT mapeaba al código del aviso; ahora a `ot_number`. Fechas mapeaban a `shift` (turno); ahora a `request_date`, `treatment_date`, `planning_date`.
- `FactLubricacion`: estado estaba hardcoded a "Pendiente"; ahora derivado del semáforo (`Cumplido/Próximo/Vencido`). `Próxima Aplicación` estaba hardcoded a `TODAY()`; ahora viene de `next_due_date`.
- `FactInspecciones`: ahora incluye `Próxima Inspección` y agregaciones desde `thickness_readings` para espesores reales.
- `FactParadas`: `Horas Totales` ahora computado de `end_time − start_time`; `Overtime` parseado a número.
- `_Medidas`: corregidas referencias a columnas inexistentes (`Fecha Tratamiento`→`Fecha Evaluación`, `Criticidad Aviso`→`Severidad Aviso`, `Valor Medido`→`thickness_readings[value_mm]`, etc.).
- `MTBF`: ahora respeta el contexto de filtro y usa `Horas Calendario` parametrizable.

### Estructura
- Eliminadas 11 tablas duplicadas snake_case (`work_orders`, `maintenance_notices`, etc.) — sus particiones M ahora viven directamente en las Dim/Fact.
- Eliminadas 5 `LocalDateTable_*` autogeneradas + `DateTableTemplate_*`.
- Apagado `__PBI_TimeIntelligenceEnabled` (auto date/time).
- 30+ relaciones del star schema explícitamente declaradas.
- Fechas string convertidas a `dateTime` en todas las Fact tables.

### Theme
- Nuevo `Industrial_Dark.json`: paleta cyan corporate sobre fondo navy oscuro (#0F1923 fondo, #1A2332 paneles, #00B8D4 acento, #1DE9B6 positivo, #FFB300 alerta, #FF5252 crítico).
- Registrado como `customTheme` en `report.json`. Todos los visuales heredan el look enterprise automáticamente.

---

## 8. Plan de mejoras visuales por página (Fase C — aplicar en PBI Desktop)

Las 12 páginas existen con visuales preconstruidos. Después de validar el refresh, recomendamos estas mejoras manuales:

### 01 Resumen Ejecutivo (página principal)
- Header con logo + título "Mantenimiento Industrial – Dashboard Ejecutivo".
- Fila 1 (KPI cards): `Total OTs` | `Disponibilidad` | `MTBF` | `MTTR` | `Backlog OTs` | `Costo Total Mantenimiento`.
- Fila 2: line chart `Disponibilidad` por mes (`DimFecha[Año-Mes]`) + sparkline `Variación OTs MoM`.
- Fila 3: donut `OTs por Tipo` + bar chart `Top 10 Equipos por Fallas` + heatmap `Horas Parada por Área × Mes`.
- Slicers laterales: `DimFecha[Año]`, `DimFecha[Trimestre]`, `DimAreas[Área]`.

### 02 OTs Detalle
- Matrix: `DimAreas[Área]` × `DimEquipos[Equipo]` × medidas (Total, Correctivas, Preventivas, Cumplimiento Plan).
- Table detalle con `Código OT`, `Tipo`, `Estado`, `Equipo`, `Técnico`, `Fechas`, `Duración Real`, `Costo Total` (drill-through).
- Slicer multi-select `Tipo OT`, `Estado OT`.

### 03 Disponibilidad
- KPI grande: `Disponibilidad` actual con `Tendencia Disponibilidad` mes anterior como goal.
- Line chart `Disponibilidad por Equipo` (top 10).
- Gauge `OEE Estimado` con bandas 0/60/85/100.

### 04 Confiabilidad
- KPI `MTBF`, `MTTR`, `Confiabilidad`, `Tasa de Fallas`.
- Pareto chart: bar `Total Fallas` por Equipo + línea `Pareto Fallas Acumulado` (umbral 80%).
- Tabla `MTBF/MTTR por Equipo` con sparklines.

### 05 Análisis Fallas
- Treemap `Modo Falla` × `Total Fallas`.
- Sankey (custom visual de marketplace) `Categoría Falla` → `Modo Falla` → `Equipo`.
- Tabla pivot `Fallas por Modo × Mes`.

### 06 Preventivo
- KPI `OTs Preventivas`, `Cumplimiento Plan`, `% Costo Correctivo`.
- Calendar heatmap `Fecha Programada` × `Cumplimiento Plan`.
- Bar chart `Cumplimiento Plan` por Área.

### 07 Avisos
- KPI `Total Avisos`, `Avisos Abiertos`, `Avisos Críticos`, `% Conversión Aviso a OT`, `Tiempo Respuesta Aviso (h)`.
- Funnel: Reportado → Evaluado → Planificado → OT.
- Bar chart `Avisos por Severidad`.
- Table con drill-through a OT (relación `notice_id`).

### 08 Paradas de Planta
- Gantt (custom visual) con `Inicio Parada` → `Fin Parada` por planta.
- KPI `Horas Parada Planta`, `Overtime Paradas`, `% Cumplimiento Parada`.
- Stacked bar `Horas Totales vs Horas Overtime` por parada.

### 09 Lubricación
- KPI `Total Lubricaciones`, `Lubricaciones Vencidas`, `% Cumplimiento Lubricación`.
- Semaphore card por punto (verde/amarillo/rojo según `Estado Lub`).
- Table detalle con `Días Para Vencer` codificado por color.

### 10 Predictivo
- Reservar para indicadores predictivos (vibración, termografía) — pendiente de datos en BD.

### 11 Inspecciones
- KPI `Total Inspecciones`, `Espesor Mínimo (mm)`, `Lecturas Críticas`.
- Line chart `Espesor Promedio (mm)` por `DimFecha[Año-Mes]`.
- Table inspecciones con drill al detalle de lecturas (`thickness_readings`).

### 12 Técnicos
- KPI `OTs por Técnico`, `Horas por Técnico`, `Eficiencia Técnico`, `Tasa Cierre Técnico`, `Costo por Técnico`.
- Bar chart Top 10 técnicos por OTs.
- Scatter `Eficiencia` (Y) vs `Horas` (X) con tamaño por `Total OTs`.

---

## 9. Próximos pasos sugeridos

- [ ] Verificar credenciales del DSN ODBC y refrescar.
- [ ] Validar visualmente que los costos se calculan correctamente (cambiar `Tarifa Hora Hombre` y `Precio Promedio Material` si tienes valores reales).
- [ ] Aplicar las mejoras visuales página por página siguiendo la sección 8.
- [ ] Si el equipo necesita visuales personalizados (Gantt, Sankey, Heatmap calendar): instalar desde **AppSource** los visuales marketplace certificados de Microsoft.
- [ ] Publicar a Power BI Service y configurar refresh programado vía Gateway.
- [ ] Compartir workspace con stakeholders de mantenimiento, confiabilidad y producción.
