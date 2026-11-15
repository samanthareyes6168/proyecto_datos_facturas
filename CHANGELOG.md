# Changelog

Versionado semántico **MAJOR.MINOR.PATCH**:
- **MAJOR**: cambio que rompe el esquema (se borra o renombra una columna que alguien consume).
- **MINOR**: funcionalidad nueva compatible (una tabla, una regla o un reporte nuevo).
- **PATCH**: corrección que no cambia el esquema.

## [1.0.0] - 2026-11-30
### Agregado
- Orquestador con DAG, prioridad por costo y Retry con backoff exponencial.
- Exportación a Apache Parquet con versión de esquema en los metadatos y benchmark contra CSV.
- Catálogo de datos (vista de referencia y operativa), linaje y análisis de impacto.
- Chaos Test y workflow nocturno de GitHub Actions.

## [0.2.0] - 2026-11-22
### Agregado
- Ingesta batch (ELT) y stream con watermarking.
- Validación en doble capa y Dead Letter Queue.
- Traducción de llaves para el join roto, normalización 3FN e imputación por mediana vs KNN.

## [0.1.0] - 2026-11-13
### Agregado
- Modelo conceptual y generador de datos con caos controlado (CSV, JSON, SQLite y stream).
