# Guía paso a paso — Armar el dashboard en Power BI Desktop

> El modelo ya está listo: 17 tablas conectadas a Supabase, 60+ medidas DAX en `_Medidas`, tema oscuro enterprise aplicado. Solo falta arrastrar campos para crear visuales.

## Antes de empezar (5 min)

### 1. Convertir fechas a tipo Fecha
Las fechas vienen como texto desde la BD. Hay que convertirlas para que funcionen time intelligence y filtros temporales.

En Power BI Desktop → vista **Modelo** (icono de las tablas relacionadas a la izquierda), o vista **Datos** (icono de la tabla):

| Tabla | Columna | Tipo deseado |
|---|---|---|
| FactOTs | Fecha Programada | Fecha |
| FactOTs | Fecha Inicio Real | Fecha y hora |
| FactOTs | Fecha Fin Real | Fecha y hora |
| FactAvisos | Fecha Reporte | Fecha y hora |
| FactLubricacion | Próxima Aplicación | Fecha |
| FactInspecciones | Fecha Inspección | Fecha |
| FactInspecciones | Próxima Inspección | Fecha |
| FactParadas | Fecha Parada | Fecha |
| FactParadas | Hora Inicio | Fecha y hora |
| FactParadas | Hora Fin | Fecha y hora |

**Cómo cambiar tipo:** Click en la columna → en el menú superior **Herramientas de columna** → **Tipo de datos** → seleccionar Fecha o Fecha y hora.

### 2. Crear relaciones con DimFecha
Después de convertir las fechas, en vista **Modelo**:
- Arrastra `FactOTs[Fecha Programada]` → `DimFecha[Date]` (relación activa)
- Arrastra `FactOTs[Fecha Inicio Real]` → `DimFecha[Date]` (PBI la marca inactiva — déjala así)
- Arrastra `FactAvisos[Fecha Reporte]` → `DimFecha[Date]`
- Arrastra `FactLubricacion[Próxima Aplicación]` → `DimFecha[Date]`
- Arrastra `FactInspecciones[Fecha Inspección]` → `DimFecha[Date]`
- Arrastra `FactParadas[Fecha Parada]` → `DimFecha[Date]`

---

## 01 Resumen Ejecutivo

Layout 1280×720, fondo oscuro.

### Visual 1 — Título (Cuadro de texto)
- **Insertar** → **Cuadro de texto** → escribir: `MANTENIMIENTO INDUSTRIAL — RESUMEN EJECUTIVO`
- Tamaño: 22pt, Negrita, color `#E8EDF3` (gris claro)
- Posición: arriba a la izquierda

### Visual 2 — Slicer Año
- Arrastrar `DimFecha[Año]` al canvas
- En **Visualizaciones** → cambiar a **Segmentación de datos**
- Configuración: **Formato** → **Opciones** → orientación **Horizontal**
- Posición: arriba derecha

### Visual 3 a 6 — KPI Cards fila 1
Para cada uno: Arrastrar la medida → en Visualizaciones cambiar a **Tarjeta**.
1. `_Medidas[Total OTs]`
2. `_Medidas[Disponibilidad]`
3. `_Medidas[MTBF]`
4. `_Medidas[MTTR]`

### Visual 7 a 10 — KPI Cards fila 2
5. `_Medidas[Backlog OTs]`
6. `_Medidas[Costo Total Mantenimiento]`
7. `_Medidas[Cumplimiento Plan]`
8. `_Medidas[Avisos Abiertos]`

### Visual 11 — Bar chart "OTs por Área"
- Visualización: **Gráfico de barras agrupadas**
- Eje Y: `DimAreas[Área]`
- Eje X: `_Medidas[Total OTs]`
- Ordenar por Total OTs descendente (click en `...` → Ordenar por → Total OTs → Descendente)
- Título: "OTs por Área"

### Visual 12 — Donut chart "OTs por Tipo"
- Visualización: **Gráfico de anillos**
- Leyenda: `FactOTs[Tipo OT]`
- Valores: `_Medidas[Total OTs]`
- Título: "OTs por Tipo"

### Visual 13 — Line chart "Disponibilidad por mes"
- Visualización: **Gráfico de líneas**
- Eje X: `DimFecha[Año-Mes]`
- Eje Y: `_Medidas[Disponibilidad]`, `_Medidas[Cumplimiento Plan]`
- Título: "Disponibilidad y Cumplimiento por Mes"

---

## 02 OTs Detalle

### Slicers (arriba)
- `FactOTs[Tipo OT]` → Segmentación de datos
- `FactOTs[Estado OT]` → Segmentación de datos
- `DimAreas[Área]` → Segmentación de datos
- `DimFecha[Año]` → Segmentación de datos

