"""Apply hybrid asset tree: delete all taxonomy + rebuild in UPPERCASE."""
import os
os.environ['DB_MODE'] = 'supabase'
os.environ['DATABASE_URL'] = 'postgresql://postgres.zxgksjwszqqvwoyfrekw:CmmsTest2026@aws-0-us-west-2.pooler.supabase.com:6543/postgres?sslmode=require'
os.environ['SUPABASE_PROBE_TIMEOUT_SEC'] = '5'
os.environ['ALLOW_LOCAL_FALLBACK'] = '0'
os.environ['SUPABASE_URL'] = 'https://zxgksjwszqqvwoyfrekw.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp4Z2tzandzenFxdndveWZyZWt3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MDUxODY5MiwiZXhwIjoyMDg2MDk0NjkyfQ.8-bychgiueoasxrFLnkvIjyFP6DVlUi5aztz0JOBl5s'

from app import app, db
from sqlalchemy import text

# ── HYBRID TREE DATA ─────────────────────────────────────────────────────────

DIGESTOR_SYSTEMS = {
    "SISTEMA DE ACCIONAMIENTO": [
        "MOTOR ELECTRICO",       # → activo rotativo
        "CAJA REDUCTORA",        # → activo rotativo
        "ACOPLE FUSIBLE",
        "ACOPLE",
        "BRIDA",
        "FAJA",
        "POLEA MOTRIZ",
        "POLEA CONDUCIDO",
        "CHUMACERA MOTRIZ",
        "CHUMACERA CONDUCIDA",
    ],
    "SISTEMA DE VAPOR": [
        "TUBERIA DE VAPOR ENTRADA 1", "VALVULA DE INGRESO DE VAPOR 1", "MANOMETRO 1",
        "TUBERIA DE VAPOR ENTRADA 2", "VALVULA DE INGRESO DE VAPOR 2", "MANOMETRO 2",
        "VALVULA DE CONDENSADO 1", "VALVULA DE CONDENSADO 2",
        "VALVULA CHECK 1", "VALVULA CHECK 2",
        "TRAMPA DE VAPOR 1", "TRAMPA DE VAPOR 2",
        "FILTRO Y 1", "FILTRO Y 2",
        "MANOMETRO DE CHAQUETA", "MANOMETRO DE DESCARGA", "MANOMETRO DE SALIDA",
        "DUCTO DESCARGA DE VAPORES", "VALVULA DESCARGA DE VAPORES",
    ],
    "TANQUE DIGESTOR": [
        "BOCA DE LLENADO", "CHAQUETA INTERNA", "CHAQUETA EXTERIOR", "ENCHAQUETADO EXTERIOR",
        "EJE LADO CONDUCIDO", "EJE LADO MOTRIZ",
        "ESCOTILLA DE DESCARGA",
        "PRENSA ESTOPA LADO CONDUCIDO", "PRENSA ESTOPA LADO MOTRIZ",
        "TAPA BOMBEADA CONDUCIDO", "TAPA BOMBEADA MOTRIZ", "TRIPODE",
    ],
    "SISTEMA DE SOPORTE": ["PLACA BASE"],
    "AUXILIARES": ["GUARDA DE FAJA", "GUARDA MOTOR ELECTRICO"],
}

TH_SYSTEMS = {
    "SISTEMA DE ACCIONAMIENTO": [
        "MOTORREDUCTOR",         # → activo rotativo
        "CADENA",
        "SPROCKET MOTRIZ", "SPROCKET CONDUCIDO",
        "CHUMACERA MOTRIZ", "CHUMACERA CONDUCIDA",
        "CHAVETA",
    ],
    "TORNILLO SINFIN": [
        "TUBO CENTRAL", "HELICE", "PUENTE",
        "EJE MOTRIZ", "EJE DE COLA", "EJE CENTRAL",
    ],
    "SISTEMA CUERPO": [
        "TINA", "TAPAS SUPERIORES", "TAPAS LATERALES",
        "CHUTE DE ALIMENTACION", "CHUTE DE DESCARGA", "CHUTE CENTRAL", "PATIN",
    ],
    "SISTEMA SOPORTE": [
        "PLACA BASE DE MOTORREDUCTOR", "SOPORTE DE TINA", "PLUMA DE IZAJE",
    ],
    "AUXILIARES": [
        "GUARDA CADENA", "GUARDA PARA ACEITE", "GUARDA PARA CHUMACERA", "GUARDA PARA FAJA",
    ],
}

