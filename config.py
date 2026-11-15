# config.py
# Configuración central del pipeline. Todas las rutas y parámetros viven aquí
# para que ningún script tenga valores "escondidos".

from pathlib import Path

# ---------------- Versión (versionado semántico MAJOR.MINOR.PATCH) ----------------
VERSION_PIPELINE = "1.0.0"
VERSION_ESQUEMA = "1.0.0"   # cambia MAJOR si se rompe el esquema (se borra/renombra una columna)

# ---------------- Rutas ----------------
RAIZ = Path(__file__).resolve().parent
DATA = RAIZ / "data"

FUENTE_DB = DATA / "fuente" / "gestor_facturas.db"          # base relacional de la app (origen)
ENTRADA_BATCH = DATA / "entrada" / "batch"                   # un folder por día: AAAA-MM-DD/
ENTRADA_STREAM = DATA / "entrada" / "stream" / "eventos_pagos.jsonl"

ALMACEN_DB = DATA / "almacen" / "almacen.db"                 # almacén analítico (ELT)
PARQUET_DIR = DATA / "parquet"                               # capa histórica en formato columnar
DLQ_DIR = DATA / "dlq"                                       # copia en CSV de la Dead Letter Queue
BENCHMARK_DIR = DATA / "benchmark"
LOGS_DIR = RAIZ / "logs"
DOCS_DIR = RAIZ / "docs"

# ---------------- Generación de datos ----------------
SEMILLA = 42
FECHA_INICIO_HISTORIA = "2026-08-03"
FECHA_FIN_HISTORIA = "2026-11-13"     # último cierre nocturno ya ocurrido
PORCENTAJE_CAOS = 0.07                # 7 % de registros corruptos (el reto pide mínimo 5 %)

# ---------------- Reglas de negocio ----------------
EDAD_MINIMA = 18
EDAD_MAXIMA = 110
CANTIDAD_MAXIMA = 1000
FECHA_MINIMA_FACTURA = "2020-01-01"
METODOS_PAGO = {"tarjeta", "efectivo", "transferencia"}
PATRON_RFC = r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$"

# ---------------- Stream ----------------
WATERMARK_TOLERANCIA_SEG = 120   # esperamos hasta 2 minutos a un evento retrasado
VENTANA_SEG = 60                 # ventanas de 1 minuto (tumbling windows)

# ---------------- Orquestación ----------------
REINTENTOS_MAXIMOS = 3
ESPERA_BASE_SEG = 2              # backoff exponencial: 2s, 4s, 8s
HORARIO_BATCH = "02:00 America/Mexico_City (08:00 UTC)"
