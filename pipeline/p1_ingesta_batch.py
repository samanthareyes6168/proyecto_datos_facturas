"""
Ingesta batch (ELT: extracción y carga).

Copia los datos sin transformar a tablas raw_* del almacén:
  - extraer_maestros(): snapshot de clientes, productos y usuarios de la base de la app.
  - ingestar_lotes(): carga cada lote diario pendiente; control_lotes evita duplicados.
"""

import csv
import json
import os
import sqlite3
from datetime import datetime

import config
from pipeline.utilidades import conectar_almacen, enviar_a_dlq, obtener_logger

log = obtener_logger("p1_batch")

_intentos_conexion = {"n": 0}


def extraer_maestros():
    """Copia las tablas maestras de la base relacional de la app al almacén (capa raw)."""
    # SIMULAR_FALLA_RED=N hace fallar los primeros N intentos (prueba de la política de reintentos).
    fallas = int(os.environ.get("SIMULAR_FALLA_RED", "0"))
    _intentos_conexion["n"] += 1
    if _intentos_conexion["n"] <= fallas:
        raise ConnectionError(f"No se pudo conectar a la base de la app (intento {_intentos_conexion['n']})")

    origen = sqlite3.connect(config.FUENTE_DB.as_uri() + "?mode=ro", uri=True)  # solo lectura
    con = conectar_almacen()
    for tabla_origen, tabla_raw, columnas in [
        ("clientes", "raw_clientes_maestro", "id_cliente, nombre, rfc, edad, ciudad, estado"),
        ("productos", "raw_productos", "id_producto, nombre, categoria, precio_lista"),
        # Gobernanza: la columna password NUNCA se copia al almacén analítico
        ("usuarios", "raw_usuarios", "id AS id_usuario, usuario"),
    ]:
        filas = origen.execute(f"SELECT {columnas} FROM {tabla_origen}").fetchall()
        nombres = [c.strip().split(" AS ")[-1] for c in columnas.split(",")]
        con.execute(f"DROP TABLE IF EXISTS {tabla_raw}")
        con.execute(f"CREATE TABLE {tabla_raw} ({', '.join(nombres)}, _extraido_en TEXT)")
        ahora = datetime.now().isoformat(timespec="seconds")
        con.executemany(f"INSERT INTO {tabla_raw} VALUES ({', '.join('?' * (len(nombres) + 1))})",
                        [tuple(f) + (ahora,) for f in filas])
        log.info(f"Maestro {tabla_origen} -> {tabla_raw}: {len(filas)} filas")
    con.commit()
    con.close()
    origen.close()


def crear_tablas_raw(con):
    # Todo es TEXT: en la capa raw no se interpreta nada, se guarda exactamente lo que llegó.
    con.executescript("""
        CREATE TABLE IF NOT EXISTS raw_facturas_json (
            lote TEXT, posicion INTEGER, documento TEXT, _cargado_en TEXT);
        CREATE TABLE IF NOT EXISTS raw_facturas_csv (
            lote TEXT, fila INTEGER, folio TEXT, fecha TEXT, id_cliente TEXT,
            nombre_cliente TEXT, productos TEXT, _cargado_en TEXT);
        CREATE TABLE IF NOT EXISTS raw_clientes_altas (
            lote TEXT, fila INTEGER, id_cliente TEXT, nombre TEXT, rfc TEXT, edad TEXT,
            ciudad TEXT, estado TEXT, _cargado_en TEXT);
    """)


def cargar_lote(con, carpeta):
    lote = carpeta.name
    ahora = datetime.now().isoformat(timespec="seconds")
    total = 0

    # ---- JSON jerárquico de la app ----
    ruta_json = carpeta / "facturas.json"
    if ruta_json.exists():
        try:
            with open(ruta_json, encoding="utf-8") as f:
                contenido = json.load(f)
            facturas = contenido["facturas"] if isinstance(contenido, dict) else contenido
            con.executemany("INSERT INTO raw_facturas_json VALUES (?, ?, ?, ?)",
                            [(lote, i, json.dumps(fac, ensure_ascii=False), ahora) for i, fac in enumerate(facturas)])
            total += len(facturas)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # Un archivo entero ilegible NO detiene el pipeline: va completo a la DLQ
            enviar_a_dlq(con, lote, "facturas.json", "archivo", ruta_json.name, "formato",
                         f"JSON ilegible: {e}", ruta_json.read_text(encoding="utf-8", errors="replace")[:5000])
            log.warning(f"[{lote}] facturas.json ilegible -> DLQ")

    # ---- CSV plano de la sucursal ----
    ruta_csv = carpeta / "facturas_sucursal.csv"
    if ruta_csv.exists():
        with open(ruta_csv, newline="", encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        con.executemany("INSERT INTO raw_facturas_csv VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [(lote, i, r.get("folio"), r.get("fecha"), r.get("id_cliente"), r.get("nombre_cliente"),
                          r.get("productos"), ahora) for i, r in enumerate(filas)])
        total += len(filas)

    # ---- CSV de altas de clientes ----
    ruta_cli = carpeta / "clientes_altas.csv"
    if ruta_cli.exists():
        with open(ruta_cli, newline="", encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        con.executemany("INSERT INTO raw_clientes_altas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(lote, i, r.get("id_cliente"), r.get("nombre"), r.get("rfc"), r.get("edad"),
                          r.get("ciudad"), r.get("estado"), ahora) for i, r in enumerate(filas)])
        total += len(filas)

    con.execute("INSERT INTO control_lotes (lote, estado, fecha_carga, registros_crudos) VALUES (?, 'cargado', ?, ?)",
                (lote, ahora, total))
    return total


def ingestar_lotes():
    con = conectar_almacen()
    crear_tablas_raw(con)
    ya_cargados = {r[0] for r in con.execute("SELECT lote FROM control_lotes")}
    carpetas = sorted(p for p in config.ENTRADA_BATCH.iterdir() if p.is_dir())
    nuevos = [c for c in carpetas if c.name not in ya_cargados]

    total = 0
    for carpeta in nuevos:
        total += cargar_lote(con, carpeta)
        con.commit()
    con.close()
    log.info(f"Lotes nuevos cargados: {len(nuevos)} (ya existían {len(ya_cargados)}) | registros crudos: {total}")
    return len(nuevos)


if __name__ == "__main__":
    extraer_maestros()
    ingestar_lotes()
