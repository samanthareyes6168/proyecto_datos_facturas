import sqlite3

con = sqlite3.connect("data/almacen/almacen.db")

print("=== Facturas de la app ACEPTADAS ===")
for folio, id_texto, id_numero in con.execute(
        "SELECT folio, id_cliente_original, id_cliente FROM stg_facturas WHERE folio LIKE 'APP%'"):
    print(f"  {folio}: id llegó como texto {id_texto!r} -> se tradujo al número {id_numero}")

print("\n=== Facturas de la app en la DLQ ===")
for llave, motivos in con.execute("SELECT llave, motivos FROM dlq WHERE registro_original LIKE '%APP-%'"):
    print(f"  {llave}: {motivos}")