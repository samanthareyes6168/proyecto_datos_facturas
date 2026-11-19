"""
Validación en dos capas y Dead Letter Queue.

  1. Esquema: tipo y obligatoriedad de cada campo.
  2. Negocio: rangos, fechas, unicidad e integridad referencial.

Los registros válidos pasan a stg_*; los rechazados se registran en la tabla dlq
con su capa, motivos y registro original.
"""

import json
import re
from datetime import date, datetime

import config
from pipeline.utilidades import conectar_almacen, enviar_a_dlq, obtener_logger, traducir_llave

log = obtener_logger("p3_validacion")

# =====================================================================
# CAPA 1: ESQUEMAS  ->  campo: (tipo, obligatorio)
# =====================================================================
ESQUEMAS = {
    "factura": {"folio": ("texto", True), "fecha": ("fecha", True),
                "id_cliente": ("entero", True), "id_usuario": ("entero", False)},
    "linea":   {"id_producto": ("entero", True), "cantidad": ("entero", True),
                "precio_unitario": ("decimal", False)},          # nulo permitido -> se imputa
    "cliente": {"id_cliente": ("entero", True), "nombre": ("texto", True), "rfc": ("texto", True),
                "edad": ("entero", False), "ciudad": ("texto", True), "estado": ("texto", True)},
    "pago":    {"id_evento": ("texto", True), "folio": ("texto", True), "monto": ("decimal", True),
                "metodo": ("texto", True), "event_time": ("fechahora", True)},
}


def es_vacio(valor):
    return valor is None or (isinstance(valor, str) and valor.strip() == "")


def convertir(valor, tipo):
    """Intenta convertir al tipo técnico. Regresa (ok, valor_convertido)."""
    if tipo == "texto":
        return isinstance(valor, (str, int)), str(valor).strip()
    if tipo == "entero":
        v = traducir_llave(valor)
        return v is not None, v
    if tipo == "decimal":
        if isinstance(valor, bool):
            return False, None
        try:
            v = float(str(valor).strip())
            return v == v and v not in (float("inf"), float("-inf")), v
        except ValueError:
            return False, None
    if tipo == "fecha":
        try:
            return True, date.fromisoformat(str(valor).strip())
        except ValueError:
            return False, None
    if tipo == "fechahora":
        try:
            return True, datetime.fromisoformat(str(valor).strip())
        except ValueError:
            return False, None
    raise ValueError(f"Tipo desconocido: {tipo}")


def validar_esquema(registro, entidad):
    """Regresa (registro_convertido, lista_de_errores)."""
    errores, limpio = [], {}
    for campo, (tipo, obligatorio) in ESQUEMAS[entidad].items():
        valor = registro.get(campo)
        if es_vacio(valor):
            if obligatorio:
                errores.append(f"{campo}: obligatorio y viene vacío")
            limpio[campo] = None
            continue
        ok, convertido = convertir(valor, tipo)
        if ok:
            limpio[campo] = convertido
        else:
            errores.append(f"{campo}: se esperaba {tipo} y llegó {valor!r}")
    return limpio, errores


# =====================================================================
# CAPA 2: REGLAS DE NEGOCIO
# =====================================================================
FECHA_MINIMA = date.fromisoformat(config.FECHA_MINIMA_FACTURA)


def reglas_factura(f, lineas, fecha_lote, clientes_existentes, folios_existentes, productos_existentes):
    errores = []
    if f["fecha"] > fecha_lote:
        errores.append(f"fecha: {f['fecha']} es futura respecto al cierre {fecha_lote}")
    if f["fecha"] < FECHA_MINIMA:
        errores.append(f"fecha: {f['fecha']} es anterior a {FECHA_MINIMA}")
    if f["folio"] in folios_existentes:
        errores.append(f"folio: {f['folio']} duplicado (ya fue registrado)")
    if f["id_cliente"] not in clientes_existentes:
        errores.append(f"id_cliente: {f['id_cliente']} no existe en el catálogo de clientes (integridad referencial)")
    if len(lineas) == 0:
        errores.append("detalle: la factura no tiene productos")
    for i, l in enumerate(lineas, start=1):
        if l["cantidad"] is not None and not (0 < l["cantidad"] <= config.CANTIDAD_MAXIMA):
            errores.append(f"línea {i} cantidad: {l['cantidad']} fuera de rango (1..{config.CANTIDAD_MAXIMA})")
        if l["precio_unitario"] is not None and l["precio_unitario"] <= 0:
            errores.append(f"línea {i} precio_unitario: {l['precio_unitario']} debe ser positivo")
        if l["id_producto"] is not None and l["id_producto"] not in productos_existentes:
            errores.append(f"línea {i} id_producto: {l['id_producto']} no existe")
    return errores


