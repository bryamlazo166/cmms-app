# Integración Power BI con CMMS Industrial

## Dos formas de conectar Power BI al sistema

### Opción A — Conector Web/JSON (recomendado para dashboards en vivo)

**Ventajas:**
- Datos siempre frescos (refresh programado de Power BI)
- Schema enriquecido (alcance, modo de falla, parada vinculada, etc.)
- Sin acceso directo a la base de datos
- Funciona desde cualquier IP

**Cómo conectar:**

1. Abre **Power BI Desktop** → "Obtener datos" → "Web"
2. URL: `https://tu-cmms.onrender.com/api/powerbi/index`
3. Autenticación: **Básica** (usuario/contraseña de un usuario admin del CMMS)
4. Power BI te mostrará el directorio JSON con todos los endpoints disponibles
5. Para cada dataset que quieras: nuevo origen Web → URL del endpoint → "Convertir a tabla"

**Endpoints disponibles** (ver lista actualizada en `/api/powerbi/index`):

| Endpoint | Datos |
|---|---|
| `/api/powerbi/work-orders-v2` | OTs con jerarquía + aviso + parada vinculada |
| `/api/powerbi/notices-v2` | Avisos con scope, modo falla, fechas de cierre |
| `/api/powerbi/personnel` | Personal asignado a OTs con horas |
| `/api/powerbi/materials` | Materiales/repuestos por OT con costos |
| `/api/powerbi/ot-log` | Bitácora de OTs |
| `/api/powerbi/lubrication-points` | Puntos lubricación + semáforo |
| `/api/powerbi/lubrication-executions` | Histórico de ejecuciones |
| `/api/powerbi/inspection-routes` | Rutas inspección + semáforo |
| `/api/powerbi/inspection-executions` | Ejecuciones (1 fila por item) |
| `/api/powerbi/monitoring-points` | Puntos monitoreo + umbrales |
| `/api/powerbi/monitoring-readings` | Lecturas históricas |
| `/api/powerbi/thickness` | Espesores por punto + desgaste |
| `/api/powerbi/shutdowns` | Cabecera de paradas |
| `/api/powerbi/shutdown-ots` | OTs por parada (cumplimiento) |
| `/api/powerbi/purchases` | Requisiciones + OC vinculada |
| `/api/powerbi/warehouse` | Stock + ABC/XYZ + ROP |
| `/api/powerbi/warehouse-movements` | Kardex completo |
| `/api/powerbi/activities` | Seguimiento + hitos |
| `/api/powerbi/rotative-assets` | Activos rotativos + BOM |
| `/api/powerbi/equipments` | Tabla plana de equipos |
| `/api/powerbi/equipment-tree` | Árbol jerárquico Área→Componente |
| `/api/powerbi/kpis` | Indicadores agregados |

**Refresh programado:**

1. Publica el dashboard a Power BI Service
2. En el dataset → Configuración → "Actualización programada"
3. Recomendado: cada 1 hora durante horario operativo

---

### Opción B — Conexión directa a Postgres (Supabase)

**Ventajas:**
- Queries SQL personalizadas
- Más rápido para datasets grandes
- DirectQuery (sin caché)

**Desventajas:**
- Requiere usuario read-only en la base
- No aprovecha el enriquecimiento del API (alcance, etc.)

**Configuración:**

El archivo `powerbi_connection.odc` ya viene preconfigurado para Supabase pooler. Para usarlo:

1. Doble clic en `powerbi_connection.odc` → abre Excel/Power BI
2. La cadena de conexión apunta a `aws-0-us-west-2.pooler.supabase.com:6543`
3. Usuario: `powerbi_reader.zxgksjwszqqvwoyfrekw` (configurar en Supabase Dashboard → Database → Roles)
4. Contraseña: solicitar al admin del proyecto

---

### Opción C — Excel master (offline, snapshot manual)

Para análisis ad-hoc sin Power BI:

1. Inicia sesión en CMMS como admin
2. URL: `https://tu-cmms.onrender.com/api/reports/powerbi-export`
3. Descarga `CMMS_PowerBI_YYYY-MM-DD.xlsx` (21 hojas)

Útil para enviar el snapshot a alguien sin acceso al sistema.

---

## Modelo de datos sugerido en Power BI

