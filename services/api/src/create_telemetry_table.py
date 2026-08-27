#!/usr/bin/env python3
"""Script temporal para crear telemetry_events en Supabase PostgreSQL."""
import psycopg2

with open('/workspaces/devleocusa-latam-aie-01-final-project/services/api/.env') as f:
    for line in f:
        if line.startswith('SQL_URL'):
            url = line.split('=')[1].strip().strip("\"'")

print('Conectando a Supabase PostgreSQL...')
conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()

# Leer y ejecutar el script SQL
with open('/workspaces/devleocusa-latam-aie-01-final-project/services/api/src/telemetry_events.sql') as f:
    sql = f.read()

cur.execute(sql)
print('✅ Tabla telemetry_events creada exitosamente en Supabase')

# Verificar
cur.execute("SELECT tablename FROM pg_tables WHERE tablename='telemetry_events'")
if cur.fetchone():
    print('✅ Verificación: tabla telemetry_events existe en Supabase')

    # Mostrar índices
    cur.execute("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename='telemetry_events'
    """)
    indices = cur.fetchall()
    print(f'✅ Índices creados ({len(indices)}):')
    for idx_name, idx_def in indices:
        print(f'   📍 {idx_name}: {idx_def[:100]}...')

    # Mostrar triggers
    cur.execute("""
        SELECT tgname
        FROM pg_trigger
        WHERE tgrelid = 'telemetry_events'::regclass
    """)
    triggers = cur.fetchall()
    for trig in triggers:
        print(f'   🔒 Trigger: {trig[0]}')

    # Mostrar políticas RLS
    cur.execute("""
        SELECT polname, polcmd
        FROM pg_policy
        WHERE polrelid = 'telemetry_events'::regclass
    """)
    policies = cur.fetchall()
    for pol in policies:
        print(f'   🛡️  RLS Policy: {pol[0]} ({pol[1]})')

cur.close()
conn.close()
print('\n🎉 Tabla lista en Supabase!')