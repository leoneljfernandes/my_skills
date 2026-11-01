---
name: tracing-with-opentelemetry
description: Use when adding distributed tracing to a Python/FastAPI service with OpenTelemetry and Grafana Tempo - TracerProvider setup, OTLP exporter, auto-instrumenting FastAPI/SQLAlchemy/httpx, manual spans and attributes for business operations, sampling, propagating context across services - or when traces are missing, SQL queries do not appear as child spans, spans are lost on shutdown, or logs cannot be correlated with traces.
domain: observability
tags: [python, fastapi, opentelemetry, tracing, tempo, sqlalchemy, otlp]
triggers: [OpenTelemetry, OTel, tracing, trazas, span, Tempo, OTLP, TracerProvider, FastAPIInstrumentor, SQLAlchemyInstrumentor, "start_as_current_span", sampling, traceparent, "distributed tracing", Jaeger]
---

# Trazas distribuidas con OpenTelemetry → Tempo

Auto-instrumentación para lo genérico (cada request HTTP, cada query SQL, cada llamada saliente) y spans manuales para las operaciones de negocio. Un solo `TracerProvider` por proceso. Exportación OTLP/gRPC a Tempo en batch.

## Contexto y reglas

**Cuándo aplica esta skill.** Solo si hay un colector OTLP al que exportar (Tempo propio u otro backend). Si el servicio corre en una plataforma con trazas nativas (p. ej. Vercel), usar `vercel-index` → `vercel-tracing`.

**Modo mínimo, sin SDK ni colector.** Si lo único que se necesita es un `trace_id` en logs y en las respuestas de error, alcanza con `opentelemetry-api` y la función `current_trace_id()` de abajo: sin `TracerProvider` no hay traza activa, devuelve `None` y el campo simplemente no aparece. `errors.py` y el formateador de logs funcionan igual; cuando se sume el SDK, aparecen los ids sin cambiar nada.

**Hacer**

- `setup_tracing(app, engine, settings)` en `create_app()`. Si no hay `OTEL_EXPORTER_OTLP_ENDPOINT` no hace nada, así que tests y desarrollo local no necesitan Tempo. Los campos `settings.OTEL_*` existen en `Settings` (ver `configuring-fastapi-settings`).
- `Resource` con `service.name`, `service.version` y `deployment.environment.name`: así se buscan y filtran las trazas.
- `BatchSpanProcessor` + `OTLPSpanExporter` (gRPC 4317). `provider.shutdown()` en el `lifespan` para no perder los spans en buffer al apagar.
- Sampler `ParentBased(TraceIdRatioBased(ratio))`: respeta la decisión del servicio que llama y aplica el ratio solo a trazas raíz. 100 % en dev/staging, menor en prod de alto volumen.
- `FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics,/health/.*")`, `SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)` (engine async → `.sync_engine`), y `HTTPXClientInstrumentor` para llamadas salientes (propaga `traceparent`).
- **Compatibilidad de versiones**: `opentelemetry-instrumentation-sqlalchemy` 0.66b1 declara `sqlalchemy < 2.1`. Con 2.1 instalado **no instrumenta nada** y solo deja un log de error. Fijar `sqlalchemy<2.1` o, si se acepta el riesgo, pasar `skip_dep_check=True` y verificar con un test que los spans SQL existen.
- Spans manuales con `tracer = trace.get_tracer(__name__)` a nivel de módulo y `with tracer.start_as_current_span("order.place", attributes={...})`. Nombres `<dominio>.<acción>` de baja cardinalidad; los ids van en atributos.
- Atributos con convenciones semánticas cuando existan, y prefijo de dominio para los propios (`order.id`, `order.quantity`).
- `trace_id` en logs (ver `logging-json-to-loki`) y en las respuestas de error (ver `handling-fastapi-errors`).
- Test con `InMemorySpanExporter` que verifique el span manual, sus atributos y que las queries SQL son hijas suyas.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `SimpleSpanProcessor` en producción | exporta en el hilo de la request: suma latencia | `BatchSpanProcessor` (Simple solo en tests) |
| Nombre de span con ids (`"order 42"`) | miles de nombres distintos; búsquedas y métricas inútiles | nombre fijo + atributo `order.id` |
| PII o secretos en atributos | quedan almacenados y visibles en Tempo | ids opacos |
| Instrumentar dos veces (`instrument_app` en cada `create_app` de tests) | spans duplicados, warnings | guardia de "ya configurado" |
| Sin `shutdown()` al apagar | se pierden los últimos spans de cada deploy | `shutdown_tracing()` en el `lifespan` |
| 100 % de sampling en prod de alto tráfico | costo de almacenamiento y red | ratio + tail sampling en el collector si hace falta |
| Confiar en que "instrument()" funcionó | con versiones incompatibles no hace nada en silencio | test que exige spans SQL hijos |

