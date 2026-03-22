import os
from dotenv import load_dotenv
import psycopg2


def _normalize_url(url: str) -> str:
    if url.startswith('postgres://'):
        return 'postgresql://' + url[len('postgres://'):]
    return url


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s AND column_name=%s
        LIMIT 1
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def main():
    load_dotenv(dotenv_path='.env')
    url = os.getenv('DATABASE_URL', '').strip()
    if not url:
        raise SystemExit('DATABASE_URL no configurada en .env')

    url = _normalize_url(url)
    conn = psycopg2.connect(url, sslmode='require')
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # lubrication_points.name
        if not column_exists(cur, 'lubrication_points', 'name'):
            cur.execute('ALTER TABLE lubrication_points ADD COLUMN name VARCHAR(120)')
            print('ADD COLUMN lubrication_points.name')
        if column_exists(cur, 'lubrication_points', 'task_name'):
            cur.execute("""
                UPDATE lubrication_points
                SET name = task_name
                WHERE (name IS NULL OR btrim(name) = '')
                  AND task_name IS NOT NULL
            """)
            print('BACKFILL lubrication_points.name <- task_name')

        # lubrication_points.description
        if not column_exists(cur, 'lubrication_points', 'description'):
            cur.execute('ALTER TABLE lubrication_points ADD COLUMN description TEXT')
            print('ADD COLUMN lubrication_points.description')
        if column_exists(cur, 'lubrication_points', 'notes'):
            cur.execute("""
                UPDATE lubrication_points
                SET description = notes
                WHERE description IS NULL
                  AND notes IS NOT NULL
            """)
            print('BACKFILL lubrication_points.description <- notes')

        # lubrication_executions.execution_date
        if not column_exists(cur, 'lubrication_executions', 'execution_date'):
            cur.execute('ALTER TABLE lubrication_executions ADD COLUMN execution_date VARCHAR(20)')
            print('ADD COLUMN lubrication_executions.execution_date')
        if column_exists(cur, 'lubrication_executions', 'executed_date'):
            cur.execute("""
                UPDATE lubrication_executions
                SET execution_date = executed_date
                WHERE execution_date IS NULL
                  AND executed_date IS NOT NULL
            """)
            print('BACKFILL lubrication_executions.execution_date <- executed_date')

        conn.commit()
        print('OK: Migracion de compatibilidad de lubricacion completada.')
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
