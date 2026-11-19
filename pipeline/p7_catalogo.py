"""
Catálogo de datos.

Genera la vista de referencia (significado de negocio) y la vista operativa
(tipos, filas, % de nulos, sensibilidad, accesos y frecuencia).

Salidas: docs/04_catalogo_datos.md, data/catalogo.json
"""

import json
from datetime import datetime

import config
from pipeline.utilidades import conectar_almacen, obtener_logger

log = obtener_logger("p7_catalogo")

ROLES = {"analista": "Analista de negocio (solo lectura de marts y Parquet)",
         "ingeniero": "Ingeniero de datos (lectura/escritura en todo el almacén)",
         "auditor": "Auditor / contabilidad (lectura de DLQ y facturas)"}

CATALOGO = {
    "dim_cliente": {
        "negocio": "Clientes que pueden recibir facturas. Un renglón por cliente.",
        "uso": "Segmentar ventas por cliente, ciudad o edad.",
        "dueno": "Área Comercial", "sensibilidad": "Confidencial (datos personales: nombre, RFC, edad)",
        "acceso": ["ingeniero", "auditor"], "frecuencia": "Diaria (batch 02:00)",
        "columnas": {"id_cliente": "Número único del cliente", "nombre": "Nombre completo",
                     "rfc": "Registro Federal de Contribuyentes", "edad": "Edad en años (mín. 18)",
                     "edad_imputada": "1 si la edad faltaba y se rellenó con la mediana",
                     "id_ciudad": "Ciudad donde vive (ver dim_ciudad)", "origen": "maestro_app o alta_csv"}},
    "dim_ciudad": {
        "negocio": "Catálogo de ciudades y su estado.", "uso": "Ventas por región.",
        "dueno": "Ingeniería de Datos", "sensibilidad": "Pública", "acceso": ["analista", "ingeniero", "auditor"],
        "frecuencia": "Diaria", "columnas": {"id_ciudad": "Identificador", "ciudad": "Nombre de la ciudad",
                                             "estado": "Estado de la república"}},
    "dim_producto": {
        "negocio": "Productos y servicios que se venden.", "uso": "Ventas por producto o categoría.",
        "dueno": "Área de Compras", "sensibilidad": "Interna", "acceso": ["analista", "ingeniero", "auditor"],
        "frecuencia": "Diaria", "columnas": {"id_producto": "Identificador", "nombre": "Nombre del producto",
                                             "categoria": "Cómputo, Accesorios, Papelería, ...",
                                             "precio_lista": "Precio oficial de catálogo"}},
    "facturas": {
        "negocio": "Encabezado de cada factura emitida (una por folio).", "uso": "Conteo de facturas, auditoría.",
        "dueno": "Contabilidad", "sensibilidad": "Confidencial (fiscal)", "acceso": ["ingeniero", "auditor"],
        "frecuencia": "Diaria", "columnas": {"folio": "Folio único (F- app, S- sucursal)", "fecha": "Fecha de emisión",
                                             "id_cliente": "Cliente facturado", "id_usuario": "Usuario que la emitió",
                                             "origen": "app_json o sucursal_csv", "lote": "Cierre nocturno en que llegó"}},
    "detalle_factura": {
        "negocio": "Cada producto dentro de una factura.", "uso": "Base de todos los cálculos de ventas.",
        "dueno": "Contabilidad", "sensibilidad": "Confidencial (fiscal)", "acceso": ["ingeniero", "auditor"],
        "frecuencia": "Diaria", "columnas": {"folio": "Factura a la que pertenece", "linea": "Número de renglón",
                                             "id_producto": "Producto vendido", "cantidad": "Unidades (> 0)",
                                             "precio_unitario": "Precio cobrado por unidad (> 0)",
                                             "precio_imputado": "1 si el precio faltaba y se imputó",
                                             "es_outlier": "1 si el precio es atípico (IQR)"}},
    "pagos": {
        "negocio": "Pagos recibidos en tiempo real.", "uso": "Cobranza del día.", "dueno": "Tesorería",
        "sensibilidad": "Confidencial (financiera)", "acceso": ["ingeniero", "auditor"],
        "frecuencia": "Continua (stream)", "columnas": {"id_evento": "Identificador del evento", "folio": "Factura pagada",
                                                        "monto": "Importe pagado", "metodo": "tarjeta/efectivo/transferencia",
                                                        "event_time": "Hora en que ocurrió el pago",
                                                        "llegada": "Hora en que llegó al sistema",
                                                        "retraso_seg": "Segundos de retraso por la red"}},
    "hechos_ventas": {
        "negocio": "Historia completa de ventas, ya limpia y unida (capa histórica, se exporta a Parquet).",
        "uso": "Cualquier análisis de ventas.", "dueno": "Ingeniería de Datos",
        "sensibilidad": "Interna (incluye nombre del cliente)", "acceso": ["analista", "ingeniero", "auditor"],
        "frecuencia": "Diaria", "columnas": {"importe": "cantidad x precio_unitario", "anio": "Año", "mes": "Mes"}},
    "mart_ventas_mensuales": {
        "negocio": "Reporte final: ventas, facturas, clientes y ticket promedio por mes.", "uso": "Dirección general.",
        "dueno": "Dirección", "sensibilidad": "Interna", "acceso": ["analista", "ingeniero", "auditor"],
        "frecuencia": "Diaria", "columnas": {"ticket_promedio": "Venta promedio por factura"}},
    "mart_ventas_cliente": {
        "negocio": "Reporte final: ranking de clientes por ventas.", "uso": "Área Comercial.",
        "dueno": "Área Comercial", "sensibilidad": "Interna", "acceso": ["analista", "ingeniero"],
        "frecuencia": "Diaria", "columnas": {}},
    "mart_ventas_producto": {
        "negocio": "Reporte final: ventas por producto, con calidad (imputados y outliers).", "uso": "Compras.",
        "dueno": "Área de Compras", "sensibilidad": "Interna", "acceso": ["analista", "ingeniero"],
        "frecuencia": "Diaria", "columnas": {}},
    "stream_cobranza_minuto": {
        "negocio": "Cobranza agregada por minuto (tiempo real).", "uso": "Monitor de caja.",
        "dueno": "Tesorería", "sensibilidad": "Interna", "acceso": ["analista", "ingeniero"],
        "frecuencia": "Continua", "columnas": {"estado": "abierta (aún puede recibir tardíos) o cerrada"}},
    "dlq": {
        "negocio": "Dead Letter Queue: registros rechazados con su motivo, para corregirlos.",
        "uso": "Auditoría de calidad de datos.", "dueno": "Ingeniería de Datos",
        "sensibilidad": "Confidencial (contiene datos crudos)", "acceso": ["ingeniero", "auditor"],
        "frecuencia": "Cada corrida", "columnas": {"capa": "formato, esquema, negocio o watermark",
                                                   "motivos": "Por qué se rechazó", "registro_original": "El dato tal cual llegó"}},
}