def reglas_cliente(c):
    errores = []
    if c["edad"] is not None and not (config.EDAD_MINIMA <= c["edad"] <= config.EDAD_MAXIMA):
        errores.append(f"edad: {c['edad']} fuera de rango ({config.EDAD_MINIMA}..{config.EDAD_MAXIMA}); "
                       f"para facturar se requiere ser mayor de edad")
    if c["rfc"] is not None and not re.match(config.PATRON_RFC, c["rfc"].upper()):
        errores.append(f"rfc: {c['rfc']!r} no tiene formato válido de RFC")
    return errores


def reglas_pago(p):
    errores = []
    if p["monto"] is not None and p["monto"] <= 0:
        errores.append(f"monto: {p['monto']} debe ser positivo")
    if p["metodo"] is not None and p["metodo"] not in config.METODOS_PAGO:
        errores.append(f"metodo: {p['metodo']!r} no es un método de pago permitido")
    return errores


# =====================================================================
# 1FN: aplanar las fuentes (listas anidadas -> una fila por producto)
# =====================================================================
def lineas_desde_celda(celda):
    """La sucursal manda todos los productos en UNA celda: '3:2:150.0|7:1:89.9'.
    Eso viola la 1FN (valor no atómico). Aquí se separa en filas."""
    lineas, errores = [], []
    if es_vacio(celda):
        return lineas, errores
    for i, parte in enumerate(str(celda).split("|"), start=1):
        piezas = parte.split(":")
        if len(piezas) != 3:
            errores.append(f"productos: el elemento {i} ({parte!r}) no tiene formato id:cantidad:precio")
            continue
        lineas.append({"id_producto": piezas[0], "cantidad": piezas[1], "precio_unitario": piezas[2]})
    return lineas, errores


