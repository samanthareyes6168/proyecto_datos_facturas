# Catálogo de datos

_Generado automáticamente por `pipeline/p7_catalogo.py` el 2026-11-14 18:01. Versión de esquema 1.0.0._

El catálogo tiene dos vistas: la **de referencia** explica los datos en lenguaje de negocio; la **operativa** documenta tipos, calidad, sensibilidad y quién puede acceder.

## Vista de referencia (negocio)

### dim_cliente
**Qué es:** Clientes que pueden recibir facturas. Un renglón por cliente.  
**Para qué sirve:** Segmentar ventas por cliente, ciudad o edad.  
**Responsable:** Área Comercial

| Campo | Significado |
|---|---|
| id_cliente | Número único del cliente |
| nombre | Nombre completo |
| rfc | Registro Federal de Contribuyentes |
| edad | Edad en años (mín. 18) |
| edad_imputada | 1 si la edad faltaba y se rellenó con la mediana |
| id_ciudad | Ciudad donde vive (ver dim_ciudad) |
| origen | maestro_app o alta_csv |

### dim_ciudad
**Qué es:** Catálogo de ciudades y su estado.  
**Para qué sirve:** Ventas por región.  
**Responsable:** Ingeniería de Datos

| Campo | Significado |
|---|---|
| id_ciudad | Identificador |
| ciudad | Nombre de la ciudad |
| estado | Estado de la república |

### dim_producto
**Qué es:** Productos y servicios que se venden.  
**Para qué sirve:** Ventas por producto o categoría.  
**Responsable:** Área de Compras

| Campo | Significado |
|---|---|
| id_producto | Identificador |
| nombre | Nombre del producto |
| categoria | Cómputo, Accesorios, Papelería, ... |
| precio_lista | Precio oficial de catálogo |

### facturas
**Qué es:** Encabezado de cada factura emitida (una por folio).  
**Para qué sirve:** Conteo de facturas, auditoría.  
**Responsable:** Contabilidad

| Campo | Significado |
|---|---|
| folio | Folio único (F- app, S- sucursal) |
| fecha | Fecha de emisión |
| id_cliente | Cliente facturado |
| id_usuario | Usuario que la emitió |
| origen | app_json o sucursal_csv |
| lote | Cierre nocturno en que llegó |

### detalle_factura
**Qué es:** Cada producto dentro de una factura.  
**Para qué sirve:** Base de todos los cálculos de ventas.  
**Responsable:** Contabilidad

| Campo | Significado |
|---|---|
| folio | Factura a la que pertenece |
| linea | Número de renglón |
| id_producto | Producto vendido |
| cantidad | Unidades (> 0) |
| precio_unitario | Precio cobrado por unidad (> 0) |
| precio_imputado | 1 si el precio faltaba y se imputó |
| es_outlier | 1 si el precio es atípico (IQR) |

### pagos
**Qué es:** Pagos recibidos en tiempo real.  
**Para qué sirve:** Cobranza del día.  
**Responsable:** Tesorería

| Campo | Significado |
|---|---|
| id_evento | Identificador del evento |
| folio | Factura pagada |
| monto | Importe pagado |
| metodo | tarjeta/efectivo/transferencia |
| event_time | Hora en que ocurrió el pago |
| llegada | Hora en que llegó al sistema |
| retraso_seg | Segundos de retraso por la red |

### hechos_ventas
**Qué es:** Historia completa de ventas, ya limpia y unida (capa histórica, se exporta a Parquet).  
**Para qué sirve:** Cualquier análisis de ventas.  
**Responsable:** Ingeniería de Datos

| Campo | Significado |
|---|---|
| anio | Año |
| mes | Mes |
| importe | cantidad x precio_unitario |

### mart_ventas_mensuales
**Qué es:** Reporte final: ventas, facturas, clientes y ticket promedio por mes.  
**Para qué sirve:** Dirección general.  
**Responsable:** Dirección

| Campo | Significado |
|---|---|
| ticket_promedio | Venta promedio por factura |

### mart_ventas_cliente
**Qué es:** Reporte final: ranking de clientes por ventas.  
**Para qué sirve:** Área Comercial.  
**Responsable:** Área Comercial

