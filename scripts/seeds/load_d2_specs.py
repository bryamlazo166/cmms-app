"""Load specs and BOM for Digestor #2 as reference template."""
import os
os.environ['DB_MODE'] = 'supabase'
os.environ['DATABASE_URL'] = 'postgresql://postgres.zxgksjwszqqvwoyfrekw:CmmsTest2026@aws-0-us-west-2.pooler.supabase.com:6543/postgres?sslmode=require'
os.environ['SUPABASE_PROBE_TIMEOUT_SEC'] = '5'
os.environ['ALLOW_LOCAL_FALLBACK'] = '0'
os.environ['SUPABASE_URL'] = 'https://zxgksjwszqqvwoyfrekw.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'x'

from app import app, db
from sqlalchemy import text

# Component specs: (component_id, [(key, value, unit), ...])
COMP_SPECS = {
    # SISTEMA DE ACCIONAMIENTO
    72: [  # MOTOR ELECTRICO
        ("POTENCIA", "40", "HP"),
        ("RPM", "1750", "RPM"),
        ("VOLTAJE", "440", "V"),
        ("FRAME", "324T", ""),
        ("FRECUENCIA", "60", "Hz"),
    ],
    73: [  # CAJA REDUCTORA
        ("RATIO", "30:1", ""),
        ("RPM SALIDA", "58", "RPM"),
        ("TIPO", "HELICOIDAL", ""),
        ("CAPACIDAD ACEITE", "2.5", "Lt"),
    ],
    74: [  # ACOPLE FUSIBLE
        ("TIPO", "FUSIBLE DE CORTE", ""),
        ("DIAMETRO", "POR IDENTIFICAR", ""),
    ],
    75: [  # ACOPLE
        ("TIPO", "FLEXIBLE", ""),
        ("MODELO", "POR IDENTIFICAR", ""),
    ],
    76: [  # BRIDA
        ("DIAMETRO", "POR IDENTIFICAR", "mm"),
        ("PERNOS", "POR IDENTIFICAR", ""),
    ],
    77: [  # FAJA
        ("TIPO", "3V", ""),
        ("MEDIDA", "POR IDENTIFICAR", ""),
        ("CANTIDAD", "3", "unid"),
        ("MARCA RECOMENDADA", "GATES / OPTIBELT", ""),
    ],
    78: [  # POLEA MOTRIZ
        ("CANALES", "3", ""),
        ("TIPO", "3V", ""),
        ("DIAMETRO", "POR IDENTIFICAR", "pulg"),
    ],
    79: [  # POLEA CONDUCIDO
        ("CANALES", "3", ""),
        ("TIPO", "3V", ""),
        ("DIAMETRO", "POR IDENTIFICAR", "pulg"),
    ],
    80: [  # CHUMACERA MOTRIZ
        ("MODELO", "UCP 212", ""),
        ("MARCA", "NTN", ""),
        ("DIAMETRO EJE", "60", "mm"),
        ("TIPO", "PIE", ""),
    ],
    81: [  # CHUMACERA CONDUCIDA
        ("MODELO", "UCP 210", ""),
        ("MARCA", "NTN", ""),
        ("DIAMETRO EJE", "50", "mm"),
        ("TIPO", "PIE", ""),
    ],
    # SISTEMA DE VAPOR
    83: [  # VALVULA DE INGRESO DE VAPOR 1
        ("DIAMETRO", "2", "pulg"),
        ("TIPO", "COMPUERTA", ""),
        ("PRESION TRABAJO", "80", "PSI"),
    ],
    86: [  # VALVULA DE INGRESO DE VAPOR 2
        ("DIAMETRO", "2", "pulg"),
        ("TIPO", "COMPUERTA", ""),
    ],
    88: [  # VALVULA DE CONDENSADO 1
        ("DIAMETRO", "3/4", "pulg"),
        ("TIPO", "BOLA", ""),
    ],
    89: [  # VALVULA DE CONDENSADO 2
        ("DIAMETRO", "3/4", "pulg"),
        ("TIPO", "BOLA", ""),
    ],
    92: [  # TRAMPA DE VAPOR 1
        ("MARCA", "SPIRAX SARCO", ""),
        ("MODELO", "POR IDENTIFICAR", ""),
        ("TIPO", "BALDE INVERTIDO", ""),
        ("DIAMETRO", "3/4", "pulg"),
    ],
    93: [  # TRAMPA DE VAPOR 2
        ("MARCA", "SPIRAX SARCO", ""),
        ("MODELO", "POR IDENTIFICAR", ""),
        ("TIPO", "BALDE INVERTIDO", ""),
    ],
    84: [  # MANOMETRO 1
        ("RANGO", "0-150", "PSI"),
        ("DIAMETRO CARATULA", "4", "pulg"),
        ("CONEXION", "1/2 NPT", ""),
    ],
    87: [  # MANOMETRO 2
        ("RANGO", "0-150", "PSI"),
    ],
    96: [  # MANOMETRO DE CHAQUETA
        ("RANGO", "0-100", "PSI"),
    ],
    # TANQUE DIGESTOR
    102: [  # CHAQUETA INTERNA
        ("MATERIAL", "ACERO AL CARBONO", ""),
        ("ESPESOR NOMINAL", "12", "mm"),
        ("ESPESOR MINIMO ACEPTABLE", "4", "mm"),
    ],
    103: [  # CHAQUETA EXTERIOR
        ("MATERIAL", "ACERO AL CARBONO", ""),
        ("ESPESOR NOMINAL", "10", "mm"),
    ],
    108: [  # PRENSA ESTOPA LADO CONDUCIDO
        ("TIPO EMPAQUETADURA", "GRAFITADA", ""),
        ("MEDIDA", "POR IDENTIFICAR", "mm"),
        ("CANTIDAD ANILLOS", "POR IDENTIFICAR", ""),
    ],
    109: [  # PRENSA ESTOPA LADO MOTRIZ
        ("TIPO EMPAQUETADURA", "GRAFITADA", ""),
        ("MEDIDA", "POR IDENTIFICAR", "mm"),
        ("CANTIDAD ANILLOS", "POR IDENTIFICAR", ""),
    ],
    112: [  # TRIPODE
        ("MATERIAL", "ACERO AL CARBONO", ""),
        ("ESPESOR NOMINAL", "POR IDENTIFICAR", "mm"),
    ],
}

