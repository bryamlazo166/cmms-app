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

print("=== SEARCHING FOR VARIATIONS ===\n")

# Check all equipment with "LINEA" or similar
cur.execute("SELECT id, name, tag FROM equipments WHERE name ILIKE '%LINEA%' ORDER BY name")
lineas = cur.fetchall()
print(f"Equipment with 'LINEA': {len(lineas)}")
for e in lineas:
  print(f"  - {e['name']} (Tag: {e['tag']})")

print("\n")

# Check MOLINO tags
cur.execute("SELECT id, name, tag FROM equipments WHERE tag LIKE '%MOLI%' ORDER BY name")
molinos = cur.fetchall()
print(f"Equipment with MOLI tags: {len(molinos)}")
for e in molinos:
  print(f"  - {e['name']} (Tag: {e['tag']})")

print("\n=== CHECK FAJA COMPONENT ===\n")

# Search for any FAJA component
cur.execute("SELECT c.id, c.name, s.id as sys_id, s.name as sys_name, eq.name as eq_name FROM components c JOIN systems s ON c.system_id = s.id JOIN equipments eq ON s.equipment_id = eq.id WHERE c.name ILIKE '%FAJA%'")
faja_comps = cur.fetchall()

if faja_comps:
  print(f"Found {len(faja_comps)} FAJA components:")
  for f in faja_comps:
    print(f"  - {f['name']} (ID: {f['id']})")
    print(f"    System: {f['sys_name']}")
    print(f"    Equipment: {f['eq_name']}\n")
else:
  print("No FAJA components found")

print("\n=== SAMPLE: MOLI2-LINE1 EQUIPMENT DETAILS ===\n")

# Get MOLI2-LINE1
cur.execute("SELECT id, name, tag FROM equipments WHERE tag = 'MOLI2-LINE1'")
eq = cur.fetchone()
if eq:
  eq_id = eq['id']
  print(f"Equipment: {eq['name']} (ID: {eq_id}, Tag: {eq['tag']})")
  
  # All systems and components
  cur.execute("""
    SELECT s.id, s.name, c.id as comp_id, c.name as comp_name, c.criticality
    FROM systems s
    LEFT JOIN components c ON s.id = c.system_id
    WHERE s.equipment_id = %s
    ORDER BY s.name, c.name
  """, (eq_id,))
  
  results = cur.fetchall()
  current_sys = None
  for r in results:
    if r['name'] != current_sys:
      current_sys = r['name']
      print(f"  System: {current_sys}")
    if r['comp_name']:
      print(f"    - {r['comp_name']} (Criticality: {r['criticality']})")

cur.close()
conn.close()
