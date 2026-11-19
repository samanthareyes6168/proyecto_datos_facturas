"""
Chaos Test.

Inyecta un lote con registros anómalos y eventos de stream retrasados o corruptos,
ejecuta el orquestador y reporta: tareas completadas, registros enviados a la DLQ,
valores imputados y filas en la capa Parquet antes y después.

Opciones: --sin-falla
"""

import argparse
import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta

import config
from pipeline.utilidades import obtener_logger

log = obtener_logger("chaos_test")


def titulo(texto):
    print("\n" + "=" * 78 + f"\n  {texto}\n" + "=" * 78)


def foto():
    if not config.ALMACEN_DB.exists():
        return {"facturas": 0, "dlq_max_id": 0, "parquet_hechos": None}
    con = sqlite3.connect(config.ALMACEN_DB)
    def uno(sql, defecto=0):
        try:
            return con.execute(sql).fetchone()[0] or defecto
        except sqlite3.OperationalError:
            return defecto
    datos = {"facturas": uno("SELECT COUNT(*) FROM facturas"), "dlq_max_id": uno("SELECT MAX(id) FROM dlq"),
             "pagos": uno("SELECT COUNT(*) FROM pagos"), "max_event": uno("SELECT max_event_time FROM control_stream", None)}
    con.close()
    manifiesto = config.PARQUET_DIR / "_manifiesto.json"
    datos["parquet_hechos"] = (json.loads(manifiesto.read_text(encoding="utf-8"))["tablas"]["hechos_ventas"]["filas"]
                               if manifiesto.exists() else None)
    return datos


def nombre_lote():
    hoy = "2026-11-14"
    n = 1
    while (config.ENTRADA_BATCH / f"{hoy}_chaos{n}").exists():
        n += 1
    return f"{hoy}_chaos{n}", n


