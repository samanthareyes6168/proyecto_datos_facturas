"""Copia una muestra de datos (CSV, JSON y Parquet) a muestras/ para el repositorio."""

import shutil

import config

destino = config.RAIZ / "muestras"
destino.mkdir(exist_ok=True)
lote = config.ENTRADA_BATCH / "2026-08-03"
for archivo in ["facturas.json", "facturas_sucursal.csv", "clientes_altas.csv"]:
    shutil.copy(lote / archivo, destino / f"origen_{archivo}")
for archivo in ["mart_ventas_mensuales.parquet", "mart_ventas_producto.parquet", "dlq.parquet", "_manifiesto.json"]:
    if (config.PARQUET_DIR / archivo).exists():
        shutil.copy(config.PARQUET_DIR / archivo, destino / archivo)
if (config.DLQ_DIR / "dlq_completa.csv").exists():
    shutil.copy(config.DLQ_DIR / "dlq_completa.csv", destino / "dlq_completa.csv")
with open(config.ENTRADA_STREAM, encoding="utf-8") as f, open(destino / "eventos_pagos_muestra.jsonl", "w", encoding="utf-8") as g:
    g.writelines(f.readlines()[:50])
print(f"Muestras copiadas a {destino}")
