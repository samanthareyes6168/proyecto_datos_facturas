# utilidades.py
# Funciones que usan todos los pasos: logs, conexión al almacén, DLQ y traducción de llaves.

import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# En algunas consolas de Windows los símbolos ✓ ✗ ✅ provocan error de codificación
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def asegurar_carpetas():
    for carpeta in [config.FUENTE_DB.parent, config.ENTRADA_BATCH, config.ENTRADA_STREAM.parent,
                    config.ALMACEN_DB.parent, config.PARQUET_DIR, config.DLQ_DIR,
                    config.BENCHMARK_DIR, config.LOGS_DIR]:
        carpeta.mkdir(parents=True, exist_ok=True)


def obtener_logger(nombre):
    asegurar_carpetas()
    logger = logging.getLogger(nombre)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formato = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%H:%M:%S")
        consola = logging.StreamHandler(sys.stdout)
        consola.setFormatter(formato)
        archivo = logging.FileHandler(config.LOGS_DIR / "pipeline.log", encoding="utf-8")
        archivo.setFormatter(formato)
        logger.addHandler(consola)
        logger.addHandler(archivo)
        logger.propagate = False
    return logger


def conectar_almacen():
    asegurar_carpetas()
    con = sqlite3.connect(config.ALMACEN_DB, timeout=10)
    crear_tablas_control(con)
    return con


def crear_tablas_control(con):
    # Tablas que el pipeline usa para saber qué ya procesó (idempotencia) y para la DLQ.
    con.executescript("""
        CREATE TABLE IF NOT EXISTS control_lotes (
            lote TEXT PRIMARY KEY,
            estado TEXT NOT NULL,              -- cargado | validado
            fecha_carga TEXT,
            fecha_validacion TEXT,
            registros_crudos INTEGER
        );
        CREATE TABLE IF NOT EXISTS control_stream (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            offset_lineas INTEGER NOT NULL,
            max_event_time TEXT
        );
        CREATE TABLE IF NOT EXISTS dlq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_registro TEXT NOT NULL,
            lote TEXT,
            fuente TEXT,          -- facturas.json | facturas_sucursal.csv | clientes_altas.csv | stream
            entidad TEXT,         -- factura | cliente | pago | archivo
            llave TEXT,           -- folio, id_cliente o id_evento
            capa TEXT,            -- formato | esquema | negocio | watermark
            motivos TEXT,
            registro_original TEXT
        );
    """)
    con.commit()


def enviar_a_dlq(con, lote, fuente, entidad, llave, capa, motivos, registro_original):
    """Manda un registro malo a la Dead Letter Queue. El pipeline NO se detiene."""
    if isinstance(motivos, (list, tuple)):
        motivos = "; ".join(motivos)
    if not isinstance(registro_original, str):
        registro_original = json.dumps(registro_original, ensure_ascii=False, default=str)
    con.execute(
        "INSERT INTO dlq (fecha_registro, lote, fuente, entidad, llave, capa, motivos, registro_original) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), lote, fuente, entidad,
         None if llave is None else str(llave), capa, motivos, registro_original),
    )


def traducir_llave(valor):
    """
    RETO DEL JOIN ROTO.
    En la base relacional el id_cliente es INTEGER (100), pero la app lo exporta como
    texto porque viene de un QLineEdit: "100", " 100 ", "100.0" o "0100".
    Esta función traduce cualquiera de esas formas al entero 100.
    Regresa None si el valor no se puede traducir (ej. "abc", "12.5", "").
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        return int(valor) if valor.is_integer() else None
    texto = str(valor).strip()
    if texto == "":
        return None
    try:
        numero = float(texto)
    except ValueError:
        return None
    if numero != numero or not numero.is_integer():   # NaN o con decimales
        return None
    return int(numero)



def vaciar_carpeta(carpeta):
    """
    Borra una carpeta y su contenido. En Windows con OneDrive a veces sale
    'PermissionError: Acceso denegado' porque OneDrive tiene la carpeta "agarrada"
    mientras sincroniza. Por eso: se reintenta 3 veces y, si aun así no se deja,
    se borran los archivos uno por uno y las carpetas que no se dejen se quedan vacías.
    """
    import shutil
    import time
    carpeta = Path(carpeta)
    for _ in range(3):
        if not carpeta.exists():
            return
        try:
            shutil.rmtree(carpeta)
            return
        except PermissionError:
            time.sleep(1)
    for ruta in sorted(carpeta.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            ruta.unlink() if ruta.is_file() else ruta.rmdir()
        except OSError:
            pass
