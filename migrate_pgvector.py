#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Migracion: activar pgvector y crear tabla bot_embeddings.

Permite hacer busqueda semantica sobre OTs cerradas, avisos historicos
y (en el futuro) PDFs subidos al Drive.

Idempotente: se puede correr multiples veces sin efectos colaterales.
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv('DATABASE_URL')


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # 1) Activar extension pgvector
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        print("[+] Extension 'vector' habilitada")
    except Exception as e:
        print(f"[!] No se pudo habilitar 'vector': {e}")
        print("    Habilitalo manualmente en Supabase Dashboard -> Database -> Extensions")
        return

    # 2) Crear tabla bot_embeddings
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_embeddings (
            id           SERIAL PRIMARY KEY,
            entity_type  VARCHAR(40) NOT NULL,
            entity_id    INTEGER NOT NULL,
            text_chunk   TEXT NOT NULL,
            embedding    VECTOR(1536) NOT NULL,
            metadata     JSONB,
            created_at   TIMESTAMP DEFAULT NOW(),
            updated_at   TIMESTAMP DEFAULT NOW()
        )
    """)
    print("[+] Tabla 'bot_embeddings' creada/verificada")

    # 3) Indice unico por entidad para upsert
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_bot_emb_entity
        ON bot_embeddings (entity_type, entity_id)
    """)
    print("[+] Indice unico (entity_type, entity_id) creado")

    # 4) Indice IVFFlat para busqueda rapida por similitud coseno
    # Lists=100 funciona bien hasta ~10K filas. Subir a 200+ con mas datos.
    try:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS ix_bot_emb_vec_cosine
            ON bot_embeddings USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 50)
        """)
        print("[+] Indice IVFFlat creado (busqueda rapida por similitud)")
    except Exception as e:
        # Si la tabla esta vacia, IVFFlat puede fallar. No es critico.
        print(f"[!] IVFFlat skip ({e})")

    conn.commit()
    cur.close()
    conn.close()

    print("\n=== DONE ===")
    print("La tabla 'bot_embeddings' esta lista para almacenar vectores de 1536 dim.")
    print("Siguiente paso: corre 'python index_history_embeddings.py' para indexar OTs/avisos existentes.")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
