# p2_ingesta_stream.py
# PASO 2: Ingesta STREAM (micro-batch) de pagos en tiempo real con WATERMARKING.
#
# Problema: por fallos de red, los eventos NO llegan en el orden en que ocurrieron.
# Solución: ventanas de 1 minuto según la hora del EVENTO (event_time) y un watermark:
#
#     watermark = (event_time más reciente que hemos visto) - tolerancia (2 minutos)
#
#   - Si llega un evento con event_time >= watermark  -> se acepta y actualiza su ventana,
#     aunque haya llegado tarde (retraso tolerable).
#   - Si llega un evento con event_time <  watermark  -> su ventana ya se CERRÓ: va a la DLQ
#     con capa 'watermark' para auditarlo (no se pierde, pero no altera reportes cerrados).
#   - Una ventana se marca 'cerrada' cuando su fin queda por debajo del watermark.
#
# El consumidor recuerda hasta qué línea leyó (control_stream.offset_lineas), así que si se
# agregan eventos nuevos al archivo, la siguiente corrida solo procesa los nuevos.
#
# Uso:  python -m pipeline.p2_ingesta_stream            (rápido)
#       python -m pipeline.p2_ingesta_stream --en-vivo  (imprime cada evento, para la demo)

import argparse
import json
import time
from datetime import datetime, timedelta

import config
from pipeline.p3_validacion import reglas_pago, validar_esquema
from pipeline.utilidades import conectar_almacen, enviar_a_dlq, obtener_logger

log = obtener_logger("p2_stream")
TOLERANCIA = timedelta(seconds=config.WATERMARK_TOLERANCIA_SEG)


def crear_tablas_stream(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS stg_pagos (
            id_evento TEXT PRIMARY KEY, folio TEXT, monto REAL, metodo TEXT,
            event_time TEXT, llegada TEXT, retraso_seg REAL, ventana_inicio TEXT);
        CREATE TABLE IF NOT EXISTS stream_cobranza_minuto (
            ventana_inicio TEXT PRIMARY KEY, ventana_fin TEXT, num_pagos INTEGER,
            monto_total REAL, eventos_tardios_aceptados INTEGER, estado TEXT);
    """)


def inicio_ventana(t):
    segundos = (t.minute * 60 + t.second) // config.VENTANA_SEG * config.VENTANA_SEG
    return t.replace(minute=0, second=0, microsecond=0) + timedelta(seconds=segundos)


def procesar_stream(en_vivo=False, pausa=0.02):
    con = conectar_almacen()
    crear_tablas_stream(con)
    estado = con.execute("SELECT offset_lineas, max_event_time FROM control_stream WHERE id = 1").fetchone()
    offset = estado[0] if estado else 0
    max_event = datetime.fromisoformat(estado[1]) if estado and estado[1] else None

    if not config.ENTRADA_STREAM.exists():
        log.warning("No hay archivo de stream")
        return {}
    with open(config.ENTRADA_STREAM, encoding="utf-8") as f:
        lineas = f.readlines()
    nuevas = lineas[offset:]
    stats = {"leidos": len(nuevas), "aceptados": 0, "tardios_aceptados": 0, "fuera_watermark": 0, "invalidos": 0}

    for texto in nuevas:
        # ---- formato: ¿es JSON legible? ----
        try:
            evento = json.loads(texto)
        except json.JSONDecodeError as e:
            enviar_a_dlq(con, "stream", "stream", "pago", None, "formato", f"JSON ilegible: {e.msg}", texto.strip())
            stats["invalidos"] += 1
            continue
        # ---- capa 1 y 2: esquema y negocio ----
        p, errores = validar_esquema(evento, "pago")
        capa = "esquema"
        if not errores:
            errores, capa = reglas_pago(p), "negocio"
        if errores:
            enviar_a_dlq(con, "stream", "stream", "pago", evento.get("id_evento"), capa, errores, evento)
            stats["invalidos"] += 1
            continue

        llegada = datetime.fromisoformat(evento.get("_llegada", p["event_time"].isoformat()))
        retraso = (llegada - p["event_time"]).total_seconds()

        # ---- WATERMARK ----
        watermark = max_event - TOLERANCIA if max_event else None
        if watermark and p["event_time"] < watermark:
            enviar_a_dlq(con, "stream", "stream", "pago", p["id_evento"], "watermark",
                         f"evento de {p['event_time'].time()} llegó {retraso:.0f}s tarde; "
                         f"watermark ya iba en {watermark.time()} (ventana cerrada)", evento)
            stats["fuera_watermark"] += 1
            if en_vivo:
                print(f"  ✗ {p['id_evento']} {p['event_time'].time()}  retraso {retraso:5.0f}s  -> DLQ (fuera de watermark)")
            continue

        es_tardio = max_event is not None and p["event_time"] < max_event
        max_event = p["event_time"] if max_event is None else max(max_event, p["event_time"])
        ventana = inicio_ventana(p["event_time"])

        con.execute("INSERT OR IGNORE INTO stg_pagos VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (p["id_evento"], p["folio"], p["monto"], p["metodo"], p["event_time"].isoformat(),
                     llegada.isoformat(), retraso, ventana.isoformat()))
        con.execute("""
            INSERT INTO stream_cobranza_minuto VALUES (?, ?, 1, ?, ?, 'abierta')
            ON CONFLICT(ventana_inicio) DO UPDATE SET
                num_pagos = num_pagos + 1, monto_total = monto_total + excluded.monto_total,
                eventos_tardios_aceptados = eventos_tardios_aceptados + excluded.eventos_tardios_aceptados
        """, (ventana.isoformat(), (ventana + timedelta(seconds=config.VENTANA_SEG)).isoformat(),
              p["monto"], 1 if es_tardio else 0))
        # Cerramos las ventanas que ya quedaron detrás del watermark
        con.execute("UPDATE stream_cobranza_minuto SET estado = 'cerrada' WHERE estado = 'abierta' AND ventana_fin <= ?",
                    ((max_event - TOLERANCIA).isoformat(),))
        stats["aceptados"] += 1
        stats["tardios_aceptados"] += 1 if es_tardio else 0
        if en_vivo:
            marca = "↺ tardío aceptado" if es_tardio else "✓"
            print(f"  {marca:17} {p['id_evento']} {p['event_time'].time()}  ${p['monto']:>10,.2f}  ventana {ventana.time()}")
            time.sleep(pausa)

    con.execute("INSERT INTO control_stream (id, offset_lineas, max_event_time) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET offset_lineas = excluded.offset_lineas, max_event_time = excluded.max_event_time",
                (offset + len(nuevas), max_event.isoformat() if max_event else None))
    con.commit()
    abiertas = con.execute("SELECT COUNT(*) FROM stream_cobranza_minuto WHERE estado = 'abierta'").fetchone()[0]
    con.close()
    log.info(f"Stream: leídos={stats['leidos']} aceptados={stats['aceptados']} "
             f"(tardíos dentro de tolerancia={stats['tardios_aceptados']}) | fuera de watermark={stats['fuera_watermark']} "
             f"| inválidos={stats['invalidos']} | ventanas abiertas={abiertas} | watermark={config.WATERMARK_TOLERANCIA_SEG}s")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--en-vivo", action="store_true", help="Muestra cada evento conforme llega")
    args = parser.parse_args()
    procesar_stream(en_vivo=args.en_vivo)
