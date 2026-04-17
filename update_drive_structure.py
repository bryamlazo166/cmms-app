"""Crea/actualiza la estructura de carpetas en CMMS_DRIVE_STRUCTURE
para reflejar la taxonomia actual del CMMS, incluyendo nuevos componentes
(HIDROLAVADORA, BOMBA DE LODOS, BOMBA TORRE DE ENFRIAMIENTO).

Idempotente: solo crea carpetas que no existen.
"""
import os
from pathlib import Path

ROOT = Path(r"D:\PROGRAMACION\CMMS_Industrial\CMMS_DRIVE_STRUCTURE")

# Estructura completa: area -> {linea -> [(equipo, tag)]}
TAXONOMY = {
    "CALDERAS": {
        "CALDERA 400 BHP": [],
        "CALDERA 900 BHP": [],
        "MANIFOLD DE VAPOR": [],
        "OSMOSIS": [],
    },
    "COCCION": {
        **{
            f"LINEA DIGESTOR #{n}": [
                (f"DIGESTOR #{n}", f"D{n}"),
                (f"TH{n}", f"TH{n}"),
            ]
            for n in range(1, 10)
        },
        "HIDROLAVADORAS": [],
        "LINEA PERCOLADOR": [
            ("PERCOLADOR #1", "PER1"),
            ("PERCOLADOR #2", "PER2"),
        ],
    },
    "LINEA DE POLLO": {},
    "MOLINO": {
        "CICLON DE ENSAQUE": [],
        "CICLON DE LLEGADA": [],
        "FAJA TRANSPORTADORA": [],
        "LINEA MOLINO #1": [],
        "LINEA MOLINO #2": [],
        "LINEA ZARANDA": [],
    },
    "RMP": {
        "HIDROLAVADORAS": [
            ("HIDROLAVADORA #1", "H1"),
            ("HIDROLAVADORA #2", "H2"),
            ("HIDROLAVADORA #3", "H3"),
            ("HIDROLAVADORA #4", "H4"),
        ],
    },
    "SECADO": {
        "ENFRIADOR": [],
        "LANZAHARINA": [],
        "PURIFICADOR": [],
        "SECADOR #1": [],
        "SECADOR #2": [],
    },
    "SUBESTACION ELECTRICA": {},
    "TRITURADO": {
        "HIDROLAVADORA": [
            ("HIDROLAVADORA #5", "H5"),
        ],
        "TRITURADOR GRANDE": [
            ("TH ALIMENTADOR", "THALI"),
            ("TH SALIDA", "THSAL"),
            ("TH SILO", "THSI"),
            ("TRITURADOR 100 HP", "TRI1"),
        ],
        "TRITURADOR PEQUENO": [
            ("TH SALIDA", "THSAL2"),
            ("TRITURADOR 75 HP", "TRI2"),
        ],
    },
    "UTILITIES": {},
    "VAHOS": {
        "HIDROLISIS": [],
        "VAHOS #1": [
            ("VAHOS", "VAHO1"),
        ],
        "VAHOS #2": [],
    },
}

# Carpetas tematicas que tambien deben replicar areas/equipos
AREA_BASED_FOLDERS = [
    "01. PLANOS",
    "04. INFORMES DE MANTENIMIENTO",  # tiene anos, no replicamos por equipo
    "05. INFORMES DE PROVEEDORES",
]

# Subcarpetas por tipo de equipo rotativo bajo MANUALES y FICHAS
ROTATIVE_TYPE_FOLDERS = {
    "02. MANUALES DE EQUIPOS": [
        "BOMBAS",
        "CAJAS REDUCTORAS",
        "HIDROLAVADORAS",
        "INSTRUMENTACION",
        "MOTORES ELECTRICOS",
        "MOTORREDUCTORES",
        "OTROS",
    ],
    "06. INFORMES DE BAJA DE EQUIPOS": [
        "BOMBAS",
        "HIDROLAVADORAS",
        "MOTORES",
        "MOTORREDUCTORES",
        "OTROS",
        "REDUCTORES",
    ],
}

# Subcarpetas dentro de BOMBAS (especificas)
BOMBAS_SUBFOLDERS = [
    "BOMBA DE LODOS",
    "BOMBA TORRE DE ENFRIAMIENTO",
    "BOMBAS CENTRIFUGAS",
    "OTROS",
]

created = []
skipped = []


def mkdir_safe(path: Path):
    if path.exists():
        skipped.append(str(path))
    else:
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path))


def main():
    # 1. Estructura de PLANOS por area > linea > equipo [tag]
    planos_root = ROOT / "01. PLANOS"
    for area, lines in TAXONOMY.items():
        area_dir = planos_root / area
        mkdir_safe(area_dir)
        for line, equipos in lines.items():
            line_dir = area_dir / line
            mkdir_safe(line_dir)
            for eq_name, tag in equipos:
                eq_folder = f"{eq_name} [{tag}]" if tag else eq_name
                mkdir_safe(line_dir / eq_folder)

    # 2. MANUALES y BAJA: tipos de equipo
    for parent_folder, types in ROTATIVE_TYPE_FOLDERS.items():
        parent_dir = ROOT / parent_folder
        mkdir_safe(parent_dir)
        for tname in types:
            mkdir_safe(parent_dir / tname)

    # 3. Subcarpetas dentro de BOMBAS
    bombas_dir = ROOT / "02. MANUALES DE EQUIPOS" / "BOMBAS"
    for sub in BOMBAS_SUBFOLDERS:
        mkdir_safe(bombas_dir / sub)

    bombas_baja_dir = ROOT / "06. INFORMES DE BAJA DE EQUIPOS" / "BOMBAS"
    for sub in BOMBAS_SUBFOLDERS:
        mkdir_safe(bombas_baja_dir / sub)

    print(f"Carpetas creadas: {len(created)}")
    for p in created:
        print(f"  + {p}")
    print(f"Carpetas existentes (omitidas): {len(skipped)}")


if __name__ == '__main__':
    main()