def generar_catalogo():
    con = conectar_almacen()
    salida, md_ref, md_op = {}, [], []
    for tabla, meta in CATALOGO.items():
        existe = con.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (tabla,)).fetchone()
        if not existe:
            continue
        filas = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        columnas = []
        for _, nombre, tipo, notnull, _, pk in con.execute(f"PRAGMA table_info({tabla})"):
            nulos = con.execute(f"SELECT COUNT(*) FROM {tabla} WHERE {nombre} IS NULL").fetchone()[0]
            columnas.append({"columna": nombre, "tipo": tipo or "TEXT", "pk": bool(pk),
                             "pct_nulos": round(nulos / filas * 100, 2) if filas else 0,
                             "descripcion": meta["columnas"].get(nombre, "")})
        salida[tabla] = {**{k: v for k, v in meta.items() if k != "columnas"}, "filas": filas, "columnas": columnas}

        md_ref.append(f"### {tabla}\n**Qué es:** {meta['negocio']}  \n**Para qué sirve:** {meta['uso']}  \n"
                      f"**Responsable:** {meta['dueno']}\n")
        descritas = [c for c in columnas if c["descripcion"]]
        if descritas:
            md_ref.append("| Campo | Significado |\n|---|---|\n" +
                          "\n".join(f"| {c['columna']} | {c['descripcion']} |" for c in descritas) + "\n")
        md_op.append(f"### {tabla}\n| Atributo | Valor |\n|---|---|\n| Filas | {filas:,} |\n"
                     f"| Sensibilidad | {meta['sensibilidad']} |\n| Acceso | {', '.join(meta['acceso'])} |\n"
                     f"| Actualización | {meta['frecuencia']} |\n| Versión de esquema | {config.VERSION_ESQUEMA} |\n\n"
                     "| Columna | Tipo | PK | % nulos |\n|---|---|---|---|\n" +
                     "\n".join(f"| {c['columna']} | {c['tipo']} | {'✔' if c['pk'] else ''} | {c['pct_nulos']} |"
                               for c in columnas) + "\n")
    con.close()

    roles = "\n".join(f"- **{k}**: {v}" for k, v in ROLES.items())
    texto = (f"# Catálogo de datos\n\n_Generado automáticamente por `pipeline/p7_catalogo.py` el "
             f"{datetime.now():%Y-%m-%d %H:%M}. Versión de esquema {config.VERSION_ESQUEMA}._\n\n"
             "El catálogo tiene dos vistas: la **de referencia** explica los datos en lenguaje de negocio; "
             "la **operativa** documenta tipos, calidad, sensibilidad y quién puede acceder.\n\n"
             "## Vista de referencia (negocio)\n\n" + "\n".join(md_ref) +
             "\n## Vista operativa (gobernanza y metadatos técnicos)\n\n### Roles de acceso\n" + roles +
             "\n\n**Regla de gobernanza:** la columna `usuarios.password` de la app nunca se copia al almacén "
             "(se excluye desde la extracción, ver `p1_ingesta_batch.py`).\n\n" + "\n".join(md_op))
    (config.DOCS_DIR / "04_catalogo_datos.md").write_text(texto, encoding="utf-8")
    (config.DATA / "catalogo.json").write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"Catálogo generado: {len(salida)} tablas documentadas -> docs/04_catalogo_datos.md")


if __name__ == "__main__":
    generar_catalogo()