### KPIs (fila 1)
- `_Medidas[Total OTs]`
- `_Medidas[OTs Cerradas]`
- `_Medidas[Backlog OTs]`
- `_Medidas[Duración Promedio OT]`

### Matrix (centro)
- Visualización: **Matriz**
- Filas: `DimAreas[Área]`, `DimEquipos[Equipo]`
- Columnas: `FactOTs[Tipo OT]`
- Valores: `_Medidas[Total OTs]`

### Tabla detalle (abajo)
- Visualización: **Tabla**
- Columnas:
  - `FactOTs[Código OT]`
  - `FactOTs[Tipo OT]`
  - `FactOTs[Estado OT]`
  - `DimEquipos[Equipo]`
  - `FactOTs[Fecha Programada]`
  - `FactOTs[Duración Estimada]`
  - `FactOTs[Duración Real]`
  - `FactOTs[Horas de Parada]`

---

## 03 Disponibilidad

### KPI cards (arriba)
- `_Medidas[Disponibilidad]`
- `_Medidas[MTBF]`
- `_Medidas[MTTR]`
- `_Medidas[Confiabilidad]`
- `_Medidas[OEE Estimado]`

### Bar chart "Disponibilidad por Equipo"
- Eje Y: `DimEquipos[Equipo]`
- Eje X: `_Medidas[Disponibilidad por Equipo]`
- Filtro: Top N 15 por Disponibilidad descendente

### Gauge "Disponibilidad global"
- Visualización: **Medidor**
- Valor: `_Medidas[Disponibilidad]`
- Mínimo: 0, Máximo: 1, Objetivo: 0.9

### Tabla "MTBF / MTTR por equipo"
- Columnas: `DimEquipos[Equipo]`, `_Medidas[MTBF por Equipo]`, `_Medidas[MTTR por Equipo]`, `_Medidas[Disponibilidad por Equipo]`

---

## 04 Confiabilidad

### KPI cards
- `_Medidas[Total Fallas]`
- `_Medidas[MTBF]`
- `_Medidas[Tasa de Fallas]`
- `_Medidas[Confiabilidad]`

### Pareto (Bar + Line combinado)
- Visualización: **Gráfico de columnas y líneas agrupadas**
- Eje compartido: `DimEquipos[Equipo]`
- Columna: `_Medidas[Total Fallas]`
- Línea: `_Medidas[Pareto Fallas Acumulado]`
- Ordenar por Total Fallas descendente, Top N 15
- Línea de objetivo en 80% (regla)

### Bar chart "Fallas por Modo"
- Eje: `FactOTs[Modo Falla]`
- Valor: `_Medidas[Fallas por Modo]`

### Tabla "Ranking de equipos"
- Columnas: `DimEquipos[Equipo]`, `_Medidas[Ranking Equipo Fallas]`, `_Medidas[Total Fallas]`, `_Medidas[MTBF por Equipo]`

---

## 05 Análisis Fallas

### KPIs
- `_Medidas[Total Fallas]`
- `_Medidas[OTs Correctivas]`
- `_Medidas[% Bloqueo Logístico]` (si aplica)

### Treemap "Modos de Falla"
- Categoría: `FactOTs[Modo Falla]`
- Valores: `_Medidas[Total Fallas]`

### Stacked bar "Fallas por Área × Tipo"
- Eje Y: `DimAreas[Área]`
- Eje X: `_Medidas[Total Fallas]`
- Leyenda: `FactOTs[Modo Falla]`

### Tabla "Detalle de OTs correctivas"
- Filtro a nivel visual: `FactOTs[Tipo OT] = "Correctivo"`
- Columnas: Código OT, Equipo, Modo Falla, Fecha Programada, Duración Real, Horas de Parada

---

## 06 Preventivo

### KPIs
- `_Medidas[OTs Preventivas]`
- `_Medidas[OTs Predictivas]`
- `_Medidas[Cumplimiento Plan]`
- `_Medidas[% Costo Correctivo]`

### Line chart "OTs por tipo en el tiempo"
- Eje X: `DimFecha[Año-Mes]`
- Y: `_Medidas[OTs Preventivas]`, `_Medidas[OTs Correctivas]`, `_Medidas[OTs Predictivas]`

### Bar chart "Cumplimiento Plan por Área"
- Eje: `DimAreas[Área]`
- Valor: `_Medidas[Cumplimiento Plan]`

### Tabla "Plan vs Real por Equipo"
- Columnas: `DimEquipos[Equipo]`, `_Medidas[OTs Preventivas]`, `_Medidas[Total OTs]`, `_Medidas[Cumplimiento Plan]`

---

## 07 Avisos

### KPIs
- `_Medidas[Total Avisos]`
- `_Medidas[Avisos Abiertos]`
- `_Medidas[Avisos Críticos]`
- `_Medidas[% Conversión Aviso a OT]`

