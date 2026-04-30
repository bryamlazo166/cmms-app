#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()
DB_URL = os.getenv('DATABASE_URL')

conn = psycopg2.connect(DB_URL)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("\n" + "="*70)
print("ROTATIVE ASSETS & BOM LINKAGE - FINAL SUMMARY")
print("="*70 + "\n")

print("1. BOMBA DE LODOS - ROTATIVE ASSETS STATUS\n")
print("-" * 70)

cur.execute("""
  SELECT c.id, c.name FROM components c
  WHERE c.name ILIKE '%BOMBA DE LODOS%'
""")
bomba = cur.fetchone()

if bomba:
  comp_id = bomba['id']
  
  cur.execute("""
    SELECT status, COUNT(*) as cnt FROM rotative_assets 
    WHERE component_id = %s GROUP BY status ORDER BY cnt DESC
  """, (comp_id,))
  status_counts = cur.fetchall()
  print(f"Component: {bomba['name']} (ID: {comp_id})")
  for s in status_counts:
    print(f"  {s['status']:15}: {s['cnt']} asset(s)")
  
  print()
  
  # Installed assets with BOM
  cur.execute("""
    SELECT id, code, name FROM rotative_assets 
    WHERE component_id = %s AND status = 'Instalado'
  """, (comp_id,))
  assets = cur.fetchall()
  
  print(f"Installed Assets ({len(assets)} total):")
  for asset in assets:
    print(f"\n  Code: {asset['code']}")
    print(f"  Name: {asset['name']}")
    
    cur.execute("""
      SELECT COUNT(*) as cnt FROM rotative_asset_bom 
      WHERE asset_id = %s
    """, (asset['id'],))
    bom_count = cur.fetchone()['cnt']
    print(f"  BOM Items: {bom_count}")
    
    if bom_count > 0:
      cur.execute("""
        SELECT rab.category, rab.quantity, rab.free_text,
               wi.code as item_code, wi.name as item_name
        FROM rotative_asset_bom rab
        LEFT JOIN warehouse_items wi ON rab.warehouse_item_id = wi.id
        WHERE rab.asset_id = %s
        ORDER BY rab.category
      """, (asset['id'],))
      for item in cur.fetchall():
        item_name = f"{item['item_code']} - {item['item_name']}" if item['item_code'] else item['free_text']
        qty = int(item['quantity']) if item['quantity'] == int(item['quantity']) else item['quantity']
        print(f"    [{item['category']}] {qty}x {item_name}")

print("\n" + "="*70)
print("2. MOLINO - LINEA MOLINO #2 COMPONENTS\n")
print("-" * 70)

cur.execute("SELECT id, name, tag FROM equipments WHERE tag = 'MOLI2-LINE1'")
eq = cur.fetchone()

if eq:
  eq_id = eq['id']
  eq_name = eq['name']
  print(f"Equipment: {eq_name} (Tag: {eq['tag']})")
  
  # Count systems and components
  cur.execute("""
    SELECT COUNT(DISTINCT id) as cnt FROM systems WHERE equipment_id = %s
  """, (eq_id,))
  sys_count = cur.fetchone()['cnt']
  
  cur.execute("""
    SELECT COUNT(c.id) as cnt
    FROM components c
    JOIN systems s ON c.system_id = s.id
    WHERE s.equipment_id = %s
  """, (eq_id,))
  comp_count = cur.fetchone()['cnt']
  
  print(f"Total Systems: {sys_count}")
  print(f"Total Components: {comp_count}")
  
  # Check for FAJA
  cur.execute("""
    SELECT c.id, c.name
    FROM components c
    JOIN systems s ON c.system_id = s.id
    WHERE s.equipment_id = %s AND UPPER(c.name) = 'FAJA'
  """, (eq_id,))
  faja = cur.fetchone()
  
  if faja:
    print(f"\nFAJA Component: YES (ID: {faja['id']}, Name: {faja['name']})")
  else:
    print(f"\nFAJA Component: NOT FOUND")
    print("  (Equipment 'LINEA MOLINO #2' does not contain a 'FAJA' component)")
    print("  Note: Equipment exists as 'MOLINO' with tag 'MOLI2-LINE1'")

print("\n" + "="*70)
print("\nMODEL RELATIONSHIPS:")
print("  Component ---[component_id]--> RotativeAsset")
print("                                       |")
print("                                  RotativeAssetSpec (specs)")
print("                                  RotativeAssetBOM (BOM)")
print("                                       |")
print("                                  WarehouseItem")
print("="*70 + "\n")

cur.close()
conn.close()
