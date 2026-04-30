# scripts/

Utilidades fuera del flujo de la app.

## Estructura

- **migrations/** — scripts one-shot de migración de schema/datos. Ya
  ejecutados en su momento; se conservan como historial. NO volver a
  correr sin revisar (algunos asumen estado previo).

- **seeds/** — generadores de datos catálogo (lubricación, espesores,
  taxonomía, specs). Se pueden volver a usar para sembrar datos de
  prueba o nuevos equipos.

- **debug/** — utilidades de diagnóstico (consultas exploratorias,
  inspección de schema, prueba de conexión, etc.). Útiles cuando hay
  que investigar algo en producción.

- **_archive/** — código legacy mantenido sólo por referencia.
  - `legacy_tests/` — tests informales ad-hoc previos al pytest formal.
  - `exports/` — outputs de pruebas (Excel) que se quedaron en raíz.
  - `models_backup.py` — backup viejo de models.py.

- **smoke_test.ps1** — smoke test rápido del API contra localhost.

## Operativos en uso

Estos viven en la raíz de `scripts/` y son seguros de correr:

- `backup_db.py` — dump completo de la BD (ver módulo de backup
  en /admin si existe el endpoint).
- `index_history_embeddings.py` — re-indexa OTs/avisos cerrados al
  vector store del bot (RAG).
- `reindex_rag.py` — alias / variante del anterior.
- `fix_js.py` — utilidad para corregir issues comunes en JS al hacer
  ediciones masivas.
