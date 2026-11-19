"""
Transformación en el almacén: modelo 3FN y capa de consumo.

  - Traducción de llaves id_cliente (texto -> entero) y registro de la comparación de joins.
  - Core 3FN: dim_ciudad, dim_cliente, dim_producto, dim_usuario, facturas, detalle_factura, pagos.
  - Consumo: hechos_ventas, mart_ventas_mensuales, mart_ventas_cliente, mart_ventas_producto.
"""

import pandas as pd

from pipeline.utilidades import conectar_almacen, obtener_logger, traducir_llave

log = obtener_logger("p5_modelado")

DDL_CORE = """
DROP TABLE IF EXISTS pagos; DROP TABLE IF EXISTS detalle_factura; DROP TABLE IF EXISTS facturas;
DROP TABLE IF EXISTS dim_cliente; DROP TABLE IF EXISTS dim_ciudad; DROP TABLE IF EXISTS dim_producto;
DROP TABLE IF EXISTS dim_usuario;

CREATE TABLE dim_ciudad (
    id_ciudad INTEGER PRIMARY KEY, ciudad TEXT NOT NULL, estado TEXT NOT NULL, UNIQUE (ciudad, estado));
CREATE TABLE dim_cliente (
    id_cliente INTEGER PRIMARY KEY, nombre TEXT NOT NULL, rfc TEXT NOT NULL, edad INTEGER NOT NULL,
    edad_imputada INTEGER NOT NULL, id_ciudad INTEGER NOT NULL REFERENCES dim_ciudad(id_ciudad), origen TEXT);
CREATE TABLE dim_producto (
    id_producto INTEGER PRIMARY KEY, nombre TEXT NOT NULL, categoria TEXT NOT NULL, precio_lista REAL NOT NULL);
CREATE TABLE dim_usuario (id_usuario INTEGER PRIMARY KEY, usuario TEXT NOT NULL);
CREATE TABLE facturas (
    folio TEXT PRIMARY KEY, fecha TEXT NOT NULL,
    id_cliente INTEGER NOT NULL REFERENCES dim_cliente(id_cliente),
    id_usuario INTEGER REFERENCES dim_usuario(id_usuario), origen TEXT NOT NULL, lote TEXT NOT NULL);
CREATE TABLE detalle_factura (
    folio TEXT NOT NULL REFERENCES facturas(folio), linea INTEGER NOT NULL,
    id_producto INTEGER NOT NULL REFERENCES dim_producto(id_producto),
    cantidad INTEGER NOT NULL CHECK (cantidad > 0), precio_unitario REAL NOT NULL CHECK (precio_unitario > 0),
    precio_imputado INTEGER NOT NULL, es_outlier INTEGER NOT NULL, PRIMARY KEY (folio, linea));
CREATE TABLE pagos (
    id_evento TEXT PRIMARY KEY, folio TEXT NOT NULL, monto REAL NOT NULL CHECK (monto > 0), metodo TEXT NOT NULL,
    event_time TEXT NOT NULL, llegada TEXT, retraso_seg REAL);
"""

SQL_MARTS = """
DROP TABLE IF EXISTS hechos_ventas;
CREATE TABLE hechos_ventas AS
SELECT d.folio, d.linea, f.fecha, CAST(substr(f.fecha, 1, 4) AS INTEGER) AS anio,
       CAST(substr(f.fecha, 6, 2) AS INTEGER) AS mes, f.origen,
       c.id_cliente, c.nombre AS cliente, ci.ciudad, ci.estado,
       p.id_producto, p.nombre AS producto, p.categoria,
       d.cantidad, d.precio_unitario, ROUND(d.cantidad * d.precio_unitario, 2) AS importe,
       d.precio_imputado, d.es_outlier
FROM detalle_factura d
JOIN facturas f      ON f.folio = d.folio
JOIN dim_cliente c   ON c.id_cliente = f.id_cliente
JOIN dim_ciudad ci   ON ci.id_ciudad = c.id_ciudad
JOIN dim_producto p  ON p.id_producto = d.id_producto;

DROP TABLE IF EXISTS mart_ventas_mensuales;
CREATE TABLE mart_ventas_mensuales AS
SELECT printf('%04d-%02d', anio, mes) AS anio_mes, COUNT(DISTINCT folio) AS num_facturas,
       COUNT(DISTINCT id_cliente) AS num_clientes, ROUND(SUM(importe), 2) AS ventas_totales,
       ROUND(SUM(importe) / COUNT(DISTINCT folio), 2) AS ticket_promedio
FROM hechos_ventas GROUP BY anio, mes ORDER BY anio, mes;

DROP TABLE IF EXISTS mart_ventas_cliente;
CREATE TABLE mart_ventas_cliente AS
SELECT id_cliente, cliente, ciudad, estado, COUNT(DISTINCT folio) AS num_facturas,
       ROUND(SUM(importe), 2) AS ventas_totales
FROM hechos_ventas GROUP BY id_cliente ORDER BY ventas_totales DESC;

DROP TABLE IF EXISTS mart_ventas_producto;
CREATE TABLE mart_ventas_producto AS
SELECT id_producto, producto, categoria, SUM(cantidad) AS unidades, ROUND(SUM(importe), 2) AS ventas_totales,
       SUM(precio_imputado) AS lineas_con_precio_imputado, SUM(es_outlier) AS lineas_outlier
FROM hechos_ventas GROUP BY id_producto ORDER BY ventas_totales DESC;

-- Vista: el total de la factura se CALCULA, no se guarda (evita datos derivados en 3FN)
DROP VIEW IF EXISTS v_total_factura;
CREATE VIEW v_total_factura AS
SELECT folio, ROUND(SUM(cantidad * precio_unitario), 2) AS total FROM detalle_factura GROUP BY folio;
"""