### mart_ventas_producto
**Qué es:** Reporte final: ventas por producto, con calidad (imputados y outliers).  
**Para qué sirve:** Compras.  
**Responsable:** Área de Compras

### stream_cobranza_minuto
**Qué es:** Cobranza agregada por minuto (tiempo real).  
**Para qué sirve:** Monitor de caja.  
**Responsable:** Tesorería

| Campo | Significado |
|---|---|
| estado | abierta (aún puede recibir tardíos) o cerrada |

### dlq
**Qué es:** Dead Letter Queue: registros rechazados con su motivo, para corregirlos.  
**Para qué sirve:** Auditoría de calidad de datos.  
**Responsable:** Ingeniería de Datos

| Campo | Significado |
|---|---|
| capa | formato, esquema, negocio o watermark |
| motivos | Por qué se rechazó |
| registro_original | El dato tal cual llegó |

## Vista operativa (gobernanza y metadatos técnicos)

### Roles de acceso
- **analista**: Analista de negocio (solo lectura de marts y Parquet)
- **ingeniero**: Ingeniero de datos (lectura/escritura en todo el almacén)
- **auditor**: Auditor / contabilidad (lectura de DLQ y facturas)

**Regla de gobernanza:** la columna `usuarios.password` de la app nunca se copia al almacén (se excluye desde la extracción, ver `p1_ingesta_batch.py`).

### dim_cliente
| Atributo | Valor |
|---|---|
| Filas | 432 |
| Sensibilidad | Confidencial (datos personales: nombre, RFC, edad) |
| Acceso | ingeniero, auditor |
| Actualización | Diaria (batch 02:00) |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| id_cliente | INTEGER | ✔ | 0.0 |
| nombre | TEXT |  | 0.0 |
| rfc | TEXT |  | 0.0 |
| edad | INTEGER |  | 0.0 |
| edad_imputada | INTEGER |  | 0.0 |
| id_ciudad | INTEGER |  | 0.0 |
| origen | TEXT |  | 0.0 |

### dim_ciudad
| Atributo | Valor |
|---|---|
| Filas | 10 |
| Sensibilidad | Pública |
| Acceso | analista, ingeniero, auditor |
| Actualización | Diaria |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| id_ciudad | INTEGER | ✔ | 0.0 |
| ciudad | TEXT |  | 0.0 |
| estado | TEXT |  | 0.0 |

### dim_producto
| Atributo | Valor |
|---|---|
| Filas | 25 |
| Sensibilidad | Interna |
| Acceso | analista, ingeniero, auditor |
| Actualización | Diaria |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| id_producto | INTEGER | ✔ | 0.0 |
| nombre | TEXT |  | 0.0 |
| categoria | TEXT |  | 0.0 |
| precio_lista | REAL |  | 0.0 |

### facturas
| Atributo | Valor |
|---|---|
| Filas | 4,451 |
| Sensibilidad | Confidencial (fiscal) |
| Acceso | ingeniero, auditor |
| Actualización | Diaria |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| folio | TEXT | ✔ | 0.0 |
| fecha | TEXT |  | 0.0 |
| id_cliente | INTEGER |  | 0.0 |
| id_usuario | INTEGER |  | 0.0 |
| origen | TEXT |  | 0.0 |
| lote | TEXT |  | 0.0 |

### detalle_factura
| Atributo | Valor |
|---|---|
| Filas | 9,040 |
| Sensibilidad | Confidencial (fiscal) |
| Acceso | ingeniero, auditor |
| Actualización | Diaria |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| folio | TEXT | ✔ | 0.0 |
| linea | INTEGER | ✔ | 0.0 |
| id_producto | INTEGER |  | 0.0 |
| cantidad | INTEGER |  | 0.0 |
| precio_unitario | REAL |  | 0.0 |
| precio_imputado | INTEGER |  | 0.0 |
| es_outlier | INTEGER |  | 0.0 |

### pagos
| Atributo | Valor |
|---|---|
| Filas | 463 |
| Sensibilidad | Confidencial (financiera) |
| Acceso | ingeniero, auditor |
| Actualización | Continua (stream) |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| id_evento | TEXT | ✔ | 0.0 |
| folio | TEXT |  | 0.0 |
| monto | REAL |  | 0.0 |
| metodo | TEXT |  | 0.0 |
| event_time | TEXT |  | 0.0 |
| llegada | TEXT |  | 0.0 |
| retraso_seg | REAL |  | 0.0 |

