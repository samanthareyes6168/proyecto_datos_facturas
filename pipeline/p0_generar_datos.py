"""
Generación de datos de origen para pruebas.

Simula la operación del Gestor de Facturas con un porcentaje configurable de
registros corruptos (config.PORCENTAJE_CAOS):
  - data/fuente/gestor_facturas.db           base relacional (clientes, productos, usuarios)
  - data/entrada/batch/AAAA-MM-DD/           facturas.json, facturas_sucursal.csv, clientes_altas.csv
  - data/entrada/stream/eventos_pagos.jsonl  pagos en tiempo real, ordenados por hora de llegada

Ejecución: python -m pipeline.p0_generar_datos --reset
"""

import argparse
import csv
import json
import random
import shutil
import sqlite3
from datetime import date, datetime, timedelta

from pipeline.utilidades import asegurar_carpetas, obtener_logger, vaciar_carpeta
import config

log = obtener_logger("p0_generar")

NOMBRES = ["Ana", "Luis", "María", "José", "Sofía", "Carlos", "Fernanda", "Jorge", "Valeria", "Miguel",
           "Daniela", "Ricardo", "Paola", "Andrés", "Lucía", "Diego", "Camila", "Héctor", "Regina", "Raúl"]
APELLIDOS = ["García", "Hernández", "López", "Martínez", "González", "Pérez", "Rodríguez", "Sánchez",
             "Ramírez", "Flores", "Torres", "Morales", "Ortiz", "Castillo", "Reyes", "Jiménez"]
# Ciudad -> Estado: dependencia transitiva que se elimina en 3FN
CIUDADES = [("Ciudad de México", "CDMX"), ("Guadalajara", "Jalisco"), ("Zapopan", "Jalisco"),
            ("Monterrey", "Nuevo León"), ("San Pedro Garza García", "Nuevo León"), ("Puebla", "Puebla"),
            ("Querétaro", "Querétaro"), ("Mérida", "Yucatán"), ("Toluca", "Estado de México"),
            ("León", "Guanajuato")]
PRODUCTOS = [
    (1, "Laptop 14 pulgadas", "Cómputo", 14500.00), (2, "Monitor 24 pulgadas", "Cómputo", 3200.00),
    (3, "Teclado mecánico", "Accesorios", 1150.00), (4, "Mouse inalámbrico", "Accesorios", 420.00),
    (5, "Audífonos con micrófono", "Accesorios", 890.00), (6, "Disco SSD 1TB", "Cómputo", 1650.00),
    (7, "Memoria USB 64GB", "Accesorios", 180.00), (8, "Impresora láser", "Cómputo", 4300.00),
    (9, "Tóner para impresora", "Papelería", 1250.00), (10, "Paquete de hojas carta", "Papelería", 115.00),
    (11, "Cuaderno profesional", "Papelería", 65.00), (12, "Bolígrafos (caja 12)", "Papelería", 85.00),
    (13, "Silla ergonómica", "Mobiliario", 5200.00), (14, "Escritorio en L", "Mobiliario", 6800.00),
    (15, "Lámpara de escritorio", "Mobiliario", 640.00), (16, "Licencia antivirus anual", "Software", 750.00),
    (17, "Licencia ofimática anual", "Software", 1900.00), (18, "Soporte técnico (hora)", "Servicios", 450.00),
    (19, "Instalación de red", "Servicios", 2800.00), (20, "Mantenimiento preventivo", "Servicios", 950.00),
    (21, "Cable HDMI 2m", "Accesorios", 150.00), (22, "Webcam HD", "Accesorios", 980.00),
    (23, "Router WiFi 6", "Cómputo", 2100.00), (24, "No-break 1000VA", "Cómputo", 2450.00),
    (25, "Archivero metálico", "Mobiliario", 3900.00),
]
PRECIO_LISTA = {p[0]: p[3] for p in PRODUCTOS}
USUARIOS = [(1, "admin"), (2, "caja_centro"), (3, "caja_norte"), (4, "sucursal_sur")]

TIPOS_CAOS_FACTURA = ["cantidad_negativa", "cantidad_texto", "precio_texto", "precio_negativo",
                      "fecha_futura", "fecha_invalida", "folio_vacio", "cliente_inexistente",
                      "producto_inexistente", "duplicado", "detalle_vacio"]
