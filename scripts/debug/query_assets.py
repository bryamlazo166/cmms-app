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

print("\n=== 1. ROTATIVE ASSETS WITH STATUS='Instalado' ON 'BOMBA DE LODOS' ===\n")

# Find component BOMBA DE LODOS in area VAHOS
cur.execute("""
  SELECT c.id, c.name, s.id as system_id, s.name as system_name, eq.name as equipment_name
  FROM components c
  JOIN systems s ON c.system_id = s.id
  JOIN equipments eq ON s.equipment_id = eq.id
  JOIN lines l ON eq.line_id = l.id
  JOIN areas a ON l.area_id = a.id
  WHERE c.name ILIKE '%BOMBA DE LODOS%' AND a.name ILIKE '%VAHOS%'
""")
bomba_result = cur.fetchall()

if not bomba_result:
  print("No BOMBA DE LODOS found in VAHOS area")
  print("\nSearching for BOMBA DE LODOS anywhere...")
  cur.execute("SELECT id, name, system_id FROM components WHERE name ILIKE '%BOMBA DE LODOS%'")
  bomba_result = cur.fetchall()

if bomba_result:
  for comp in bomba_result:
    comp_id = comp['id']
    comp_name = comp['name']
    print(f"Found: {comp_name} (ID: {comp_id})")
    print(f"  System: {comp.get('system_name', 'N/A')}")
    print(f"  Equipment: {comp.get('equipment_name', 'N/A')}\n")
    
    # Count Instalado assets
    cur.execute("""
      SELECT COUNT(*) as cnt FROM rotative_assets 
      WHERE component_id = %s AND status = 'Instalado'
    """, (comp_id,))
    count = cur.fetchone()['cnt']
    print(f"  Instalado Assets: {count}")
    
    # List them
    cur.execute("""
      SELECT id, code, name, brand, model, serial_number, status, install_date
      FROM rotative_assets 
      WHERE component_id = %s AND status = 'Instalado'
      ORDER BY code
    """, (comp_id,))
    assets = cur.fetchall()
    
    for asset in assets:
      print(f"\n    Asset: {asset['code']} - {asset['name']}")
      print(f"      Brand: {asset['brand']}, Model: {asset['model']}")
      print(f"      Serial: {asset['serial_number']}")
      print(f"      Installed: {asset['install_date']}")
      
      # Specs
      cur.execute("""
        SELECT key_name, value_text, unit FROM rotative_asset_specs 
        WHERE asset_id = %s AND is_active = true
        ORDER BY order_index
      """, (asset['id'],))
      specs = cur.fetchall()
      if specs:
        print(f"      Specs:")
        for spec in specs:
          unit_str = f" {spec['unit']}" if spec['unit'] else ""
          print(f"        - {spec['key_name']}: {spec['value_text']}{unit_str}")
      
      # BOM
      cur.execute("""
        SELECT id, warehouse_item_id, free_text, category, quantity, notes
        FROM rotative_asset_bom 
        WHERE asset_id = %s
        ORDER BY category, id
      """, (asset['id'],))
      bom_items = cur.fetchall()
      if bom_items:
        print(f"      BOM (Spare Parts):")
        for item in bom_items:
          item_text = None
          if item['warehouse_item_id']:
            cur.execute("SELECT code, name FROM warehouse_items WHERE id = %s", (item['warehouse_item_id'],))
            wi = cur.fetchone()
            if wi:
              item_text = f"{wi['code']} - {wi['name']}"
          else:
            item_text = item['free_text']
          
          qty = item['quantity']
          cat = item['category']
          notes = f" ({item['notes']})" if item['notes'] else ""
          print(f"        - [{cat}] {qty}x {item_text}{notes}")

else:
  print("BOMBA DE LODOS not found in database")

print("\n\n=== 2. COMPONENT 'FAJA' IN EQUIPMENT 'LINEA MOLINO #2' ===\n")

# Search LINEA MOLINO #2
cur.execute("SELECT id, name, tag, line_id FROM equipments WHERE name ILIKE '%LINEA MOLINO%2%'")
linea_molino = cur.fetchall()

if linea_molino:
  for eq in linea_molino:
    eq_id = eq['id']
    eq_name = eq['name']
    print(f"Found Equipment: {eq_name} (Tag: {eq['tag']})")
    
    # Get all systems and components
    cur.execute("""
      SELECT DISTINCT s.id, s.name, c.id as comp_id, c.name as comp_name
      FROM systems s
      LEFT JOIN components c ON s.id = c.system_id
      WHERE s.equipment_id = %s
      ORDER BY s.name, c.name
    """, (eq_id,))
    comps = cur.fetchall()
    
    print(f"  Systems and Components:")
    current_system = None
    for c in comps:
      if c['name'] != current_system:
        print(f"    System: {c['name']}")
        current_system = c['name']
      if c['comp_name']:
        faja_marker = " <<<< FAJA FOUND!" if 'FAJA' in c['comp_name'].upper() else ""
        print(f"      - {c['comp_name']}{faja_marker}")
    
    # Specific search for FAJA
    cur.execute("""
      SELECT c.id, c.name FROM components c
      JOIN systems s ON c.system_id = s.id
      WHERE s.equipment_id = %s AND c.name ILIKE '%FAJA%'
    """, (eq_id,))
    faja_result = cur.fetchone()
    
    if faja_result:
      print(f"\n  FAJA Component EXISTS: {faja_result['name']} (ID: {faja_result['id']})")
    else:
      print(f"\n  FAJA Component NOT FOUND in {eq_name}")

else:
  print("LINEA MOLINO #2 not found")
  print("Available equipment with MOLINO:")
  cur.execute("SELECT id, name, tag FROM equipments WHERE name ILIKE '%MOLINO%' ORDER BY name")
  for eq in cur.fetchall():
    print(f"  - {eq['name']} (Tag: {eq['tag']})")

cur.close()
conn.close()
