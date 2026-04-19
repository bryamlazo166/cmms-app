"""Extrae imagenes de referencia desde el PDF de registro de espesores."""
from pathlib import Path
import pypdfium2 as pdfium
from PIL import Image

PDF = Path(r"D:\PROGRAMACION\REGISTRO DE ESPESORES-TRIPODE.pdf")
OUT = Path(r"D:\PROGRAMACION\CMMS_Industrial\static\images\thickness")
OUT.mkdir(parents=True, exist_ok=True)

SCALE = 3.0  # ~216 dpi

pdf = pdfium.PdfDocument(str(PDF))
pages = [pdf[i].render(scale=SCALE).to_pil() for i in range(len(pdf))]
for i, p in enumerate(pages):
    print(f"Pagina {i+1}: {p.size}")

# Pagina 1: tripode + tablas. Recortamos solo el dibujo del tripode.
p1 = pages[0]
W1, H1 = p1.size
# Dibujo del tripode, excluyendo encabezado FECHA/DIGESTOR y tabla derecha
tripode_box = (int(W1 * 0.02), int(H1 * 0.10), int(W1 * 0.50), int(H1 * 0.58))
tripode = p1.crop(tripode_box)
tripode.save(OUT / "tripode.png", optimize=True)
# El PDF no tiene dibujo separado de chaqueta; reutilizamos el tripode
# (la chaqueta es la carcasa que envuelve el tripode, misma geometria 1..5)
tripode.save(OUT / "chaqueta.png", optimize=True)

# Pagina 2: tapas (DESCARGA/TRANSMICION)
p2 = pages[1]
W2, H2 = p2.size

# Tapa conducida (DESCARGA) — circulo izquierdo inferior
conducida_box = (int(W2 * 0.06), int(H2 * 0.46), int(W2 * 0.28), int(H2 * 0.96))
p2.crop(conducida_box).save(OUT / "tapa_conducida.png", optimize=True)

# Tapa motriz (TRANSMICION) — circulo central inferior
motriz_box = (int(W2 * 0.28), int(H2 * 0.46), int(W2 * 0.52), int(H2 * 0.96))
p2.crop(motriz_box).save(OUT / "tapa_motriz.png", optimize=True)

print("\nArchivos generados en", OUT)
for f in sorted(OUT.glob("*.png")):
    print(f"  {f.name}: {f.stat().st_size // 1024} KB")