# Other areas/lines/equipment
OTHER = [
    # (area, line, equipo, tag)
    ("CALDERAS", "CALDERA 400 BHP", None, None),
    ("CALDERAS", "CALDERA 900 BHP", None, None),
    ("CALDERAS", "MANIFOLD DE VAPOR", None, None),
    ("CALDERAS", "OSMOSIS", None, None),
    ("COCCION", "HIDROLAVADORAS", None, None),
    ("COCCION", "LINEA PERCOLADOR", "PERCOLADOR #1", "PER1"),
    ("COCCION", "LINEA PERCOLADOR", "PERCOLADOR #2", "PER2"),
    ("LINEA DE POLLO", None, None, None),
    ("MOLINO", "CICLON DE ENSAQUE", None, None),
    ("MOLINO", "CICLON DE LLEGADA", None, None),
    ("MOLINO", "FAJA TRANSPORTADORA", None, None),
    ("MOLINO", "LINEA MOLINO #1", None, None),
    ("MOLINO", "LINEA MOLINO #2", None, None),
    ("MOLINO", "LINEA ZARANDA", None, None),
    ("RMP", "HIDROLAVADORAS", "HIDROLAVADORA #1", "H1"),
    ("RMP", "HIDROLAVADORAS", "HIDROLAVADORA #2", "H2"),
    ("RMP", "HIDROLAVADORAS", "HIDROLAVADORA #3", "H3"),
    ("SECADO", "ENFRIADOR", None, None),
    ("SECADO", "LANZAHARINA", None, None),
    ("SECADO", "PURIFICADOR", None, None),
    ("SECADO", "SECADOR #1", None, None),
    ("SECADO", "SECADOR #2", None, None),
    ("SUBESTACION ELECTRICA", None, None, None),
    ("TRITURADO", "HIDROLAVADORA", "HIDROLAVADORA #5", "H5"),
    ("TRITURADO", "TRITURADOR GRANDE", "TH ALIMENTADOR", "THALI"),
    ("TRITURADO", "TRITURADOR GRANDE", "TH SALIDA", "THSAL"),
    ("TRITURADO", "TRITURADOR GRANDE", "TH SILO", "THSI"),
    ("TRITURADO", "TRITURADOR GRANDE", "TRITURADOR 100 HP", "TRI1"),
    ("TRITURADO", "TRITURADOR PEQUENO", "TH SALIDA", "THSAL2"),
    ("TRITURADO", "TRITURADOR PEQUENO", "TRITURADOR 75 HP", "TRI2"),
    ("UTILITIES", None, None, None),
    ("VAHOS", "HIDROLISIS", None, None),
    ("VAHOS", "VAHOS #1", None, None),
    ("VAHOS", "VAHOS #2", None, None),
]


