# 5. Justificación de costos: Batch vs Stream (FinOps)

Precios de referencia consultados en noviembre de 2026 (verificar antes de entregar):
- AWS EC2 `t3.medium` (2 vCPU, 4 GB) bajo demanda en us-east-1: **USD 0.0416 por hora** ([Holori](https://calculator.holori.com/aws/ec2/t3.medium/us-east-1)).
- GitHub Actions, runner Linux de 2 núcleos: **USD 0.006 por minuto**; gratis en repositorios públicos y con
  USD 12 mensuales incluidos en la cuenta gratuita para repos privados ([GitHub Docs](https://docs.github.com/en/billing/concepts/product-billing/github-actions)).

## Comparación para la vía Batch
| Opción | Cálculo | Costo mensual aprox. |
|---|---|---|
| Servidor encendido 24/7 esperando el cierre | 730 h × 0.0416 | **USD 30.37** |
| Mismo servidor, encendido solo 15 min al día | 7.5 h × 0.0416 | **USD 0.31** |
| GitHub Actions programado (≈ 3 min por corrida) | 90 min × 0.006 | **USD 0.54** (USD 0 en repo público) |

El pipeline completo tarda segundos en procesar un día de facturas. Mantener un servidor prendido 24/7
para eso desperdicia más del **98 %** del cómputo. Por eso la vía Batch corre a las 02:00 en un runner que se
crea, procesa y **se destruye**: se paga solo el tiempo de uso, en un horario sin carga.

## ¿Y el Stream?
El Stream sí necesita estar escuchando todo el tiempo, porque su valor es ver la cobranza minuto a minuto.
Por eso es la parte cara de la arquitectura y se limita a lo que de verdad necesita tiempo real (pagos):

| Diseño | Costo mensual aprox. | Comentario |
|---|---|---|
| Todo en tiempo real (facturas + pagos), 24/7 | USD 30+ | Paga tiempo real para datos que contabilidad revisa una vez al día |
| **Híbrido: facturas en batch, pagos en stream** (este proyecto) | ≈ USD 30.9 | Tiempo real solo donde aporta |
| Pagos en micro-batch cada 5 min, en horario de tienda (12 h) | ≈ USD 15 | Alternativa si 5 min de retraso es aceptable |

## Conclusión para el documento ejecutivo
La arquitectura híbrida reserva el cómputo continuo para la cobranza, que lo necesita, y procesa la
facturación, que es el mayor volumen, en una ventana nocturna con recursos apagados el resto del día.
El costo del batch baja de unos USD 30 a menos de USD 1 al mes.
