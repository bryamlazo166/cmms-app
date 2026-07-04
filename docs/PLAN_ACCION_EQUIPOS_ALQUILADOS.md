# Plan de Accion — Equipos Alquilados (RDrental)

Contexto: 10 equipos entre minicargadores y montacargas alquilados a RDrental.
Fallas frecuentes, paralizaciones del area de descarga de materia prima, y el
proveedor casi siempre atribuye la responsabilidad al cliente en su formato.
Los equipos deberian cambiarse cada **4000 horas**.

## Que se implemento en el CMMS (modulo "Equipos Alquilados")

Ruta: `/equipos-alquilados` (sidebar → Activos y Planta → Equipos Alquilados).

1. **Registro de flota**: codigo ALQ-XXX, tipo, marca/modelo/serie, proveedor,
   ubicacion, fecha de inicio, horometro inicial y limite de cambio (4000 h
   configurable por equipo).
2. **Horometros**: lecturas periodicas con historial. Calculan:
   - % de vida util y horas restantes hacia el cambio de unidad.
   - Alerta AMARILLA al 90% y ROJA al superar el limite ("exigir cambio").
3. **Fallas con doble atribucion**: cada falla registra lo que declara el
   proveedor en su formato **y** nuestra evaluacion con sustento escrito.
   Ademas: sistema afectado, horometro, horas de parada, si paralizo
   produccion, y el numero del formato del proveedor (trazabilidad).
4. **Deteccion de fallas repetitivas**: si el mismo equipo falla del mismo
   sistema dentro de 30 dias, se marca REPETIDA y genera alerta ROJA
   ("reclamar mala reparacion").
5. **Indicadores por equipo**: MTBF en horas reales de horometro, fallas
   30/90 dias, horas de parada acumuladas, paralizaciones de produccion, y
   conteo de fallas "en disputa" (proveedor dice NUESTRA, nosotros decimos
   PROVEEDOR/COMPARTIDA).
6. **Export a Excel** de todo el historial de fallas con ambas versiones de
   responsabilidad — este es el sustento que se lleva a la reunion con el
   proveedor.

## Rutina operativa recomendada

| Frecuencia | Accion |
|---|---|
| Diario | Registrar toda falla EL MISMO DIA, antes de que llegue el proveedor. Foto del horometro. |
| Al atender el proveedor | Anotar el nro de su formato en la falla. NO firmar conformidad si nuestra evaluacion difiere — registrar el sustento en el campo correspondiente. |
| Semanal | Registrar lectura de horometro de los 10 equipos (5 min). |
| Mensual | Exportar Excel de fallas y revisar alertas: equipos con fallas repetidas o >3 fallas/30d → carta formal al proveedor. |
| Trimestral | Revision de contrato con datos: MTBF por equipo, % disponibilidad, unidades sobre 90% de vida. |

## Argumentos que el modulo te da para defender la posicion

1. **Falla repetida ≤30 dias del mismo sistema** = reparacion deficiente del
   proveedor, no mal uso. Es el argumento mas fuerte y el modulo lo marca solo.
2. **Horometro > 4000 h** = unidad fuera de vida util contractual; toda falla
   posterior es atribuible al desgaste de una unidad que ya debio cambiarse.
3. **Historial de paralizaciones** con horas de parada = impacto economico
   cuantificable (descarga de materia prima detenida).
4. **Discrepancia sistematica** en la atribucion de responsabilidad: si el
   proveedor dice "cliente" en el 90% de casos pero las fallas se repiten tras
   sus reparaciones, el patron mismo es el argumento.

## Siguientes pasos sugeridos (no implementados aun)

- Clausulas a negociar: penalidad por indisponibilidad >X h/mes, unidad de
  respaldo (backup) obligatoria, cambio automatico a las 4000 h.
- Check-list de entrega/recepcion cada vez que el proveedor interviene una
  unidad (firmado por ambas partes) para cerrar la discusion de "mal uso".
- Capacitacion corta a operadores + registro de operador por turno, para
  eliminar el argumento de mala operacion.
