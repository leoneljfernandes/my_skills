---
name: exposing-prometheus-metrics
description: Use when a Python/FastAPI service needs Prometheus metrics - exposing /metrics, HTTP request rate/latency/status (RED), business KPIs (orders, payments, signups), counters/histograms/gauges, label design, multiprocess workers (gunicorn/uvicorn --workers) - or when Prometheus memory explodes from high cardinality, latency percentiles look wrong, or metrics disappear/duplicate across workers.
domain: observability
tags: [python, fastapi, prometheus, metrics, red-method, prometheus-client]
triggers: [prometheus, "/metrics", prometheus_client, prometheus-fastapi-instrumentator, Counter, Histogram, Gauge, "métricas de negocio", "business metrics", cardinality, "high cardinality", histogram_quantile, PROMETHEUS_MULTIPROC_DIR, RED]
---

# Métricas Prometheus: HTTP (RED) + negocio

Dos familias, dos herramientas: `prometheus-fastapi-instrumentator` mide **cómo responde** la API (Rate, Errors, Duration). `prometheus_client` mide **qué hace** el negocio. Ambas salen en el mismo `/metrics`.

## Contexto y reglas

**Hacer**

- **HTTP**: `Instrumentator(should_group_status_codes=True, should_ignore_untemplated=True, excluded_handlers=[...])`. Expone `http_requests_total{handler,method,status}` y `http_request_duration_seconds` (histograma), con `handler` = **plantilla** de ruta (`/orders/{order_id}`), no el path real.
- **Negocio**: módulo `app/observability/metrics.py` con métricas a nivel de módulo, importadas por los services. Se incrementan **después del `commit`**: solo cuenta lo persistido.
- **Nombres**: `<dominio>_<qué>_<unidad>`, snake_case, unidades base (segundos, bytes). Los counters terminan en `_total` (prometheus_client lo agrega solo). Pasar `unit=` al histograma.
- **Labels solo con cardinalidad acotada y conocida** (`reason`, `channel`, `status` agrupado). Regla práctica: el producto de los valores posibles de todos los labels < 100 por métrica.
- **Histogramas** con buckets alrededor de los umbrales del SLO (si el SLO es "< 500 ms", tiene que existir el bucket `0.5`). Percentiles con `histogram_quantile` sobre `rate(...[5m])` agregado `by (le)`.
- **Counter** para eventos (siempre suben), **Histogram** para distribuciones (latencias, importes), **Gauge** solo para valores instantáneos (cola pendiente, conexiones abiertas).
- **Multiproceso** (gunicorn o `uvicorn --workers N`): `PROMETHEUS_MULTIPROC_DIR` apuntando a un directorio vacío en cada arranque. Sin eso, cada scrape ve un worker distinto y los counters "saltan".
- Scrape con `job` estable (`job_name: orders-api`). Las reglas SLO y los dashboards filtran por `job`.
- Testear las métricas de negocio: `REGISTRY.get_sample_value("shop_orders_created_total")` o leer `/metrics` en un test de integración.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| Label `user_id`, `email`, `order_id`, path crudo | una serie por valor: Prometheus se queda sin memoria | logs/trazas para el detalle; labels acotados |
| `should_ignore_untemplated=False` | cada 404 de un bot crea una serie nueva | ignorar rutas no declaradas |
| Promedio de latencia (`sum/count`) como indicador | oculta la cola lenta | p95/p99 con `histogram_quantile` |
| Incrementar el counter antes del commit | cuenta órdenes que hicieron rollback | incrementar después del commit |
| Gauge para "requests procesadas" | pierde eventos entre scrapes; se reinicia con el proceso | Counter + `rate()` |
| Métricas creadas dentro de la función | `Duplicated timeseries in CollectorRegistry` | definirlas una vez a nivel de módulo |
| `/metrics` público en internet | expone topología y volumen de negocio | red interna o auth en el ingress |