with app.app_context():
    try:
        # ── STEP 1: Nullify all FK references to taxonomy ──
        print("Step 1: Nullifying FK references...")
        null_queries = [
            "UPDATE work_orders SET area_id=NULL, line_id=NULL, equipment_id=NULL, system_id=NULL, component_id=NULL",
            "UPDATE maintenance_notices SET area_id=NULL, line_id=NULL, equipment_id=NULL, system_id=NULL, component_id=NULL",
            "UPDATE rotative_assets SET area_id=NULL, line_id=NULL, equipment_id=NULL, system_id=NULL, component_id=NULL",
            "UPDATE rotative_asset_history SET area_id=NULL, line_id=NULL, equipment_id=NULL, system_id=NULL, component_id=NULL",
            "UPDATE lubrication_points SET area_id=NULL, line_id=NULL, equipment_id=NULL, system_id=NULL, component_id=NULL",
            "UPDATE monitoring_points SET area_id=NULL, line_id=NULL, equipment_id=NULL, system_id=NULL, component_id=NULL",
        ]
        for q in null_queries:
            try:
                db.session.execute(text("SAVEPOINT sp1"))
                db.session.execute(text(q))
                db.session.execute(text("RELEASE SAVEPOINT sp1"))
                print(f"  OK: {q[:60]}...")
            except Exception as e:
                db.session.execute(text("ROLLBACK TO SAVEPOINT sp1"))
                print(f"  SKIP: {q[:40]}... ({e})")

        # Nullable FK tables with different column names
        extra_nulls = [
            ("inspection_routes", ["area_id", "line_id", "equipment_id", "system_id", "component_id"]),
            ("activities", ["equipment_id"]),
            ("condition_points", ["area_id", "line_id", "equipment_id", "system_id", "component_id"]),
            ("inspection_items", ["component_id", "system_id"]),
        ]
        for tbl, cols in extra_nulls:
            for col in cols:
                try:
                    db.session.execute(text("SAVEPOINT sp2"))
                    db.session.execute(text(f"UPDATE {tbl} SET {col}=NULL"))
                    db.session.execute(text("RELEASE SAVEPOINT sp2"))
                except Exception:
                    db.session.execute(text("ROLLBACK TO SAVEPOINT sp2"))

        # Delete from tables that have non-nullable FKs
        delete_deps = [
            "DELETE FROM component_specs",
            "DELETE FROM equipment_specs",
            "DELETE FROM document_links",
            "DELETE FROM spare_parts",
            "DELETE FROM equipment_files",
            "DELETE FROM condition_points",
            "DELETE FROM rotable_installations",
            "DELETE FROM inspection_results",
            "DELETE FROM inspection_executions",
        ]
        for q in delete_deps:
            try:
                db.session.execute(text("SAVEPOINT sp3"))
                db.session.execute(text(q))
                db.session.execute(text("RELEASE SAVEPOINT sp3"))
                print(f"  DEL: {q}")
            except Exception:
                db.session.execute(text("ROLLBACK TO SAVEPOINT sp3"))

        # Also handle rotable_installations
        try:
            db.session.execute(text("SAVEPOINT sp4"))
            db.session.execute(text("DELETE FROM rotable_installations"))
            db.session.execute(text("RELEASE SAVEPOINT sp4"))
        except Exception:
            db.session.execute(text("ROLLBACK TO SAVEPOINT sp4"))

        db.session.commit()
        print("Step 1 complete.")

        # ── STEP 2: Delete all taxonomy using TRUNCATE CASCADE ──
        print("\nStep 2: Truncating all taxonomy (CASCADE)...")
        db.session.execute(text("TRUNCATE TABLE components, systems, equipments, lines, areas CASCADE"))
        db.session.commit()
        print("Step 2 complete — all taxonomy cleared.")

        # ── STEP 3: Reset sequences ──
        print("\nStep 3: Resetting sequences...")
        for tbl in ['areas', 'lines', 'equipments', 'systems', 'components']:
            try:
                db.session.execute(text(f"SELECT setval(pg_get_serial_sequence('{tbl}','id'), 1, false)"))
            except Exception:
                pass
        db.session.commit()

        # ── STEP 4: Insert new hybrid tree ──
        print("\nStep 4: Inserting hybrid tree...")

        area_cache = {}  # name -> id
        line_cache = {}  # (area_id, name) -> id

        def get_or_create_area(name):
            if name in area_cache:
                return area_cache[name]
            db.session.execute(text("INSERT INTO areas (name) VALUES (:n)"), {"n": name})
            aid = db.session.execute(text("SELECT id FROM areas WHERE name = :n"), {"n": name}).scalar()
            area_cache[name] = aid
            return aid

        def get_or_create_line(area_id, name):
            key = (area_id, name)
            if key in line_cache:
                return line_cache[key]
            db.session.execute(text("INSERT INTO lines (name, area_id) VALUES (:n, :a)"), {"n": name, "a": area_id})
            lid = db.session.execute(text("SELECT id FROM lines WHERE name = :n AND area_id = :a"), {"n": name, "a": area_id}).scalar()
            line_cache[key] = lid
            return lid

        def create_equipment(name, tag, line_id):
            db.session.execute(text("INSERT INTO equipments (name, tag, line_id) VALUES (:n, :t, :l)"), {"n": name, "t": tag, "l": line_id})
            return db.session.execute(text("SELECT id FROM equipments WHERE tag = :t"), {"t": tag}).scalar()

        def create_system(name, equipment_id):
            db.session.execute(text("INSERT INTO systems (name, equipment_id) VALUES (:n, :e)"), {"n": name, "e": equipment_id})
            return db.session.execute(text("SELECT id FROM systems WHERE name = :n AND equipment_id = :e"), {"n": name, "e": equipment_id}).scalar()

        def create_component(name, system_id, crit="Media"):
            db.session.execute(text("INSERT INTO components (name, system_id, criticality) VALUES (:n, :s, :c)"), {"n": name, "s": system_id, "c": crit})

        # ── COCCION: Digestors 1-9 ──
        coccion_id = get_or_create_area("COCCION")

        for n in range(1, 10):
            line_id = get_or_create_line(coccion_id, f"LINEA DIGESTOR #{n}")

            # DIGESTOR
            eq_id = create_equipment(f"DIGESTOR #{n}", f"D{n}", line_id)
            for sys_name, comps in DIGESTOR_SYSTEMS.items():
                sys_id = create_system(sys_name, eq_id)
                for comp_name in comps:
                    create_component(comp_name, sys_id)

            # TH
            th_id = create_equipment(f"TH{n}", f"TH{n}", line_id)
            for sys_name, comps in TH_SYSTEMS.items():
                sys_id = create_system(sys_name, th_id)
                for comp_name in comps:
                    create_component(comp_name, sys_id)

            print(f"  LINEA DIGESTOR #{n}: D{n} + TH{n}")

        # ── Other areas/lines/equipment ──
        for area_name, line_name, eq_name, eq_tag in OTHER:
            area_id = get_or_create_area(area_name)
            if line_name:
                line_id = get_or_create_line(area_id, line_name)
                if eq_name and eq_tag:
                    create_equipment(eq_name, eq_tag, line_id)
                    print(f"  {area_name} > {line_name} > {eq_name} [{eq_tag}]")
                else:
                    print(f"  {area_name} > {line_name}")
            else:
                print(f"  {area_name} (area only)")

        db.session.commit()
        print("\nStep 4 complete.")

        # ── STEP 5: Seed failure catalog ──
        print("\nStep 5: Seeding failure catalog...")
        existing = db.session.execute(text("SELECT count(*) FROM failure_catalog")).scalar()
        if existing == 0:
            seeds = [
                ("ROTURA", "MECANICA"), ("DESGASTE", "MECANICA"), ("FUGA", "MECANICA"),
                ("DESALINEACION", "MECANICA"), ("DESBALANCEO", "MECANICA"),
                ("SOBRECALENTAMIENTO", "MECANICA"), ("RUIDO ANORMAL", "MECANICA"),
                ("VIBRACION EXCESIVA", "MECANICA"), ("AFLOJAMIENTO", "MECANICA"),
                ("CORROSION", "MECANICA"), ("ATASCAMIENTO", "MECANICA"),
                ("DESCARRILAMIENTO", "MECANICA"), ("FATIGA", "MECANICA"),
                ("DEFORMACION", "MECANICA"),
                ("CORTOCIRCUITO", "ELECTRICA"), ("SOBRECARGA", "ELECTRICA"),
                ("FALLA DE AISLAMIENTO", "ELECTRICA"),
                ("FUGA HIDRAULICA", "HIDRAULICA"),
                ("FUGA NEUMATICA", "NEUMATICA"),
                ("FALLA DE SENSOR", "INSTRUMENTACION"),
                ("FALTA DE LUBRICACION", "LUBRICACION"),
                ("CONTAMINACION DE LUBRICANTE", "LUBRICACION"),
                ("FRACTURA ESTRUCTURAL", "ESTRUCTURAL"),
            ]
            for fm, fc in seeds:
                db.session.execute(text(
                    "INSERT INTO failure_catalog (failure_mode, failure_category, is_active, usage_count) VALUES (:m, :c, true, 0)"
                ), {"m": fm, "c": fc})
            db.session.commit()
            print(f"  Seeded {len(seeds)} failure modes.")
        else:
            print(f"  Already has {existing} entries, skipping seed.")

        # ── VERIFY ──
        print("\n=== VERIFICATION ===")
        for tbl in ['areas', 'lines', 'equipments', 'systems', 'components']:
            c = db.session.execute(text(f"SELECT count(*) FROM {tbl}")).scalar()
            print(f"  {tbl}: {c}")
        fc = db.session.execute(text("SELECT count(*) FROM failure_catalog")).scalar()
        print(f"  failure_catalog: {fc}")

        db.session.remove()
        print("\nDONE!")

    except Exception as e:
        db.session.rollback()
        db.session.remove()
        import traceback
        traceback.print_exc()
