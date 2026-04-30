#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv('DATABASE_URL')

conn = psycopg2.connect(DB_URL)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("\n" + "="*70)
print("ROTATIVE ASSETS & BOM LINKAGE SUMMARY")
print("="*70 + "\n")

print("1. BOMBA DE LODOS (VAHOS Area) - ROTATIVE ASSETS & BOM\n")
print("-" * 70)

cur.execute("""
  SELECT c.id, c.name FROM components c
  WHERE c.name ILIKE '%BOMBA DE LODOS%'
""")
bomba = cur.fetchone()

if bomba:
  comp_id = bomba['id']
  
  # Count by status
  cur.execute("""
    SELECT status, COUNT(*) as cnt FROM rotative_assets 
    WHERE component_id = %s GROUP BY status ORDER BY cnt DESC
  """, (comp_id,))
  status_counts = cur.fetchall()
  print(f"Component: {bomba['name']} (ID: {comp_id})")
  print(f"Status distribution:")
  for s in status_counts:
    print(f"  {s['status']:20} {s['cnt']:3} assets")
  
  print()
  
  # Installed assets detail
  cur.execute("""
    SELECT id, code, name, brand, model, status FROM rotative_assets 
    WHERE component_id = %s AND status = 'Instalado'
  """, (comp_id,))
  assets = cur.fetchall()
  
  print(f"Installed Assets Detail ({len(assets)} total):")
  for asset in assets:
    print(f"\n  Asset: {asset['code']} - {asset['name']}")
    
    # Get BOM
    cur.execute("""
      SELECT rab.id, rab.category, rab.quantity, rab.free_text, rab.notes,
             wi.code as item_code, wi.name as item_name
      FROM rotative_asset_bom rab
      LEFT JOIN warehouse_items wi ON rab.warehouse_item_id = wi.id
      WHERE rab.asset_id = %s
      ORDER BY rab.category, rab.id
    """, (asset['id'],))
    bom = cur.fetchall()
    
    if bom:
      print(f"    BOM Items: {len(bom)}")
      for item in bom:
        item_name = f"{item['item_code']} - {item['item_name']}" if item['item_code'] else item['free_text']
        qty = f"{item['quantity']:.1f}".rstrip('0').rstrip('.')
        notes = f" ({item['notes']})" if item['notes'] else ""
        print(f"      - [{item['category']:10}] {qty}x {item_name}{notes}")
    else:
      print(f"    BOM Items: None")

print("\n" + "="*70)
print("2. MOLINO EQUIPMENT - LINEA MOLINO #2 (FAJA COMPONENT EXISTENCE)\n")
print("-" * 70)

# MOLINO exists as "MOLINO" not "LINEA MOLINO"
cur.execute("SELECT id, name, tag FROM equipments WHERE tag = 'MOLI2-LINE1'")
eq = cur.fetchone()

if eq:
  print(f"Equipment: {eq['name']} (Tag: {eq['tag']})")
  print(f"Status: EXISTS")
  
  # Check for FAJA
  cur.execute("""
    SELECT c.id, c.name FROM components c
    JOIN systems s ON c.system_id = s.id
    WHERE s.equipment_id = %s AND c.name ILIKE '%FAJA%' AND c.name NOT LIKE '%GUARDA%'
  """, (eq['id'],))
  faja_comps = cur.fetchall()
  
  print(f"FAJA Component in MOLINO (MOLI2-LINE1):")
  if faja_comps:
    for f in faja_comps:
      print(f"  - {f['name']} (ID: {f['id']}) ✓ EXISTS")
  else:
    print(f"  No pure FAJA component found")
    
  # Get system count
  cur.execute("SELECT COUNT(DISTINCT id) as cnt FROM systems WHERE equipment_id = %s", (eq['id'],))
  sys_cnt = cur.fetchone()['cnt']
  
  # Get component count
  cur.execute("SELECT COUNT(*) as cnt FROM components WHERE system_id IN (SELECT id FROM systems WHERE equipment_id = %s)", (eq['id'],))
  comp_cnt = cur.fetchone()['cnt']
  
  print(f"Systems: {sys_cnt}, Components: {comp_cnt}")

else:
  print("Equipment 'LINEA MOLINO #2' NOT FOUND")
  print("Note: System has 'MOLINO' equipment (not 'LINEA MOLINO')")
  print("Available MOLINO variants:")
  cur.execute("SELECT id, name, tag FROM equipments WHERE name ILIKE '%MOLINO%' ORDER BY name")
  for e in cur.fetchall():
    print(f"  - {e['name']} (Tag: {e['tag']})")

print("\n" + "="*70)
print("\nMODEL STRUCTURE:\n")
print("  RotativeAsset (code, name, brand, model, category, component_id, status)")
print("    → RotativeAssetSpec (asset_id, key_name, value_text, unit)")
print("    → RotativeAssetBOM (asset_id, warehouse_item_id, category, quantity)")
print("                         └→ WarehouseItem (code, name, stock, unit)")
print("\n" + "="*70)

cur.close()
conn.close()
