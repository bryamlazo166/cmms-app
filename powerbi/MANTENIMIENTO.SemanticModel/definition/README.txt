POWER BI SEMANTIC MODEL: MANTENIMIENTO CMMS
============================================

FILE LOCATION:
/sessions/bold-intelligent-franklin/mnt/PBIR/MANTENIMIENTO.SemanticModel/definition/model.tmdl

DATABASE CONNECTION:
- Server: aws-0-us-west-2.pooler.supabase.com
- Database: postgres
- Schema: public
- Authentication: Requires Supabase credentials

MODEL STRUCTURE:
================

DIMENSION TABLES (7):
1. DimAreas (9 records)
   - id (key), Área, Descripción

2. DimLineas (34 records)
   - id (key), Línea, area_id (FK), Descripción

3. DimEquipos (58 records)
   - id (key), Equipo, Tag Equipo, line_id (FK), Criticidad, Descripción

4. DimSistemas (238 records)
   - id (key), Sistema, equipment_id (FK)

5. DimComponentes (1,431 records)
   - id (key), Componente, system_id (FK), Criticidad, Descripción

6. DimTecnicos (15 records)
   - id (key), Técnico, Especialidad, Activo, Contacto

7. DimFecha (Calculated)
   - Date (key), Año, Mes Num, Mes, Semana, Trimestre, Año-Mes, Dia Semana, Es Fin Semana
   - Range: 2020-01-01 to 2026-12-31

FACT TABLES (5):
1. FactOTs (Work Orders - 44 columns)
   - All OT fields from work_orders table
   - Includes derived and descriptive columns
   - Primary relationships to DimEquipos, DimTecnicos, DimFecha

2. FactAvisos (Maintenance Notices - 30 columns)
   - All notice fields from maintenance_notices table
   - Includes criticality, priority, workflow tracking
   - Relationships to DimEquipos

3. FactParadas (Shutdowns - 17 columns)
   - Complete shutdown records
   - Includes compliance tracking and OT counts
   - Operational and overtime metrics

4. FactLubPuntos (Lubrication Points)
   - Equipment lubrication maintenance points
   - Semaphore status tracking (Al Día/Por Vencer/Vencido)
   - Frequency and active status

5. FactLubEjecuciones (Lubrication Executions)
   - Point-level execution records
   - Anomaly and leak detection tracking
   - Audit trail with creation notice links

RELATIONSHIPS (10):
- FactOTs.equipment_id → DimEquipos.id
- FactOTs.technician_id → DimTecnicos.id
- FactOTs."Fecha Programada" → DimFecha.Date
- FactAvisos.equipment_id → DimEquipos.id
- FactLubPuntos.equipment_id → DimEquipos.id
- FactLubEjecuciones.point_id → FactLubPuntos.id
- DimEquipos.line_id → DimLineas.id
- DimLineas.area_id → DimAreas.id
- DimSistemas.equipment_id → DimEquipos.id
- DimComponentes.system_id → DimSistemas.id

MEASURES: 58 TOTAL (Organized in 7 Display Folders)
=====================================================

KPIs PRINCIPALES (8 measures):
- Total OTs, OTs Cerradas, OTs Abiertas, OTs En Progreso
- % Correctivo, % Preventivo, Backlog OTs
- Indice Mantenimiento Preventivo

ORDENES DE TRABAJO (13 measures):
- OTs Correctivas, OTs Preventivas, OTs Ronda Diaria
- Tiempo Promedio Cierre dias
- OTs con Parada, Horas Totales Parada
- Duracion Promedio OT h
- OTs con Logistica Bloqueada, OTs con Informe Pendiente
- OTs esta Semana, OTs este Mes, OTs Atrasadas

CONFIABILIDAD (10 measures):
- Fallas Correctivas, Total Horas Parada
- MTTR h (Mean Time To Repair)
- MTBF h (Mean Time Between Failures)
- Disponibilidad Mecanica %, Confiabilidad 720h %
- Tasa Falla lambda, Horas Operativas
- Ratio Parada Operacion, OEE Indicativo

TECNICOS (5 measures):
- Tecnicos Activos, OTs por Tecnico
- Carga Promedio Tecnico, Ratio Tecnico Equipo
- OTs Sin Cerrar por Tecnico

LUBRICACION (7 measures):
- Total Puntos Lubricacion, Puntos Vencidos
- % Cumplimiento Lubricacion, Puntos Al Dia
- Ejecuciones Lubricacion
- Anomalias Lubricacion, Fugas Detectadas

AVISOS (6 measures):
- Total Avisos, Avisos Pendientes, Avisos Cerrados
- % Conversion Aviso OT
- Avisos por Turno, Avisos Alta Criticidad

PARADAS DE PLANTA (5 measures):
- Total Paradas, Horas Parada Planta
- % Cumplimiento Promedio Parada
- Overtime Total Paradas, Paradas Completadas

TENDENCIAS (4 measures):
- OTs MoM % (Month over Month)
- Fallas Acumuladas, Disponibilidad Acumulada
- MTBF Tendencia

TECHNICAL SPECIFICATIONS:
=========================

Language & Culture: es-ES (Spanish-Spain)
Default Format: #,0.00
Tab Indentation: Used (no spaces)
Comments: None (TMDL doesn't support them)
Partition Mode: Import (not DirectQuery)

M QUERY ENGINE:
- PostgreSQL.Database() connection
- Table.TransformColumnTypes() for type safety
- Schema-qualified: [Schema="public"]
- Error handling: ExtraValues.Error

DAX FUNCTIONS USED:
- COUNTROWS, CALCULATE, COUNTA, SUMX, AVERAGEX
- DIVIDE (with error handling), DATEDIFF, DATEADD
- FILTER, VALUES, DISTINCT
- IF, AND, OR
- TRUE(), TODAY(), YEAR, MONTH, ISONORAFTER
- EXP (exponential for reliability calculations)

FORMATTING STRINGS:
- "#,0" for integers (thousands separator)
- "0.0%" for percentages
- "0.0" for decimal hours/days
- "0.00" for ratios and technical metrics

NOTES FOR DEPLOYMENT:
=====================

1. PostgreSQL credentials required in Power BI
2. Supabase pooler connection string configured
3. Refresh policy: Data import on schedule
4. All tables use import mode (snapshot data)
5. Calculated DimFecha table includes 7 years of dates

PRODUCTION READINESS CHECKLIST:
✓ All 10 source tables mapped
✓ 44 FactOTs columns included
✓ 30 FactAvisos columns included
✓ 17 FactParadas columns included
✓ Proper key relationships (10 total)
✓ 58 business measures defined
✓ Spanish column/measure naming
✓ Format strings applied
✓ Display folders organized
✓ No syntax errors or comments
✓ Tab indentation verified
✓ Calculated table for dates
✓ Hierarchical relationships (Area→Line→Equipment)

VERSION: 1.0 - Production Ready
CREATED: April 2026
