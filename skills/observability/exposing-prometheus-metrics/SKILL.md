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

**Cuándo aplica esta skill.** Solo si el despliegue tiene contenedores propios de monitoreo (Prometheus que hace scrape de `/metrics`). Se enciende con `METRICS_ENABLED=true` (apagado por defecto: sin ese flag `setup_metrics` no registra `/metrics`). Si el servicio corre en una plataforma que trae sus propias métricas (p. ej. Vercel), usar lo nativo de la plataforma: ver `vercel-index` → `custom-metrics`.

**Hacer**

- **HTTP**: `Instrumentator(should_group_status_codes=True, should_ignore_untemplated=True, excluded_handlers=[...])`. Expone `http_requests_total{handler,method,status}` y `http_request_duration_seconds` (histograma), con `handler` = **plantilla** de ruta (`/orders/{order_id}`), no el path real.
- **Negocio**: módulo `app/observability/metrics.py` con métricas a nivel de módulo, importadas por los services. Se incrementan **después del `commit`**: solo cuenta lo persistido.
- **Nombres**: `<dominio>_<qué>_<unidad>`, snake_case, unidades base (segundos, bytes). Los counters terminan en `_total` (prometheus_client lo agrega solo). Pasar `unit=` al histograma.
- **Labels solo con cardinalidad acotada y conocida** (`reason`, `channel`, `status` agrupado). Regla práctica: el producto de los valores posibles de todos los labels < 100 por métrica.
- **Histogramas** con buckets alrededor de los umbrales del SLO (si el SLO es "< 500 ms", tiene que existir el bucket `0.5`). Percentiles con `histogram_quantile` sobre `rate(...[5m])` agregado `by (le)`. El Instrumentator trae por defecto dos histogramas: `http_request_duration_seconds` (por `handler`, solo **3 buckets**: 0.1, 0.5 y 1 s, así que un p99 de 5 s se ve como 1 s) y `http_request_duration_highr_seconds` (21 buckets, **sin** `handler`). Se fijan los buckets propios del primero con `metrics.default(latency_lowr_buckets=(...))`, que incluyen el umbral del SLO, y se usa para el SLI y para percentiles por endpoint; el `highr` sirve para los percentiles globales. No se agregan más buckets por `handler`: multiplicaría las series (regla de cardinalidad).
- **Counter** para eventos (siempre suben), **Histogram** para distribuciones (latencias, importes), **Gauge** solo para valores instantáneos (cola pendiente, conexiones abiertas).
- **Multiproceso** (gunicorn con `uvicorn-worker`; `uvicorn --workers N` no ejecuta `child_exit`, así que no llama a `mark_process_dead`): `PROMETHEUS_MULTIPROC_DIR` apuntando a un directorio que **existe y está vacío** en cada arranque (se borra y se crea en el comando de arranque). Sin el directorio la app no arranca (`FileNotFoundError` al importar); sin vaciarlo quedan archivos de workers muertos. Sin eso, cada scrape ve un worker distinto y los counters "saltan". En multiproceso **no existen** las métricas `process_*` (CPU, memoria, fds): los paneles de Recursos del dashboard quedan vacíos, y esos datos hay que tomarlos del contenedor. Dependencias solo en este caso: `gunicorn` y `uvicorn-worker` (`uvicorn.workers` está deprecado).
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

`app/observability/metrics.py` (verificado a mano (2026-11-01, pytest): el test de integración lee `shop_orders_created_total` y `http_requests_total{handler="/api/v1/orders",method="POST",status="2xx"}` desde `/metrics`):

```python
from fastapi import FastAPI
from prometheus_client import Counter, Histogram

from app.config import Settings

# Negocio. Labels SOLO de cardinalidad acotada (nunca ids, emails ni paths crudos).
ORDERS_CREATED = Counter("shop_orders_created", "Orders successfully persisted")
ORDER_REJECTIONS = Counter(
    "shop_order_rejections", "Orders rejected by business rules", labelnames=("reason",)
)
ORDER_VALUE = Histogram(
    "shop_order_value", "Order total amount", unit="usd",
    buckets=(10, 25, 50, 100, 250, 500, 1000, 5000),
)


def setup_metrics(app: FastAPI, settings: Settings) -> None:
    if not settings.METRICS_ENABLED:  # sin Prometheus propio no se expone /metrics
        return
    from prometheus_fastapi_instrumentator import Instrumentator, metrics  # diferido: apagado, no hace falta instalarlos

    Instrumentator(
        should_group_status_codes=True,      # status="2xx"/"4xx"/"5xx": cardinalidad fija
        should_ignore_untemplated=True,      # 404 a rutas inexistentes no crean series nuevas
        excluded_handlers=["/metrics", "/health/.*"],
    ).add(
        # Buckets de http_request_duration_seconds (por handler): incluyen el umbral del SLO (0.5) y su entorno.
        metrics.default(latency_lowr_buckets=(0.05, 0.1, 0.25, 0.3, 0.5, 1, 2.5, 5, 10))
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
```

Series resultantes:

```text
http_requests_total{handler="/api/v1/orders",method="POST",status="2xx"} 1.0
http_request_duration_seconds_bucket{handler="/api/v1/orders",le="0.5",method="POST"} 1.0
http_request_duration_highr_seconds_bucket{le="0.5"} 1.0
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
# Duration: p95 global (highr: 21 buckets) y p95 por endpoint (lowr: los buckets propios)
histogram_quantile(0.95, sum by (le) (rate(http_request_duration_highr_seconds_bucket{job="orders-api"}[5m])))
histogram_quantile(0.95, sum by (le, handler) (rate(http_request_duration_seconds_bucket{job="orders-api"}[5m])))
# Negocio: órdenes por minuto y ticket promedio
sum(rate(shop_orders_created_total{job="orders-api"}[5m])) * 60
sum(rate(shop_order_value_usd_sum{job="orders-api"}[1h])) / sum(rate(shop_order_value_usd_count{job="orders-api"}[1h]))
```

Multiproceso con gunicorn:

```python
# gunicorn.conf.py. Limpia las series de un worker que murió; el directorio se vacía al arrancar (abajo).
from prometheus_client import multiprocess

def child_exit(server, worker) -> None:  # type: ignore[no-untyped-def]
    multiprocess.mark_process_dead(worker.pid)
```

```bash
# Dependencias solo en multiproceso: gunicorn y uvicorn-worker.
D=/tmp/prometheus
rm -rf "$D" && mkdir -p "$D"   # vacío en cada arranque; sin el directorio la app no arranca
PROMETHEUS_MULTIPROC_DIR="$D" gunicorn app.main:app -k uvicorn_worker.UvicornWorker -w 4
```

## Checklist de verificación

- [ ] `curl -s :8000/metrics | grep http_requests_total` muestra `handler` con plantillas (`{order_id}`), nunca ids.
- [ ] Ninguna métrica tiene labels con ids, emails, paths crudos o texto libre.
- [ ] Cada KPI de negocio tiene métrica y test que verifica su incremento.
- [ ] Los buckets de latencia incluyen el umbral del SLO: `curl -s :8000/metrics | grep 'http_request_duration_seconds_bucket' | grep 'le="0.5"'` devuelve series.
- [ ] Prometheus → *Status / Targets*: el job está `UP`.
- [ ] Con N workers, el counter total en Prometheus coincide con el número de requests enviadas.

## Skills relacionadas

- `defining-grafana-slos`: SLIs, burn-rate alerts y dashboards sobre estas métricas.
- `tracing-with-opentelemetry`: el detalle por request que las métricas no deben tener.
