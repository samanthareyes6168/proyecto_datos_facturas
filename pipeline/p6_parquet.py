"""
Exportación a Apache Parquet y benchmark contra CSV.

  - exportar_parquet(): capa histórica y marts en Parquet, con la versión de esquema en metadatos.
  - benchmark(): misma consulta (ventas por año, mes y categoría) sobre CSV diarios y sobre Parquet.

Requiere pyarrow. Ejecución: python -m pipeline.p6_parquet [--benchmark] [--factor N]
"""

import argparse
import json
import shutil
import statistics
import time
from datetime import datetime

import pandas as pd

import config
from pipeline.utilidades import conectar_almacen, obtener_logger, vaciar_carpeta

log = obtener_logger("p6_parquet")
TABLAS_EXPORTAR = ["hechos_ventas", "mart_ventas_mensuales", "mart_ventas_cliente", "mart_ventas_producto",
                   "stream_cobranza_minuto", "dlq"]


def verificar_pyarrow():
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        raise RuntimeError("Falta la librería pyarrow. Instálenla con:  pip install pyarrow")


def escribir_parquet(df, ruta, nombre_tabla):
    import pyarrow as pa
    import pyarrow.parquet as pq
    tabla = pa.Table.from_pandas(df, preserve_index=False)
    metadatos = dict(tabla.schema.metadata or {})
    metadatos.update({b"version_esquema": config.VERSION_ESQUEMA.encode(),
                      b"version_pipeline": config.VERSION_PIPELINE.encode(),
                      b"tabla_origen": nombre_tabla.encode(),
                      b"generado_en": datetime.now().isoformat(timespec="seconds").encode()})
    pq.write_table(tabla.replace_schema_metadata(metadatos), ruta, compression="snappy")


def exportar_parquet():
    verificar_pyarrow()
    config.PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    con = conectar_almacen()
    manifiesto = {"version_esquema": config.VERSION_ESQUEMA, "version_pipeline": config.VERSION_PIPELINE,
                  "generado_en": datetime.now().isoformat(timespec="seconds"), "tablas": {}}
    existentes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for tabla in [t for t in TABLAS_EXPORTAR if t in existentes]:
        df = pd.read_sql(f"SELECT * FROM {tabla}", con)
        ruta = config.PARQUET_DIR / f"{tabla}.parquet"
        escribir_parquet(df, ruta, tabla)
        manifiesto["tablas"][tabla] = {"filas": len(df), "columnas": list(df.columns),
                                        "bytes": ruta.stat().st_size}
        log.info(f"Parquet: {ruta.name:32} {len(df):>7} filas  {ruta.stat().st_size / 1024:8.1f} KB")
    # Copia legible de la DLQ en CSV para auditoría
    pd.read_sql("SELECT * FROM dlq", con).to_csv(config.DLQ_DIR / "dlq_completa.csv", index=False, encoding="utf-8")
    con.close()
    (config.PARQUET_DIR / "_manifiesto.json").write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False),
                                                         encoding="utf-8")
    return manifiesto


def medir(funcion, repeticiones=3):
    tiempos = []
    for _ in range(repeticiones):
        inicio = time.perf_counter()
        resultado = funcion()
        tiempos.append(time.perf_counter() - inicio)
    return statistics.median(tiempos), resultado


def benchmark(factor=10):
    verificar_pyarrow()
    con = conectar_almacen()
    hechos = pd.read_sql("SELECT * FROM hechos_ventas", con)
    con.close()

    # Simulamos más historia replicando los datos (factor veces) para que la diferencia sea visible
    grande = pd.concat([hechos.assign(replica=r) for r in range(factor)], ignore_index=True)
    carpeta_csv = config.BENCHMARK_DIR / "csv_diarios"
    vaciar_carpeta(carpeta_csv)
    carpeta_csv.mkdir(parents=True, exist_ok=True)
    for (fecha, replica), grupo in grande.groupby(["fecha", "replica"]):
        grupo.to_csv(carpeta_csv / f"ventas_{fecha}_{replica:02d}.csv", index=False)
    ruta_parquet = config.BENCHMARK_DIR / "hechos_ventas_grande.parquet"
    escribir_parquet(grande, ruta_parquet, "hechos_ventas_grande")

    archivos = sorted(carpeta_csv.glob("*.csv"))
    columnas = ["anio", "mes", "categoria", "importe"]

    def consulta(df):
        return df.groupby(["anio", "mes", "categoria"])["importe"].sum().round(2)

    def desde_csv():
        return consulta(pd.concat((pd.read_csv(a) for a in archivos), ignore_index=True))

    def desde_parquet():
        return consulta(pd.read_parquet(ruta_parquet, columns=columnas))

    t_csv, r_csv = medir(desde_csv)
    t_parquet, r_parquet = medir(desde_parquet)
    iguales = r_csv.sort_index().equals(r_parquet.sort_index())
    bytes_csv = sum(a.stat().st_size for a in archivos)
    bytes_parquet = ruta_parquet.stat().st_size

    texto = f"""# Benchmark: múltiples CSV vs Apache Parquet (generado por `p6_parquet.py --benchmark`)

Consulta: **ventas totales por año, mes y categoría** sobre {len(grande):,} líneas de venta.

| | Múltiples CSV | Parquet |
|---|---|---|
| Archivos | {len(archivos):,} | 1 |
| Tamaño en disco | {bytes_csv / 1_048_576:,.1f} MB | {bytes_parquet / 1_048_576:,.1f} MB |
| Tiempo de la consulta (mediana de 3) | {t_csv:.3f} s | {t_parquet:.3f} s |
| Columnas leídas | todas ({len(grande.columns)}) | solo {len(columnas)} |

**Parquet fue {t_csv / t_parquet:,.1f} veces más rápido y ocupa {bytes_csv / bytes_parquet:,.1f} veces menos espacio.**
Ambas lecturas dieron exactamente el mismo resultado: {'sí' if iguales else 'NO (revisar)'}.

Razones: Parquet es columnar (lee solo las {len(columnas)} columnas que la consulta necesita),
binario y tipado (no convierte texto a número) y comprimido con snappy (menos bytes que leer).
"""
    (config.DOCS_DIR / "reporte_benchmark.md").write_text(texto, encoding="utf-8")
    log.info(f"BENCHMARK ({len(grande):,} filas): CSV x{len(archivos)} = {t_csv:.3f}s | Parquet = {t_parquet:.3f}s "
             f"-> {t_csv / t_parquet:.1f}x más rápido, {bytes_csv / bytes_parquet:.1f}x menos espacio")
    return {"t_csv": t_csv, "t_parquet": t_parquet, "archivos": len(archivos)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--factor", type=int, default=10, help="Veces que se replica la historia en el benchmark")
    args = parser.parse_args()
    exportar_parquet()
    if args.benchmark:
        benchmark(args.factor)