## Ejemplos

`app/observability/metrics.py` (verificado: el test de integración lee `shop_orders_created_total` y `http_requests_total{handler="/api/v1/orders",method="POST",status="2xx"}` desde `/metrics`):

```python
from fastapi import FastAPI
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

# Negocio. Labels SOLO de cardinalidad acotada (nunca ids, emails ni paths crudos).
ORDERS_CREATED = Counter("shop_orders_created", "Orders successfully persisted")
ORDER_REJECTIONS = Counter(
    "shop_order_rejections", "Orders rejected by business rules", labelnames=("reason",)
)
ORDER_VALUE = Histogram(
    "shop_order_value", "Order total amount", unit="usd",
    buckets=(10, 25, 50, 100, 250, 500, 1000, 5000),
)


def setup_metrics(app: FastAPI) -> None:
    Instrumentator(
        should_group_status_codes=True,      # status="2xx"/"4xx"/"5xx": cardinalidad fija
        should_ignore_untemplated=True,      # 404 a rutas inexistentes no crean series nuevas
        excluded_handlers=["/metrics", "/health/.*"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
```

Series resultantes:

```text
http_requests_total{handler="/api/v1/orders",method="POST",status="2xx"} 1.0
http_request_duration_seconds_bucket{handler="/api/v1/orders",le="0.5",method="POST"} 1.0
shop_orders_created_total 1.0
shop_order_rejections_total{reason="insufficient_stock"} 1.0
shop_order_value_usd_bucket{le="50.0"} 1.0
```

Uso en el service (después del commit):

```python
await self._session.commit()
ORDERS_CREATED.inc()  # métricas de negocio DESPUÉS del commit: solo cuenta lo persistido
ORDER_VALUE.observe(float(order.total))
```

Rechazos, antes de lanzar la excepción de dominio:

```python
if product.stock < data.quantity:
    ORDER_REJECTIONS.labels(reason="insufficient_stock").inc()
    raise InsufficientStockError(...)
```

PromQL de referencia:

```promql
# Rate (req/s) por endpoint
sum by (handler) (rate(http_requests_total{job="orders-api"}[5m]))
# Errors: ratio de 5xx
sum(rate(http_requests_total{job="orders-api",status="5xx"}[5m]))
  / sum(rate(http_requests_total{job="orders-api"}[5m]))
# Duration: p95 por endpoint
histogram_quantile(0.95, sum by (le, handler) (rate(http_request_duration_seconds_bucket{job="orders-api"}[5m])))
# Negocio: órdenes por minuto y ticket promedio
sum(rate(shop_orders_created_total[5m])) * 60
sum(rate(shop_order_value_usd_sum[1h])) / sum(rate(shop_order_value_usd_count[1h]))
```

Multiproceso con gunicorn:

```python
# gunicorn.conf.py. El directorio se vacía en cada deploy (p. ej. emptyDir / tmpfs).
from prometheus_client import multiprocess

def child_exit(server, worker) -> None:  # type: ignore[no-untyped-def]
    multiprocess.mark_process_dead(worker.pid)
```

```bash
PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4
```

## Checklist de verificación

- [ ] `curl -s :8000/metrics | grep http_requests_total` muestra `handler` con plantillas (`{order_id}`), nunca ids.
- [ ] Ninguna métrica tiene labels con ids, emails, paths crudos o texto libre.
- [ ] Cada KPI de negocio tiene métrica y test que verifica su incremento.
- [ ] Los buckets de latencia incluyen el umbral del SLO.
- [ ] Prometheus → *Status / Targets*: el job está `UP`.
- [ ] Con N workers, el counter total en Prometheus coincide con el número de requests enviadas.

## Skills relacionadas

- `defining-grafana-slos`: SLIs, burn-rate alerts y dashboards sobre estas métricas.
- `tracing-with-opentelemetry`: el detalle por request que las métricas no deben tener.