# BOM for rotative assets (asset_id, [(free_text, category, qty, notes)])
ASSET_BOM = {
    # MR-0009 = MOTOR ELECTRICO DIGESTOR #2 (id may vary, we'll find it)
    "MR-0009": [
        ("RODAMIENTO LADO MOTRIZ 6308-2RS", "MECANICO", 1, "LADO ACOPLE"),
        ("RODAMIENTO LADO CONDUCIDO 6207-2RS", "MECANICO", 1, "LADO VENTILADOR"),
        ("RETEN LADO MOTRIZ", "MECANICO", 1, "POR IDENTIFICAR MEDIDA"),
        ("GRASA MOBIL POLYREX EM", "CONSUMIBLE", 1, "PARA RODAMIENTOS"),
        ("VENTILADOR", "MECANICO", 1, "POR IDENTIFICAR"),
        ("CUBIERTA DE VENTILADOR", "MECANICO", 1, "POR IDENTIFICAR"),
    ],
    # MR-0010 = CAJA REDUCTORA DIGESTOR #2
    "MR-0010": [
        ("RODAMIENTO ENTRADA", "MECANICO", 1, "POR IDENTIFICAR MODELO"),
        ("RODAMIENTO SALIDA", "MECANICO", 1, "POR IDENTIFICAR MODELO"),
        ("RETEN ENTRADA", "MECANICO", 1, "POR IDENTIFICAR MEDIDA"),
        ("RETEN SALIDA", "MECANICO", 1, "POR IDENTIFICAR MEDIDA"),
        ("ACEITE MOBIL 630 / EQUIVALENTE", "CONSUMIBLE", 1, "2.5 LITROS"),
        ("VISOR DE ACEITE", "MECANICO", 1, "POR IDENTIFICAR"),
        ("ENGRANAJE HELICOIDAL", "MECANICO", 1, "POR IDENTIFICAR"),
    ],
}