```
                        ┌─────────────────┐
                        │   equipment-    │
                        │      tree       │ (dim)
                        └────────┬────────┘
                                 │ TAG
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
┌───────▼───────┐       ┌────────▼────────┐      ┌────────▼────────┐
│ work-orders   │       │     notices     │      │  shutdown-ots   │
│      -v2      │ TAG ──┤      -v2        │ TAG ─┤                 │
└───────┬───────┘       └─────────────────┘      └─────────────────┘
        │ Codigo_OT
        │
   ┌────┴────┬───────────┬──────────┐
   │         │           │          │
┌──▼──┐ ┌────▼───┐ ┌─────▼─────┐ ┌──▼─────────┐
│ ma- │ │personal│ │ ot-log    │ │ purchases  │
│ter- │ │        │ │           │ │ (OT_Codigo)│
│iales│ │        │ │           │ │            │
└─────┘ └────────┘ └───────────┘ └────────────┘
```

**Relaciones recomendadas:**

| Desde | Columna | Hacia | Columna | Tipo |
|---|---|---|---|---|
| work-orders-v2 | TAG | equipments | TAG | Many-to-One |
| notices-v2 | TAG | equipments | TAG | Many-to-One |
| materials | Codigo_OT | work-orders-v2 | Codigo_OT | Many-to-One |
| personnel | Codigo_OT | work-orders-v2 | Codigo_OT | Many-to-One |
| shutdown-ots | Codigo_OT | work-orders-v2 | Codigo_OT | Many-to-One |
| shutdown-ots | Parada_Codigo | shutdowns | Codigo_Parada | Many-to-One |
| purchases | OT_Codigo | work-orders-v2 | Codigo_OT | Many-to-One |
| warehouse-movements | Codigo_Item | warehouse | Codigo | Many-to-One |
| lubrication-executions | Codigo_Punto | lubrication-points | Codigo | Many-to-One |
| inspection-executions | Codigo_Ruta | inspection-routes | Codigo | Many-to-One |
| monitoring-readings | Codigo_Punto | monitoring-points | Codigo | Many-to-One |
| thickness | TAG | equipments | TAG | Many-to-One |

---

## Dashboards sugeridos

### 1. **Dashboard Ejecutivo** (cards + tendencia)
- KPIs: `/kpis` → tarjetas (OTs abiertas, % preventivo, vencidos)
- Tendencia: `work-orders-v2` agrupado por mes y `Tipo_Mantenimiento`

### 2. **Análisis de Modos de Falla** (Pareto + recurrencia)
- Fuente: `notices-v2`
- Pareto: `Modo_Falla` × count, ordenado descendente
- Recurrencia: `Componente` con count de avisos correctivos

### 3. **Cumplimiento de Plan** (donut + tabla)
- Fuente: `lubrication-points`, `inspection-routes`, `monitoring-points`
- Donut por `Semaforo` (Verde/Amarillo/Rojo)
- Tabla de "vencidos críticos"

### 4. **Costos de Mantenimiento** (barras apiladas)
- Fuente: `materials` joineado con `work-orders-v2`
- Suma de `Costo_Total` por `Area` y `Tipo_Mantenimiento`

### 5. **Cumplimiento de Paradas** (Gantt + cumplimiento)
- Fuente: `shutdown-ots`, `shutdowns`
- % cumplimiento = `Cerrada=Si` / total por parada

### 6. **Stock & Almacén** (tabla + alertas)
- Fuente: `warehouse`
- Filtros por `Clase_ABC`, `Criticidad`
- Alerta: `Stock_Actual < ROP`

---

## Permisos necesarios

El usuario que use Power BI necesita en el CMMS:

- Rol `admin`, **o**
- Rol con flags `view: true` y `export: true` en los módulos que quiera consultar

Para crear un usuario dedicado para Power BI:

1. CMMS → `/usuarios` → "Nuevo Usuario"
2. Username: `powerbi_lector`
3. Rol: crear uno custom o usar `gerencia` (sólo lectura)
4. En la matriz de permisos, asegurar `view + export = true` en todos los módulos relevantes

---

## Troubleshooting

**Error 401 en Power BI:**
- Re-autentica con credenciales del CMMS
- Verifica que el usuario no esté desactivado

**Error 403 en algunos endpoints:**
- El usuario no tiene `view` o `export` para ese módulo
- Editar permisos desde `/usuarios` (admin)

**Datos desactualizados:**
- Power BI cachea por defecto. En Power BI Service → dataset → "Actualizar ahora"
- Programar refresh cada 1-4h en horario operativo

**Mojibake/caracteres raros:**
- Verifica que el connector use UTF-8 (Power BI Desktop lo detecta automáticamente)

**Performance lenta:**
- Para datasets > 50k filas, considerar Opción B (DirectQuery a Postgres)
- O filtrar el endpoint con query params (futuro: agregar `?from=YYYY-MM-DD`)