def demostrar_join_roto(con):
    """Compara tres estrategias de join sobre id_cliente y registra el resultado en el log."""
    facturas = pd.read_sql("SELECT folio, id_cliente_original FROM stg_facturas", con)
    clientes = pd.read_sql("SELECT id_cliente, nombre FROM int_clientes", con)
    clientes["id_cliente"] = clientes["id_cliente"].astype("int64")
    facturas["id_cliente_original"] = facturas["id_cliente_original"].astype(object)

    # Intento 1: unir texto contra entero
    try:
        r = facturas.merge(clientes, left_on="id_cliente_original", right_on="id_cliente")
        intento1 = f"{len(r)} coincidencias"
    except ValueError as e:
        intento1 = f"ERROR -> {str(e).splitlines()[0][:90]}"

    # Intento 2: convertir el entero a texto (la "solución ingenua")
    c2 = clientes.assign(id_txt=clientes["id_cliente"].astype(str))
    r2 = facturas.merge(c2, left_on="id_cliente_original", right_on="id_txt")

    # Intento 3: traducción de tipos correcta
    f3 = facturas.assign(id_cliente=facturas["id_cliente_original"].map(traducir_llave).astype("int64"))
    r3 = f3.merge(clientes, on="id_cliente")

    total = len(facturas)
    perdidas = facturas[~facturas["id_cliente_original"].isin(c2["id_txt"])]["id_cliente_original"]
    log.info("RETO DEL JOIN ROTO (facturas.id_cliente TEXTO vs dim_cliente.id_cliente ENTERO):")
    log.info(f"    1) Join directo texto vs entero ............ {intento1}")
    log.info(f"    2) Convertir el entero a texto ............. {len(r2)}/{total} ({len(r2) / total:.1%}) "
             f"-> se pierden ids como {sorted(set(perdidas))[:3]}")
    log.info(f"    3) Traducción con traducir_llave() ......... {len(r3)}/{total} ({len(r3) / total:.1%})")
    return {"directo": intento1, "texto": len(r2), "traducido": len(r3), "total": total}


def modelar():
    con = conectar_almacen()
    demo = demostrar_join_roto(con)
    con.executescript(DDL_CORE)

    # ---- dim_ciudad y dim_cliente (3FN) ----
    clientes = pd.read_sql("SELECT * FROM int_clientes", con)
    ciudades = clientes[["ciudad", "estado"]].drop_duplicates().sort_values(["estado", "ciudad"]).reset_index(drop=True)
    ciudades.insert(0, "id_ciudad", range(1, len(ciudades) + 1))
    ciudades.to_sql("dim_ciudad", con, if_exists="append", index=False)
    clientes = clientes.merge(ciudades, on=["ciudad", "estado"])
    clientes[["id_cliente", "nombre", "rfc", "edad", "edad_imputada", "id_ciudad", "origen"]] \
        .to_sql("dim_cliente", con, if_exists="append", index=False)

    # ---- dim_producto y dim_usuario ----
    con.execute("INSERT INTO dim_producto SELECT CAST(id_producto AS INTEGER), nombre, categoria, "
                "CAST(precio_lista AS REAL) FROM raw_productos")
    con.execute("INSERT INTO dim_usuario SELECT CAST(id_usuario AS INTEGER), usuario FROM raw_usuarios")

    # ---- hechos normalizados ----
    con.execute("INSERT INTO facturas SELECT folio, fecha, id_cliente, id_usuario, origen, lote FROM stg_facturas")
    con.execute("INSERT INTO detalle_factura SELECT folio, linea, id_producto, cantidad, ROUND(precio_final, 2), "
                "precio_imputado, es_outlier FROM int_detalle")
    con.execute("INSERT INTO pagos SELECT id_evento, folio, monto, metodo, event_time, llegada, retraso_seg "
                "FROM stg_pagos" if con.execute("SELECT name FROM sqlite_master WHERE name='stg_pagos'").fetchone()
                else "SELECT 1 WHERE 0")

    con.executescript(SQL_MARTS)
    con.commit()
    conteos = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
               for t in ["dim_ciudad", "dim_cliente", "dim_producto", "facturas", "detalle_factura", "pagos",
                         "hechos_ventas", "mart_ventas_mensuales"]}
    con.close()
    log.info("Modelo 3FN + marts: " + ", ".join(f"{k}={v}" for k, v in conteos.items()))
    return {"join": demo, "conteos": conteos}


if __name__ == "__main__":
    modelar()