# Equipment-level specs for D2
EQUIP_SPECS = [
    ("CAPACIDAD", "4500", "Kg"),
    ("PRESION DE TRABAJO", "80", "PSI"),
    ("TEMPERATURA DE OPERACION", "140", "C"),
    ("TIEMPO DE COCCION", "POR IDENTIFICAR", "min"),
    ("RPM OPERACION", "58", "RPM"),
    ("TIPO", "HORIZONTAL CON CHAQUETA", ""),
]


with app.app_context():
    try:
        # Ensure free_text column exists
        try:
            db.session.execute(text("ALTER TABLE rotative_asset_bom ADD COLUMN free_text VARCHAR(200)"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(text("ALTER TABLE rotative_asset_bom ALTER COLUMN warehouse_item_id DROP NOT NULL"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # 1. Load component specs
        print("=== LOADING COMPONENT SPECS ===")
        order = 1
        for comp_id, specs in COMP_SPECS.items():
            for key, val, unit in specs:
                db.session.execute(text("""
                    INSERT INTO component_specs (component_id, key_name, value_text, unit, order_index)
                    VALUES (:cid, :k, :v, :u, :o)
                """), {"cid": comp_id, "k": key, "v": val, "u": unit, "o": order})
                order += 1
        db.session.commit()
        print(f"  Loaded specs for {len(COMP_SPECS)} components")

        # 2. Load equipment specs for D2 (id=3)
        print("\n=== LOADING EQUIPMENT SPECS ===")
        for i, (key, val, unit) in enumerate(EQUIP_SPECS):
            db.session.execute(text("""
                INSERT INTO equipment_specs (equipment_id, key_name, value_text, unit, order_index)
                VALUES (:eid, :k, :v, :u, :o)
            """), {"eid": 3, "k": key, "v": val, "u": unit, "o": i + 1})
        db.session.commit()
        print(f"  Loaded {len(EQUIP_SPECS)} specs for DIGESTOR #2")

        # 3. Load BOM for rotative assets
        print("\n=== LOADING BOM ===")
        for asset_code, items in ASSET_BOM.items():
            asset = db.session.execute(text("SELECT id FROM rotative_assets WHERE code = :c"), {"c": asset_code}).fetchone()
            if not asset:
                print(f"  Asset {asset_code} not found, skipping")
                continue
            aid = asset[0]
            for ft, cat, qty, notes in items:
                db.session.execute(text("""
                    INSERT INTO rotative_asset_bom (asset_id, warehouse_item_id, free_text, category, quantity, notes)
                    VALUES (:aid, NULL, :ft, :cat, :qty, :notes)
                """), {"aid": aid, "ft": ft, "cat": cat, "qty": qty, "notes": notes})
            print(f"  {asset_code}: {len(items)} repuestos")
        db.session.commit()

        print("\n=== DONE ===")

        # Verify
        cs = db.session.execute(text("SELECT count(*) FROM component_specs")).scalar()
        es = db.session.execute(text("SELECT count(*) FROM equipment_specs")).scalar()
        bom = db.session.execute(text("SELECT count(*) FROM rotative_asset_bom")).scalar()
        print(f"  Component specs: {cs}")
        print(f"  Equipment specs: {es}")
        print(f"  BOM items: {bom}")

        db.session.remove()
    except Exception as e:
        db.session.rollback()
        db.session.remove()
        import traceback
        traceback.print_exc()