## Ejemplos

`app/observability/tracing.py` (verificado: test con `InMemorySpanExporter` y envío real por OTLP a Tempo 3.1.1, consultado de vuelta por la API `/api/v2/traces/<id>`):

```python
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings

_provider: TracerProvider | None = None


def setup_tracing(app: FastAPI, engine: AsyncEngine, settings: Settings) -> None:
    global _provider
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT or _provider is not None:
        return
    resource = Resource.create({
        "service.name": settings.APP_NAME,
        "service.version": settings.APP_VERSION,
        "deployment.environment.name": settings.APP_ENV.value,
    })
    # ParentBased: respeta la decisión del servicio que llama; ratio solo para trazas raíz.
    _provider = TracerProvider(
        resource=resource, sampler=ParentBased(TraceIdRatioBased(settings.OTEL_TRACES_SAMPLER_RATIO))
    )
    _provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                insecure=settings.OTEL_EXPORTER_OTLP_INSECURE,
            )
        )
    )
    trace.set_tracer_provider(_provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider, excluded_urls="/metrics,/health/.*")
    # Engine async → se instrumenta su sync_engine. Cada query es un span hijo del request.
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, tracer_provider=_provider)


def shutdown_tracing() -> None:
    if _provider is not None:
        _provider.shutdown()  # flush de los spans en buffer antes de salir


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def current_span_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.span_id, "016x") if ctx.is_valid else None
```

Span manual en un caso de uso:

```python
tracer = trace.get_tracer(__name__)


async def place_order(self, data: OrderCreate) -> Order:
    with tracer.start_as_current_span(
        "order.place",
        attributes={"order.product_id": data.product_id, "order.quantity": data.quantity},
    ) as span:
        product = await self._products.get_for_update(data.product_id)   # span SQL hijo
        ...
        await self._session.commit()
        span.set_attribute("order.id", order.id)
        return order
    # Si sale una excepción, el span la registra (record_exception) y queda con status ERROR.
```

Test que impide que la instrumentación falle en silencio:

```python
_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)  # global: una sola vez por proceso


@pytest.fixture
def spans(engine: AsyncEngine) -> Iterator[InMemorySpanExporter]:
    FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, tracer_provider=_provider)
    _exporter.clear()
    yield _exporter
    SQLAlchemyInstrumentor().uninstrument()
    FastAPIInstrumentor.uninstrument_app(app)


async def test_place_order_emits_manual_span_with_sql_children(
    client: AsyncClient, spans: InMemorySpanExporter
) -> None:
    product = await ProductFactory.create_async(stock=5)
    spans.clear()

    response = await client.post(
        "/api/v1/orders", json={"customer_email": "a@b.com", "product_id": product.id, "quantity": 1}
    )
    assert response.status_code == 201, response.text

    finished = spans.get_finished_spans()
    place = next(s for s in finished if s.name == "order.place")
    sql_children = [s for s in finished if s.parent is not None and s.parent.span_id == place.context.span_id]
    assert sql_children, [s.name for s in finished]
    server = next(s for s in finished if s.name == "POST /api/v1/orders")
    assert place.context.trace_id == server.context.trace_id
```

Variables de entorno (docker-compose del backend):

```yaml
OTEL_EXPORTER_OTLP_ENDPOINT: http://tempo:4317
OTEL_TRACES_SAMPLER_RATIO: "1.0"   # prod de alto tráfico: 0.1 o menos
```

## Checklist de verificación

- [ ] Con el modo mínimo, `current_trace_id()` devuelve `None` y la app arranca sin colector.
- [ ] El test con `InMemorySpanExporter` pasa: span manual con atributos + spans SQL hijos + mismo `trace_id` que el span HTTP.
- [ ] En Tempo, una request a `POST /api/v1/orders` muestra el árbol HTTP → `order.place` → queries SQL.
- [ ] Los logs emitidos durante la request tienen el mismo `trace_id` que la traza.
- [ ] Al detener el contenedor (`docker compose stop backend`), las últimas requests aparecen en Tempo.
- [ ] `/metrics` y `/health/*` no generan trazas.
- [ ] Las versiones de `sqlalchemy` y `opentelemetry-instrumentation-sqlalchemy` son compatibles: no aparece el log "falls outside of that range".

## Skills relacionadas

- `logging-json-to-loki`: correlación log ↔ traza.
- `defining-grafana-slos`: Tempo, datasources y service graph (references/stack.md).
- `handling-fastapi-errors`: `trace_id` en las respuestas de error.
