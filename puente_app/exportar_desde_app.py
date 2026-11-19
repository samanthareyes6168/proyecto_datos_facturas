"""
Exportación de facturas del Gestor de Facturas al formato de lote del pipeline.

Lee facturas.db de la app, resuelve cliente y producto contra el catálogo relacional
(sin distinguir mayúsculas ni acentos) y escribe data/entrada/batch/<fecha>_app/facturas.json.
Los nombres no encontrados se conservan como texto y son rechazados en la validación.

Ejecución: python puente_app/exportar_desde_app.py --app-db <ruta facturas.db> [--fecha AAAA-MM-DD]
"""

import argparse
import json
import sqlite3
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.lower().split())


def exportar(ruta_app_db, fecha):
    app = sqlite3.connect(ruta_app_db)
    fuente = sqlite3.connect(config.FUENTE_DB)
    clientes = {normalizar(n): i for i, n in fuente.execute("SELECT id_cliente, nombre FROM clientes")}
    productos = {normalizar(n): i for i, n in fuente.execute("SELECT id_producto, nombre FROM productos")}
    fuente.close()

    facturas, sin_cliente, sin_producto = [], 0, 0
    for id_factura, folio, cliente, fecha_f, id_usuario in app.execute(
            "SELECT id, folio, cliente, fecha, id_usuario FROM facturas WHERE fecha = ?", (fecha,)):
        id_cliente = clientes.get(normalizar(cliente))
        sin_cliente += id_cliente is None
        detalle = []
        for producto, cantidad, precio in app.execute(
                "SELECT producto, cantidad, precio_unitario FROM detalle_factura WHERE id_factura = ?", (id_factura,)):
            id_producto = productos.get(normalizar(producto))
            sin_producto += id_producto is None
            detalle.append({"id_producto": id_producto if id_producto is not None else producto,
                            "cantidad": cantidad, "precio_unitario": precio})
        facturas.append({"folio": folio, "fecha": fecha_f,
                         # El id se exporta como texto, igual que lo captura la interfaz
                         "id_cliente": str(id_cliente) if id_cliente is not None else cliente,
                         "id_usuario": id_usuario, "detalle": detalle})
    app.close()

    carpeta = config.ENTRADA_BATCH / f"{fecha}_app"
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / "facturas.json", "w", encoding="utf-8") as f:
        json.dump({"lote": carpeta.name, "generado_por": "gestor_facturas (app real)", "facturas": facturas},
                  f, ensure_ascii=False, indent=1)
    print(f"Exportadas {len(facturas)} facturas del {fecha} a {carpeta / 'facturas.json'}")
    print(f"  Clientes no encontrados en el catálogo: {sin_cliente} | productos no encontrados: {sin_producto}")
    print("  (esas facturas irán a la DLQ cuando corra el pipeline)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-db", default="app_gestor_facturas/facturas.db")
    parser.add_argument("--fecha", default=date.today().isoformat())
    args = parser.parse_args()
    exportar(args.app_db, args.fecha)