TIPOS_CAOS_CLIENTE = ["edad_negativa", "edad_texto", "menor_de_edad", "rfc_invalido", "nombre_vacio"]


def generar_rfc(nombre, apellido, nacimiento):
    letras = (apellido[:2] + apellido[-1] + nombre[0]).upper()
    letras = letras.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
    homoclave = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(3))
    return letras + nacimiento.strftime("%y%m%d") + homoclave


def nuevo_cliente(id_cliente, fecha_ref):
    nombre, apellido = random.choice(NOMBRES), random.choice(APELLIDOS)
    edad = random.randint(18, 78)
    nacimiento = fecha_ref - timedelta(days=edad * 365 + random.randint(0, 300))
    ciudad, estado = random.choice(CIUDADES)
    return {"id_cliente": id_cliente, "nombre": f"{nombre} {apellido} {random.choice(APELLIDOS)}",
            "rfc": generar_rfc(nombre, apellido, nacimiento), "edad": edad, "ciudad": ciudad, "estado": estado}


def id_como_texto(id_cliente):
    # Variantes de texto con las que la app exporta el id
    r = random.random()
    if r < 0.75:
        return str(id_cliente)
    if r < 0.85:
        return f" {id_cliente} "
    if r < 0.95:
        return f"{id_cliente}.0"
    return f"0{id_cliente}"


def precio_con_variacion(id_producto):
    precio = PRECIO_LISTA[id_producto] * random.uniform(0.9, 1.1)
    r = random.random()
    if r < 0.03:
        return None                       # NULO -> se imputa
    if r < 0.045:
        return round(precio * 10, 2)      # OUTLIER: alguien capturó un cero de más
    return round(precio, 2)


def crear_fuente_relacional(clientes):
    if config.FUENTE_DB.exists():
        config.FUENTE_DB.unlink()
    con = sqlite3.connect(config.FUENTE_DB)
    con.executescript("""
        CREATE TABLE usuarios (id INTEGER PRIMARY KEY, usuario TEXT NOT NULL UNIQUE, password TEXT NOT NULL);
        -- Igual que en la app: ciudad y estado juntos (dependencia transitiva, NO está en 3FN)
        CREATE TABLE clientes (id_cliente INTEGER PRIMARY KEY, nombre TEXT, rfc TEXT, edad INTEGER,
                               ciudad TEXT, estado TEXT);
        CREATE TABLE productos (id_producto INTEGER PRIMARY KEY, nombre TEXT, categoria TEXT, precio_lista REAL);
    """)
    con.executemany("INSERT INTO usuarios VALUES (?, ?, ?)", [(u[0], u[1], "1234") for u in USUARIOS])
    con.executemany("INSERT INTO clientes VALUES (:id_cliente, :nombre, :rfc, :edad, :ciudad, :estado)", clientes)
    con.executemany("INSERT INTO productos VALUES (?, ?, ?, ?)", PRODUCTOS)
    con.commit()
    con.close()


def corromper_factura(factura, tipo, fecha_lote, folios_previos):
    detalle = factura["detalle"]
    if tipo == "cantidad_negativa":
        detalle[0]["cantidad"] = -random.randint(1, 5)
    elif tipo == "cantidad_texto":
        detalle[0]["cantidad"] = random.choice(["dos", "tres", "N/A"])
    elif tipo == "precio_texto":
        detalle[0]["precio_unitario"] = random.choice(["abc", "N/A", "$1,200"])
    elif tipo == "precio_negativo":
        detalle[0]["precio_unitario"] = -abs(detalle[0]["precio_unitario"] or 100.0)
    elif tipo == "fecha_futura":
        factura["fecha"] = (fecha_lote + timedelta(days=random.randint(30, 400))).isoformat()
    elif tipo == "fecha_invalida":
        factura["fecha"] = random.choice(["2026-13-45", "31/02/2026", "ayer"])
    elif tipo == "folio_vacio":
        factura["folio"] = ""
    elif tipo == "cliente_inexistente":
        factura["id_cliente"] = "99999"
    elif tipo == "producto_inexistente":
        detalle[0]["id_producto"] = 999
    elif tipo == "duplicado" and folios_previos:
        factura["folio"] = random.choice(folios_previos)
    elif tipo == "detalle_vacio":
        factura["detalle"] = []
    return factura


