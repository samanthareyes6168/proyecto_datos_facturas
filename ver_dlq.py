import sqlite3

con = sqlite3.connect("data/almacen/almacen.db")
print("=== Rechazos por capa ===")
for fila in con.execute("SELECT capa, entidad, COUNT(*) FROM dlq GROUP BY capa, entidad"):
    print(fila)
print("\n=== Últimos 10 rechazados ===")
for llave, motivos in con.execute("SELECT llave, motivos FROM dlq ORDER BY id DESC LIMIT 10"):
    print(f"{llave:24} -> {motivos[:70]}")