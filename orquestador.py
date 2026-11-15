# orquestador.py
# FASE 4: Script maestro con un DAG (grafo de tareas con dependencias).
#
#   - Respeta DEPENDENCIAS: una tarea solo corre cuando terminaron todas las que necesita.
#   - PRIORIZA POR COSTO: si varias tareas están listas, primero corre las baratas.
#     Las tareas de costo "alto" (benchmark) solo corren en la ventana nocturna o con --incluir-costosas.
#   - RETRY con backoff exponencial: ante fallos TEMPORALES (red, base bloqueada) reintenta
#     esperando 2s, 4s, 8s. Los errores de lógica NO se reintentan (fallar rápido).
#   - Si una tarea falla definitivamente, sus dependientes se saltan, pero las demás siguen.
#
# Horario: el batch corre todos los días a las 02:00 (ver .github/workflows/pipeline_nocturno.yml).
#
# Uso:
#   python orquestador.py                       -> corre todo el DAG
#   python orquestador.py --simular-falla-red   -> los 2 primeros intentos de conexión fallan (demo Retry)
#   python orquestador.py --incluir-costosas    -> también corre el benchmark Parquet vs CSV
#   python orquestador.py --solo-stream         -> solo la vía de tiempo real
#   python orquestador.py --ver-dag             -> imprime el DAG y sale

import argparse
import os
import sqlite3
import time
from datetime import datetime

import config
from pipeline import (p1_ingesta_batch, p2_ingesta_stream, p3_validacion, p4_imputacion, p5_modelado,
                      p6_parquet, p7_catalogo)
from pipeline.utilidades import obtener_logger

log = obtener_logger("orquestador")

ORDEN_COSTO = {"bajo": 0, "medio": 1, "alto": 2}


def es_temporal(error):
    """Solo vale la pena reintentar fallos pasajeros. Un 'no such column' NO se arregla esperando."""
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    return isinstance(error, sqlite3.OperationalError) and "locked" in str(error).lower()

# nombre: (función, dependencias, costo)
DAG = {
    "extraer_maestros":   (p1_ingesta_batch.extraer_maestros, [], "bajo"),
    "ingesta_batch":      (p1_ingesta_batch.ingestar_lotes, [], "medio"),
    "ingesta_stream":     (p2_ingesta_stream.procesar_stream, [], "bajo"),
    "validar_y_dlq":      (p3_validacion.validar_lotes, ["extraer_maestros", "ingesta_batch"], "medio"),
    "imputar":            (p4_imputacion.imputar, ["validar_y_dlq"], "medio"),
    "modelar_3fn_marts":  (p5_modelado.modelar, ["imputar", "ingesta_stream"], "medio"),
    "exportar_parquet":   (p6_parquet.exportar_parquet, ["modelar_3fn_marts"], "medio"),
    "catalogo_datos":     (p7_catalogo.generar_catalogo, ["modelar_3fn_marts"], "bajo"),
    "benchmark_parquet":  (p6_parquet.benchmark, ["exportar_parquet"], "alto"),
}


def con_reintentos(nombre, funcion):
    for intento in range(1, config.REINTENTOS_MAXIMOS + 2):     # 1 intento + 3 reintentos
        try:
            return funcion()
        except Exception as e:
            if not es_temporal(e) or intento > config.REINTENTOS_MAXIMOS:
                raise
            espera = config.ESPERA_BASE_SEG * 2 ** (intento - 1)
            log.warning(f"[{nombre}] fallo temporal: {e}. Reintento {intento}/{config.REINTENTOS_MAXIMOS} en {espera}s")
            time.sleep(espera)


def imprimir_dag(dag):
    print("\nDAG del pipeline (tarea  <- depende de)  [costo]")
    for nombre, (_, deps, costo) in dag.items():
        print(f"  {nombre:20} <- {', '.join(deps) if deps else '(inicio)':40} [{costo}]")
    print()


def ejecutar(incluir_costosas=False, solo_stream=False):
    dag = dict(DAG)
    if solo_stream:
        dag = {k: v for k, v in dag.items() if k == "ingesta_stream"}
    if not incluir_costosas:
        dag = {k: v for k, v in dag.items() if v[2] != "alto"}

    log.info(f"===== Inicio del pipeline v{config.VERSION_PIPELINE} | {len(dag)} tareas =====")
    estado = {n: "pendiente" for n in dag}
    tiempos = {}
    inicio_total = time.perf_counter()

    while any(e == "pendiente" for e in estado.values()):
        # Saltar tareas cuyas dependencias fallaron
        for n, (_, deps, _) in dag.items():
            if estado[n] == "pendiente" and any(estado.get(d) in ("fallida", "saltada") for d in deps):
                estado[n] = "saltada"
                log.error(f"[{n}] SALTADA porque falló una dependencia")
        listas = [n for n, (_, deps, _) in dag.items()
                  if estado[n] == "pendiente" and all(estado.get(d, "ok") == "ok" for d in deps)]
        if not listas:
            break
        listas.sort(key=lambda n: ORDEN_COSTO[dag[n][2]])           # prioridad: primero lo barato
        nombre = listas[0]
        funcion = dag[nombre][0]
        log.info(f"[{nombre}] ▶ inicia (costo {dag[nombre][2]})")
        t0 = time.perf_counter()
        try:
            con_reintentos(nombre, funcion)
            estado[nombre] = "ok"
        except Exception as e:
            estado[nombre] = "fallida"
            log.error(f"[{nombre}] ✗ FALLÓ: {type(e).__name__}: {e}")
        tiempos[nombre] = time.perf_counter() - t0

    log.info("===== Resumen =====")
    for n in dag:
        log.info(f"  {n:20} {estado[n]:9} {tiempos.get(n, 0):6.2f}s")
    log.info(f"Tiempo total: {time.perf_counter() - inicio_total:.1f}s | fin {datetime.now():%H:%M:%S}")
    return estado


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orquestador del pipeline de facturas")
    parser.add_argument("--simular-falla-red", action="store_true")
    parser.add_argument("--incluir-costosas", action="store_true")
    parser.add_argument("--solo-stream", action="store_true")
    parser.add_argument("--ver-dag", action="store_true")
    args = parser.parse_args()
    if args.ver_dag:
        imprimir_dag(DAG)
        raise SystemExit(0)
    if args.simular_falla_red:
        os.environ["SIMULAR_FALLA_RED"] = "2"
    resultado = ejecutar(args.incluir_costosas, args.solo_stream)
    raise SystemExit(0 if all(e == "ok" for e in resultado.values()) else 1)
