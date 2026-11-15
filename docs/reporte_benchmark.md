# Benchmark: múltiples CSV vs Apache Parquet (generado por `p6_parquet.py --benchmark`)

Consulta: **ventas totales por año, mes y categoría** sobre 90,300 líneas de venta.

| | Múltiples CSV | Parquet |
|---|---|---|
| Archivos | 1,030 | 1 |
| Tamaño en disco | 12.7 MB | 1.0 MB |
| Tiempo de la consulta (mediana de 3) | 3.516 s | 0.023 s |
| Columnas leídas | todas (19) | solo 4 |

**Parquet fue 150.7 veces más rápido y ocupa 12.2 veces menos espacio.**
Ambas lecturas dieron exactamente el mismo resultado: sí.

Razones: Parquet es columnar (lee solo las 4 columnas que la consulta necesita),
binario y tipado (no convierte texto a número) y comprimido con snappy (menos bytes que leer).