### Bar chart "Avisos por Severidad"
- Eje: `FactAvisos[Severidad Aviso]`
- Valor: `_Medidas[Total Avisos]`

### Donut "Avisos por Estado"
- Leyenda: `FactAvisos[Estado Aviso]`
- Valores: `_Medidas[Total Avisos]`

### Tabla detalle
- `FactAvisos[Código Aviso]`, `[Severidad Aviso]`, `[Estado Aviso]`, `[Reportado Por]`, `[Fecha Reporte]`, `DimEquipos[Equipo]`, `[Número OT Aviso]`

---

## 08 Paradas de Planta

### KPIs
- `_Medidas[Total Paradas]`
- `_Medidas[Paradas Completadas]`

### Bar chart "Paradas por Tipo"
- Eje: `FactParadas[Tipo Parada]`
- Valor: `_Medidas[Total Paradas]`

### Tabla detalle
- `FactParadas[Nombre Parada]`, `[Tipo Parada]`, `[Estado Parada]`, `[Fecha Parada]`, `[Hora Inicio]`, `[Hora Fin]`, `[Observaciones]`

---

## 09 Lubricación

### KPIs
- `_Medidas[Total Lubricaciones]`
- `_Medidas[Lubricaciones Vencidas]` *(estado lub = "red")*
- `_Medidas[Cantidad Total Lubricante]`

### Bar chart "Lubricaciones por Estado"
- Eje: `FactLubricacion[Estado Lub]`
- Valor: `_Medidas[Total Lubricaciones]`
- Coloreado condicional: rojo si "red", amarillo "yellow", verde "green"

### Tabla detalle
- `FactLubricacion[Código Lub]`, `[Punto Lubricación]`, `[Lubricante]`, `[Grado]`, `[Cantidad]`, `[Frecuencia Lub]`, `[Estado Lub]`, `[Próxima Aplicación]`, `DimEquipos[Equipo]`

---

## 10 Predictivo

> Reservada para indicadores predictivos (vibración, termografía, ultrasonidos). Aún no hay datos en la BD. Página vacía por ahora.

---

## 11 Inspecciones

### KPIs
- `_Medidas[Total Inspecciones]`
- `_Medidas[Espesor Promedio (mm)]`
- `_Medidas[Espesor Mínimo (mm)]`
- `_Medidas[Lecturas Críticas]`
- `_Medidas[Lecturas Alerta]`

### Bar chart "Inspecciones por Estado"
- Eje: `FactInspecciones[Estado Inspección]`
- Valor: `_Medidas[Total Inspecciones]`

### Scatter "Lecturas de espesor"
- Eje X: `thickness_readings[value_mm]`
- Eje Y: `thickness_readings[point_id]`
- Color: `thickness_readings[is_critical]`

### Tabla detalle
- `FactInspecciones[Fecha Inspección]`, `[Inspector]`, `[Estado Inspección]`, `DimEquipos[Equipo]`, `[Puntos Totales]`, `[Puntos Críticos]`, `[Puntos Alerta]`

---

## 12 Técnicos

### KPIs
- `_Medidas[OTs por Técnico]`
- `_Medidas[Horas por Técnico]`
- `_Medidas[Eficiencia Técnico]`
- `_Medidas[Tasa Cierre Técnico]`

### Bar chart "Top 10 técnicos por OTs"
- Eje Y: `DimTecnicos[Técnico]`
- Eje X: COUNT(`ot_personnel`) o medida específica
- Top N 10 descendente

### Scatter "Eficiencia vs Horas trabajadas"
- Eje X: `_Medidas[Horas por Técnico]`
- Eje Y: `_Medidas[Eficiencia Técnico]`
- Tamaño: `_Medidas[Total OTs]`
- Detalle: `DimTecnicos[Técnico]`

### Tabla detalle
- `DimTecnicos[Técnico]`, `[Especialidad]`, `_Medidas[Total OTs]`, `_Medidas[Horas por Técnico]`, `_Medidas[Eficiencia Técnico]`, `_Medidas[Tasa Cierre Técnico]`

---

## Tips finales

### Formato consistente (aplicar a todas las páginas)
- Click en cualquier visual → panel **Formato** (icono rodillo) → **General** → **Borde** → activar (radio 4px)
- Tema oscuro ya está aplicado, los visuales heredan automáticamente

### Sincronizar slicers entre páginas
- Click en slicer → menú **Ver** → **Sincronizar segmentaciones** → marcar todas las páginas

### Guardar y publicar
- **Ctrl+S** para guardar el `.pbip`
- **Archivo → Publicar → Publicar en Power BI** para subirlo al workspace

### Cuando llegues a Power BI Service
- Configurar credenciales del DSN ODBC en el dataset
- Configurar refresh programado (diario)