def inyectar_batch(lote, n):
    carpeta = config.ENTRADA_BATCH / lote
    carpeta.mkdir(parents=True)
    p = f"CH{n}-"
    nuevo_id = 9000 + n * 10

    clientes = [
        {"id_cliente": f" {nuevo_id} ", "nombre": "Cliente Válido Sin Edad", "rfc": "VASE900101AB1", "edad": "",
         "ciudad": "Puebla", "estado": "Puebla"},                                                  # edad nula -> imputar
        {"id_cliente": str(nuevo_id + 1), "nombre": "Edad Negativa", "rfc": "NEGA900101AB1", "edad": "-5",
         "ciudad": "León", "estado": "Guanajuato"},
        {"id_cliente": str(nuevo_id + 2), "nombre": "Edad En Texto", "rfc": "TEXT900101AB1", "edad": "veinte",
         "ciudad": "León", "estado": "Guanajuato"},
        {"id_cliente": str(nuevo_id + 3), "nombre": "Menor De Edad", "rfc": "MENO100101AB1", "edad": "15",
         "ciudad": "Mérida", "estado": "Yucatán"},
        {"id_cliente": str(nuevo_id + 4), "nombre": "RFC Inválido", "rfc": "XXXX", "edad": "40",
         "ciudad": "Toluca", "estado": "Estado de México"},
    ]
    with open(carpeta / "clientes_altas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(clientes[0]))
        w.writeheader()
        w.writerows(clientes)

    def fac(folio, cliente="150", fecha="2026-11-14", detalle=None):
        return {"folio": folio, "fecha": fecha, "id_cliente": cliente, "id_usuario": 1,
                "detalle": detalle if detalle is not None else [{"id_producto": 3, "cantidad": 2, "precio_unitario": 1100.0}]}

    facturas = [
        fac(f"{p}0001"), fac(f"{p}0002", cliente="151.0"), fac(f"{p}0003", cliente=" 152 "),
        fac(f"{p}0004", cliente=f"{nuevo_id}"),                                                  # cliente dado de alta hoy
        fac(f"{p}0005", detalle=[{"id_producto": 1, "cantidad": 1, "precio_unitario": None}]),     # precio nulo -> imputar
        fac(f"{p}0006", detalle=[{"id_producto": 4, "cantidad": "dos", "precio_unitario": 420}]),  # tipo erróneo
        fac(f"{p}0007", detalle=[{"id_producto": 4, "cantidad": -3, "precio_unitario": 420}]),     # cantidad negativa
        fac(f"{p}0008", detalle=[{"id_producto": 4, "cantidad": 1, "precio_unitario": "abc"}]),    # precio texto
        fac(f"{p}0009", fecha="2027-05-01"),                                                     # fecha futura
        fac(f"{p}0010", cliente="77777"),                                                        # cliente inexistente
        fac("F-000001"),                                                                         # folio duplicado
        fac(f"{p}0011", detalle=[]),                                                             # sin productos
        fac(f"{p}0012", cliente="abc"),                                                          # id no numérico
    ]
    with open(carpeta / "facturas.json", "w", encoding="utf-8") as f:
        json.dump({"lote": lote, "generado_por": "chaos_test", "facturas": facturas}, f, ensure_ascii=False, indent=1)

    with open(carpeta / "facturas_sucursal.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["folio", "fecha", "id_cliente", "nombre_cliente", "productos"])
        w.writerow([f"{p}S01", "2026-11-14", "160", "x", "10:3:120.5|11:2:"])        # válido (2do precio nulo)
        w.writerow([f"{p}S02", "2026-11-14", "161", "x", "3:dos"])                   # celda mal formada
        w.writerow([f"{p}S03", "2026-11-14", "162", "x", "7:1:180|99:1:50"])         # producto inexistente
    return len(clientes), len(facturas) + 3


def inyectar_stream(max_event):
    base = datetime.fromisoformat(max_event) if max_event else datetime.fromisoformat("2026-11-14T10:30:00")
    eventos = []
    for i in range(1, 6):   # válidos y a tiempo
        t = base + timedelta(seconds=20 * i)
        eventos.append({"id_evento": f"CHAOS-OK-{base:%H%M%S}-{i}", "folio": "F-000010", "monto": 500.0 * i,
                        "metodo": "tarjeta", "event_time": t.isoformat(), "_llegada": (t + timedelta(seconds=1)).isoformat()})
    ultimo = base + timedelta(seconds=100)
    eventos += [
        {"id_evento": f"CHAOS-TARDE-OK-{base:%H%M%S}", "folio": "F-000011", "monto": 999.0, "metodo": "efectivo",
         "event_time": (ultimo - timedelta(seconds=60)).isoformat(), "_llegada": ultimo.isoformat()},     # dentro de tolerancia
        {"id_evento": f"CHAOS-TARDE-X-{base:%H%M%S}", "folio": "F-000012", "monto": 1500.0, "metodo": "efectivo",
         "event_time": (ultimo - timedelta(minutes=10)).isoformat(), "_llegada": ultimo.isoformat()},    # fuera de watermark
        {"id_evento": f"CHAOS-NEG-{base:%H%M%S}", "folio": "F-000013", "monto": -500.0, "metodo": "tarjeta",
         "event_time": ultimo.isoformat()},
        {"id_evento": f"CHAOS-TXT-{base:%H%M%S}", "folio": "F-000014", "monto": "N/A", "metodo": "tarjeta",
         "event_time": ultimo.isoformat()},
        {"id_evento": f"CHAOS-MET-{base:%H%M%S}", "folio": "F-000015", "monto": 300.0, "metodo": "bitcoin",
         "event_time": ultimo.isoformat()},
    ]
    with open(config.ENTRADA_STREAM, "a", encoding="utf-8") as f:
        for e in eventos:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        f.write('{"id_evento": "CHAOS-ROTO", "monto": 12\n')                                # JSON truncado
    return len(eventos) + 1


def main(con_falla=True):
    titulo("CHAOS TEST · Pipeline de facturas")
    antes = foto()
    print(f"Estado inicial: facturas={antes['facturas']}  |  pagos={antes.get('pagos', 0)}  |  "
          f"filas en Parquet (hechos_ventas)={antes['parquet_hechos']}")

    lote, n = nombre_lote()
    titulo(f"1) Inyectando caos en el lote {lote}")
    n_cli, n_fac = inyectar_batch(lote, n)
    n_ev = inyectar_stream(antes.get("max_event"))
    print(f"  {n_cli} altas de clientes, {n_fac} facturas y {n_ev} eventos de stream; la mayoría corruptos a propósito.")

    titulo("2) Corriendo el orquestador" + (" con FALLA DE RED simulada (Retry)" if con_falla else ""))
    if con_falla:
        os.environ["SIMULAR_FALLA_RED"] = "2"
    import orquestador
    estado = orquestador.ejecutar()
    os.environ.pop("SIMULAR_FALLA_RED", None)

    despues = foto()
    con = sqlite3.connect(config.ALMACEN_DB)
    nuevos_dlq = con.execute("SELECT capa, entidad, llave, motivos FROM dlq WHERE id > ? ORDER BY id",
                             (antes["dlq_max_id"],)).fetchall()
    imputados = con.execute("SELECT folio, linea, precio_final FROM int_detalle WHERE lote = ? AND precio_imputado = 1",
                            (lote,)).fetchall()
    edad = con.execute("SELECT id_cliente, edad FROM int_clientes WHERE edad_imputada = 1 AND id_cliente = ?",
                       (9000 + n * 10,)).fetchall()
    con.close()

    titulo("3) Resultado")
    print(f"  ¿El pipeline se detuvo? {'NO ✅, todas las tareas terminaron' if all(e == 'ok' for e in estado.values()) else 'Hubo tareas fallidas ⚠️'}")
    print(f"  Facturas nuevas aceptadas: {despues['facturas'] - antes['facturas']}")
    print(f"  Pagos nuevos aceptados:    {despues.get('pagos', 0) - antes.get('pagos', 0)}")
    print(f"  Registros enviados a la DLQ en esta corrida: {len(nuevos_dlq)}")
    for capa, entidad, llave, motivos in nuevos_dlq:
        print(f"     [{capa:9}] {entidad:8} {str(llave)[:24]:24} {motivos[:80]}")
    print(f"  Precios imputados con la mediana del producto: {len(imputados)}")
    for folio, linea, precio in imputados:
        print(f"     {folio} línea {linea} -> ${precio:,.2f}")
    for id_c, e in edad:
        print(f"  Edad imputada con la mediana: cliente {id_c} -> {e} años")
    print(f"  Capa Parquet (hechos_ventas): {antes['parquet_hechos']} -> {despues['parquet_hechos']} filas")
    print(f"\n  La DLQ completa para auditoría está en {config.DLQ_DIR / 'dlq_completa.csv'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin-falla", action="store_true")
    args = parser.parse_args()
    main(con_falla=not args.sin_falla)