def crear_tablas_stg(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS stg_clientes_altas (
            id_cliente INTEGER PRIMARY KEY, id_cliente_original TEXT, nombre TEXT, rfc TEXT,
            edad INTEGER, ciudad TEXT, estado TEXT, lote TEXT);
        CREATE TABLE IF NOT EXISTS stg_facturas (
            folio TEXT PRIMARY KEY, fecha TEXT, id_cliente_original TEXT, id_cliente INTEGER,
            id_usuario INTEGER, origen TEXT, lote TEXT);
        CREATE TABLE IF NOT EXISTS stg_detalle (
            folio TEXT, linea INTEGER, id_producto INTEGER, cantidad INTEGER,
            precio_unitario REAL, lote TEXT, PRIMARY KEY (folio, linea));
    """)


def clientes_conocidos(con):
    maestro = {traducir_llave(r[0]) for r in con.execute("SELECT id_cliente FROM raw_clientes_maestro")}
    altas = {r[0] for r in con.execute("SELECT id_cliente FROM stg_clientes_altas")}
    return maestro | altas


def validar_clientes_lote(con, lote, stats):
    filas = con.execute("SELECT fila, id_cliente, nombre, rfc, edad, ciudad, estado FROM raw_clientes_altas "
                        "WHERE lote = ? ORDER BY fila", (lote,)).fetchall()
    existentes = clientes_conocidos(con)
    for fila in filas:
        original = dict(zip(["id_cliente", "nombre", "rfc", "edad", "ciudad", "estado"], fila[1:]))
        c, errores = validar_esquema(original, "cliente")
        capa = "esquema"
        if not errores:
            errores, capa = reglas_cliente(c), "negocio"
            if c["id_cliente"] in existentes:
                errores.append(f"id_cliente: {c['id_cliente']} ya existe")
        if errores:
            enviar_a_dlq(con, lote, "clientes_altas.csv", "cliente", original["id_cliente"], capa, errores, original)
            stats["clientes_dlq"] += 1
            continue
        con.execute("INSERT INTO stg_clientes_altas VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (c["id_cliente"], original["id_cliente"], c["nombre"], c["rfc"].upper(), c["edad"],
                     c["ciudad"], c["estado"], lote))
        existentes.add(c["id_cliente"])
        stats["clientes_ok"] += 1


def validar_facturas_lote(con, lote, stats):
    fecha_lote = date.fromisoformat(lote[:10])
    clientes = clientes_conocidos(con)
    productos = {traducir_llave(r[0]) for r in con.execute("SELECT id_producto FROM raw_productos")}
    folios = {r[0] for r in con.execute("SELECT folio FROM stg_facturas")}

    candidatas = []   # (fuente, origen, documento_original, encabezado, lineas, errores_formato)
    for (doc,) in con.execute("SELECT documento FROM raw_facturas_json WHERE lote = ? ORDER BY posicion", (lote,)):
        original = json.loads(doc)
        detalle = original.get("detalle")
        errores = [] if isinstance(detalle, list) else ["detalle: se esperaba una lista"]
        candidatas.append(("facturas.json", "app_json", original, original,
                           detalle if isinstance(detalle, list) else [], errores))
    for row in con.execute("SELECT folio, fecha, id_cliente, nombre_cliente, productos FROM raw_facturas_csv "
                           "WHERE lote = ? ORDER BY fila", (lote,)):
        original = dict(zip(["folio", "fecha", "id_cliente", "nombre_cliente", "productos"], row))
        lineas, errores = lineas_desde_celda(original["productos"])
        encabezado = {"folio": original["folio"], "fecha": original["fecha"],
                      "id_cliente": original["id_cliente"], "id_usuario": 4}
        candidatas.append(("facturas_sucursal.csv", "sucursal_csv", original, encabezado, lineas, errores))

    for fuente, origen, original, encabezado, lineas_crudas, errores in candidatas:
        # ---- Capa 1: esquema ----
        f, err = validar_esquema(encabezado, "factura")
        errores = errores + err
        lineas = []
        for i, lc in enumerate(lineas_crudas, start=1):
            l, err = validar_esquema(lc if isinstance(lc, dict) else {}, "linea")
            errores += [f"línea {i} {e}" for e in err]
            lineas.append(l)
        capa = "esquema" if errores else "negocio"
        # ---- Capa 2: negocio (solo si el esquema pasó) ----
        if not errores:
            errores = reglas_factura(f, lineas, fecha_lote, clientes, folios, productos)
        if errores:
            enviar_a_dlq(con, lote, fuente, "factura", encabezado.get("folio"), capa, errores, original)
            stats["facturas_dlq"] += 1
            continue
        con.execute("INSERT INTO stg_facturas VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f["folio"], f["fecha"].isoformat(), str(encabezado["id_cliente"]), f["id_cliente"],
                     f["id_usuario"], origen, lote))
        con.executemany("INSERT INTO stg_detalle VALUES (?, ?, ?, ?, ?, ?)",
                        [(f["folio"], i, l["id_producto"], l["cantidad"], l["precio_unitario"], lote)
                         for i, l in enumerate(lineas, start=1)])
        folios.add(f["folio"])
        stats["facturas_ok"] += 1
        stats["lineas_ok"] += len(lineas)


def validar_lotes():
    con = conectar_almacen()
    crear_tablas_stg(con)
    pendientes = [r[0] for r in con.execute("SELECT lote FROM control_lotes WHERE estado = 'cargado' ORDER BY lote")]
    stats = {"clientes_ok": 0, "clientes_dlq": 0, "facturas_ok": 0, "facturas_dlq": 0, "lineas_ok": 0}
    for lote in pendientes:
        validar_clientes_lote(con, lote, stats)    # primero clientes: una factura puede usar un cliente nuevo
        validar_facturas_lote(con, lote, stats)
        con.execute("UPDATE control_lotes SET estado = 'validado', fecha_validacion = ? WHERE lote = ?",
                    (datetime.now().isoformat(timespec="seconds"), lote))
        con.commit()
    con.close()
    total_f = stats["facturas_ok"] + stats["facturas_dlq"]
    log.info(f"Lotes validados: {len(pendientes)} | facturas válidas={stats['facturas_ok']} "
             f"DLQ={stats['facturas_dlq']} ({(stats['facturas_dlq'] / total_f if total_f else 0):.1%}) | "
             f"clientes válidos={stats['clientes_ok']} DLQ={stats['clientes_dlq']}")
    return stats


if __name__ == "__main__":
    validar_lotes()