### hechos_ventas
| Atributo | Valor |
|---|---|
| Filas | 9,040 |
| Sensibilidad | Interna (incluye nombre del cliente) |
| Acceso | analista, ingeniero, auditor |
| Actualización | Diaria |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| folio | TEXT |  | 0.0 |
| linea | INT |  | 0.0 |
| fecha | TEXT |  | 0.0 |
| anio | INT |  | 0.0 |
| mes | INT |  | 0.0 |
| origen | TEXT |  | 0.0 |
| id_cliente | INT |  | 0.0 |
| cliente | TEXT |  | 0.0 |
| ciudad | TEXT |  | 0.0 |
| estado | TEXT |  | 0.0 |
| id_producto | INT |  | 0.0 |
| producto | TEXT |  | 0.0 |
| categoria | TEXT |  | 0.0 |
| cantidad | INT |  | 0.0 |
| precio_unitario | REAL |  | 0.0 |
| importe | TEXT |  | 0.0 |
| precio_imputado | INT |  | 0.0 |
| es_outlier | INT |  | 0.0 |

### mart_ventas_mensuales
| Atributo | Valor |
|---|---|
| Filas | 4 |
| Sensibilidad | Interna |
| Acceso | analista, ingeniero, auditor |
| Actualización | Diaria |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| anio_mes | TEXT |  | 0.0 |
| num_facturas | TEXT |  | 0.0 |
| num_clientes | TEXT |  | 0.0 |
| ventas_totales | TEXT |  | 0.0 |
| ticket_promedio | TEXT |  | 0.0 |

### mart_ventas_cliente
| Atributo | Valor |
|---|---|
| Filas | 418 |
| Sensibilidad | Interna |
| Acceso | analista, ingeniero |
| Actualización | Diaria |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| id_cliente | INT |  | 0.0 |
| cliente | TEXT |  | 0.0 |
| ciudad | TEXT |  | 0.0 |
| estado | TEXT |  | 0.0 |
| num_facturas | TEXT |  | 0.0 |
| ventas_totales | TEXT |  | 0.0 |

### mart_ventas_producto
| Atributo | Valor |
|---|---|
| Filas | 25 |
| Sensibilidad | Interna |
| Acceso | analista, ingeniero |
| Actualización | Diaria |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| id_producto | INT |  | 0.0 |
| producto | TEXT |  | 0.0 |
| categoria | TEXT |  | 0.0 |
| unidades | TEXT |  | 0.0 |
| ventas_totales | TEXT |  | 0.0 |
| lineas_con_precio_imputado | TEXT |  | 0.0 |
| lineas_outlier | TEXT |  | 0.0 |

### stream_cobranza_minuto
| Atributo | Valor |
|---|---|
| Filas | 32 |
| Sensibilidad | Interna |
| Acceso | analista, ingeniero |
| Actualización | Continua |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| ventana_inicio | TEXT | ✔ | 0.0 |
| ventana_fin | TEXT |  | 0.0 |
| num_pagos | INTEGER |  | 0.0 |
| monto_total | REAL |  | 0.0 |
| eventos_tardios_aceptados | INTEGER |  | 0.0 |
| estado | TEXT |  | 0.0 |

### dlq
| Atributo | Valor |
|---|---|
| Filas | 428 |
| Sensibilidad | Confidencial (contiene datos crudos) |
| Acceso | ingeniero, auditor |
| Actualización | Cada corrida |
| Versión de esquema | 1.0.0 |

| Columna | Tipo | PK | % nulos |
|---|---|---|---|
| id | INTEGER | ✔ | 0.0 |
| fecha_registro | TEXT |  | 0.0 |
| lote | TEXT |  | 0.0 |
| fuente | TEXT |  | 0.0 |
| entidad | TEXT |  | 0.0 |
| llave | TEXT |  | 0.7 |
| capa | TEXT |  | 0.0 |
| motivos | TEXT |  | 0.0 |
| registro_original | TEXT |  | 0.0 |