def generar_lineas():
    lineas = []
    for _ in range(random.choices([1, 2, 3, 4], weights=[35, 35, 20, 10])[0]):
        id_producto = random.randint(1, len(PRODUCTOS))
        lineas.append({"id_producto": id_producto, "cantidad": random.choices([1, 2, 3, 5, 10], [50, 25, 12, 8, 5])[0],
                       "precio_unitario": precio_con_variacion(id_producto)})
    return lineas


def generar_lotes(clientes_validos):
    inicio = date.fromisoformat(config.FECHA_INICIO_HISTORIA)
    fin = date.fromisoformat(config.FECHA_FIN_HISTORIA)
    consecutivo_app, consecutivo_suc = 1, 1
    siguiente_id_cliente = max(clientes_validos) + 1
    folios_previos = []
    stats = {"facturas": 0, "facturas_caos": 0, "clientes": 0, "clientes_caos": 0, "dias": 0}

    dia = inicio
    while dia <= fin:
        carpeta = config.ENTRADA_BATCH / dia.isoformat()
        carpeta.mkdir(parents=True, exist_ok=True)
        stats["dias"] += 1

        # ---- clientes_altas.csv ----
        altas = []
        for _ in range(random.randint(0, 3)):
            c = nuevo_cliente(siguiente_id_cliente, dia)
            siguiente_id_cliente += 1
            if random.random() < 0.15:
                tipo = random.choice(TIPOS_CAOS_CLIENTE)
                stats["clientes_caos"] += 1
                if tipo == "edad_negativa":
                    c["edad"] = -random.randint(1, 40)
                elif tipo == "edad_texto":
                    c["edad"] = random.choice(["veinte", "treinta y dos", "?"])
                elif tipo == "menor_de_edad":
                    c["edad"] = random.randint(10, 17)
                elif tipo == "rfc_invalido":
                    c["rfc"] = random.choice(["XXXX", "12345", c["rfc"][:8]])
                elif tipo == "nombre_vacio":
                    c["nombre"] = ""
            else:
                if random.random() < 0.08:
                    c["edad"] = ""        # NULO -> se imputa con la mediana
                clientes_validos.append(c["id_cliente"])
            c["id_cliente"] = id_como_texto(c["id_cliente"])
            altas.append(c)
            stats["clientes"] += 1
        with open(carpeta / "clientes_altas.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["id_cliente", "nombre", "rfc", "edad", "ciudad", "estado"])
            w.writeheader()
            w.writerows(altas)

        # ---- facturas.json (app) y facturas_sucursal.csv (sucursal antigua) ----
        facturas_app, filas_sucursal = [], []
        for origen, cuantas in [("app", random.randint(25, 45)), ("sucursal", random.randint(8, 15))]:
            for _ in range(cuantas):
                if origen == "app":
                    folio = f"F-{consecutivo_app:06d}"
                    consecutivo_app += 1
                else:
                    folio = f"S-{consecutivo_suc:06d}"
                    consecutivo_suc += 1
                factura = {"folio": folio, "fecha": dia.isoformat(),
                           "id_cliente": id_como_texto(random.choice(clientes_validos)),
                           "id_usuario": 4 if origen == "sucursal" else random.randint(1, 3),
                           "detalle": generar_lineas()}
                if random.random() < config.PORCENTAJE_CAOS:
                    factura = corromper_factura(factura, random.choice(TIPOS_CAOS_FACTURA), dia, folios_previos)
                    stats["facturas_caos"] += 1
                folios_previos.append(factura["folio"])
                stats["facturas"] += 1

                if origen == "app":
                    facturas_app.append(factura)
                else:
                    # 1FN violada: todos los productos en una sola celda "id:cantidad:precio|..."
                    productos = "|".join(
                        f"{l['id_producto']}:{l['cantidad']}:{'' if l['precio_unitario'] is None else l['precio_unitario']}"
                        for l in factura["detalle"])
                    filas_sucursal.append({"folio": factura["folio"], "fecha": factura["fecha"],
                                           "id_cliente": factura["id_cliente"],
                                           "nombre_cliente": "(capturado a mano)", "productos": productos})

        with open(carpeta / "facturas.json", "w", encoding="utf-8") as f:
            json.dump({"lote": dia.isoformat(), "generado_por": "gestor_facturas v2", "facturas": facturas_app},
                      f, ensure_ascii=False, indent=1)
        with open(carpeta / "facturas_sucursal.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["folio", "fecha", "id_cliente", "nombre_cliente", "productos"])
            w.writeheader()
            w.writerows(filas_sucursal)
        dia += timedelta(days=1)

    return stats, folios_previos


def generar_stream(folios, n_eventos=500):
    """Pagos en tiempo real del día de hoy. El archivo está ordenado por hora de LLEGADA,
    no por hora del evento: así se ve el desorden que provocan los fallos de red."""
    inicio = datetime.fromisoformat("2026-11-14T10:00:00")
    eventos = []
    stats = {"eventos": n_eventos, "retrasados_tolerables": 0, "fuera_de_watermark": 0, "corruptos": 0}
    for i in range(n_eventos):
        event_time = inicio + timedelta(seconds=i * 3.6 + random.uniform(0, 3))
        r = random.random()
        if r < 0.85:
            retraso = random.uniform(0, 5)
        elif r < 0.96:
            retraso = random.uniform(10, 100)
            stats["retrasados_tolerables"] += 1
        else:
            retraso = random.uniform(180, 600)       # fallo de red largo
            stats["fuera_de_watermark"] += 1
        evento = {"id_evento": f"E-{i + 1:05d}", "folio": random.choice(folios[-400:]),
                  "monto": round(random.uniform(150, 18000), 2),
                  "metodo": random.choice(sorted(config.METODOS_PAGO)),
                  "event_time": event_time.isoformat(timespec="seconds")}
        if random.random() < 0.05:
            stats["corruptos"] += 1
            tipo = random.choice(["monto_negativo", "monto_texto", "sin_folio", "fecha_rota", "json_roto"])
            if tipo == "monto_negativo":
                evento["monto"] = -evento["monto"]
            elif tipo == "monto_texto":
                evento["monto"] = "N/A"
            elif tipo == "sin_folio":
                evento["folio"] = None
            elif tipo == "fecha_rota":
                evento["event_time"] = "10:61:99"
            elif tipo == "json_roto":
                evento = "JSON_ROTO"
        llegada = event_time + timedelta(seconds=retraso)
        eventos.append((llegada, evento))

    eventos.sort(key=lambda x: x[0])
    with open(config.ENTRADA_STREAM, "w", encoding="utf-8") as f:
        for llegada, evento in eventos:
            if evento == "JSON_ROTO":
                f.write('{"id_evento": "E-ROTO", "monto": 120.5, "folio": \n')   # línea truncada
            else:
                evento["_llegada"] = llegada.isoformat(timespec="seconds")
                f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    return stats


def main(reset=True):
    random.seed(config.SEMILLA)
    if reset:
        # Solo borramos data/ (logs/ se queda: en Windows el log está abierto y no se puede borrar)
        vaciar_carpeta(config.DATA)
    asegurar_carpetas()

    fecha_ref = date.fromisoformat(config.FECHA_INICIO_HISTORIA)
    clientes = [nuevo_cliente(i, fecha_ref) for i in range(100, 400)]
    for c in random.sample(clientes, 6):
        c["edad"] = None                                # algunos nulos también en el maestro
    crear_fuente_relacional(clientes)
    log.info(f"Fuente relacional creada: {config.FUENTE_DB.name} con {len(clientes)} clientes y {len(PRODUCTOS)} productos")

    stats, folios = generar_lotes([c["id_cliente"] for c in clientes])
    log.info(f"Lotes batch: {stats['dias']} días | facturas={stats['facturas']} "
             f"(corruptas={stats['facturas_caos']}, {stats['facturas_caos'] / stats['facturas']:.1%}) | "
             f"altas de clientes={stats['clientes']} (corruptas={stats['clientes_caos']})")

    s = generar_stream([f for f in folios if f])
    log.info(f"Stream: {s['eventos']} eventos | retrasados dentro de tolerancia={s['retrasados_tolerables']} | "
             f"fuera de watermark={s['fuera_de_watermark']} | corruptos={s['corruptos']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera datos de origen con caos controlado")
    parser.add_argument("--reset", action="store_true", help="Borra data/ y logs/ antes de generar")
    args = parser.parse_args()
    main(reset=args.reset)
