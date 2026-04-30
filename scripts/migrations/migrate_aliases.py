#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Migracion: crea tabla bot_aliases para glosario aprendido del bot.

El bot guarda equivalencias locales que aprende del usuario, ej:
  'fapmetal'    -> 'FAB METAL SAC' (proveedor)
  'el negro'    -> 'chumacera oxidada del D8' (apodo interno)
  'ronda nico'  -> 'ronda diaria area RMP' (jerga del turno)

Cuando el bot recibe un mensaje, expande estos terminos ANTES de enviar
a DeepSeek. Asi el modelo entiende terminos locales sin reentrenar.

Idempotente.
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_aliases (
            id           SERIAL PRIMARY KEY,
            alias        VARCHAR(120) NOT NULL,
            expansion    TEXT NOT NULL,
            category     VARCHAR(40),
            chat_id      BIGINT,
            usage_count  INTEGER DEFAULT 0,
            created_by   VARCHAR(120),
            created_at   TIMESTAMP DEFAULT NOW(),
            updated_at   TIMESTAMP DEFAULT NOW(),
            is_active    BOOLEAN DEFAULT TRUE
        )
    """)
    print("[+] Tabla 'bot_aliases' creada/verificada")

    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_bot_aliases_alias
        ON bot_aliases (LOWER(alias)) WHERE is_active = TRUE
    """)
    print("[+] Indice unico por alias (case-insensitive) creado")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_bot_aliases_chat
        ON bot_aliases (chat_id) WHERE chat_id IS NOT NULL
    """)
    print("[+] Indice por chat_id creado")

    conn.commit()
    cur.close()
    conn.close()

    print("\n=== DONE ===")
    print("La tabla 'bot_aliases' esta lista.")
    print("Comandos del bot disponibles:")
    print("  /alias <termino> = <expansion>   -> guardar")
    print("  /alias <termino> = <expansion> [categoria]")
    print("  /aliases                          -> listar todos")
    print("  /borra_alias <termino>            -> eliminar")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
