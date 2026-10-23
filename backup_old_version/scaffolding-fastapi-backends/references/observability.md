# Observabilidad: métricas, logs y trazas

| Pilar | Herramienta | Cómo se alimenta |
|---|---|---|
| Métricas | Prometheus `:9090` | la API expone `/metrics` (`prometheus-fastapi-instrumentator`); scrape cada 15 s |
| Logs | Loki `:3100` + Grafana Alloy | Alloy lee stdout de todos los contenedores vía el socket de Docker |
| Trazas | Tempo `:3200` + OpenTelemetry | FastAPI y SQLAlchemy instrumentados (cada query es un span), export OTLP/gRPC a `tempo:4317` |
| Visualización | Grafana `:3000` | datasources y dashboard **provisionados** desde `monitoring/grafana/` |

Principios:

- **Todo como código**: clonar + `docker compose up` produce los mismos datasources y dashboards, sin clicks.
- **Correlación**: cada log lleva `trace_id`/`span_id`; Grafana salta log → traza (Loki derived field) y traza → logs (Tempo `tracesToLogsV2`).
- **Tracing opcional**: solo se activa si existe `OTEL_EXPORTER_OTLP_ENDPOINT`; tests y ejecución local no necesitan Tempo.
- `/metrics` se excluye de las trazas y de los paneles (es ruido del scrape).

## Estructura

```text
monitoring/
├── prometheus.yml
├── loki.yml
├── tempo.yml
├── alloy.river
├── build_dashboard.py                 # genera el JSON del dashboard
└── grafana/
    ├── provisioning/
    │   ├── datasources/datasources.yml
    │   └── dashboards/dashboards.yml
    └── dashboards/<servicio>.json     # generado, versionado
```

## `app/telemetry.py`

```python
import logging
import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

LOG_FORMAT = (
    "%(asctime)s %(levelname)s [%(name)s] "
    "[trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] - %(message)s"
)


def setup_telemetry(app: FastAPI, db_engine) -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")  # variable estándar de OTel
    if not endpoint:
        return  # tests / ejecución local: sin tracing

    provider = TracerProvider(
        resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "my-api")})
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)

    LoggingInstrumentor().instrument(set_logging_format=True, logging_format=LOG_FORMAT)
    logging.getLogger().setLevel(logging.INFO)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="metrics")
    SQLAlchemyInstrumentor().instrument(engine=db_engine.sync_engine)  # engine async → .sync_engine
```

La app escribe logs con `logging` (nunca `print`): así salen con nivel y `trace_id`.

## Servicios en `docker-compose.yml`

```yaml
  prometheus:
    image: prom/prometheus:v3.5.0
    container_name: prometheus
    restart: always
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --enable-feature=exemplar-storage
    ports: ["9090:9090"]
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro,z
      - prometheus_data:/prometheus
    depends_on: [backend]

  grafana:
    image: grafana/grafana:12.1.0
    container_name: grafana
    restart: always
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
    ports: ["3000:3000"]
    volumes:
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro,z
      - ./monitoring/grafana/dashboards:/var/lib/grafana/dashboards:ro,z
      - grafana_data:/var/lib/grafana
    depends_on: [prometheus, loki, tempo]

  loki:
    image: grafana/loki:3.5.0
    container_name: loki
    restart: always
    command: ["-config.file=/etc/loki/loki.yml"]
    ports: ["3100:3100"]
    volumes:
      - ./monitoring/loki.yml:/etc/loki/loki.yml:ro,z
      - loki_data:/loki

  alloy:
    image: grafana/alloy:v1.10.0
    container_name: alloy
    restart: always
    command: ["run", "--server.http.listen-addr=0.0.0.0:12345", "/etc/alloy/config.alloy"]
    security_opt: [label=disable]          # SELinux: permite leer el socket de Docker
    volumes:
      - ./monitoring/alloy.river:/etc/alloy/config.alloy:ro,z
      - /var/run/docker.sock:/var/run/docker.sock
    depends_on: [loki]

  tempo:
    image: grafana/tempo:2.8.0
    container_name: tempo
    restart: always
    user: root                              # escribe en el volumen /var/tempo
    command: ["-config.file=/etc/tempo/tempo.yml"]
    ports: ["3200:3200"]
    volumes:
      - ./monitoring/tempo.yml:/etc/tempo/tempo.yml:ro,z
      - tempo_data:/var/tempo
```

Los tags de arriba son ejemplos: al crear el proyecto, fijar la versión estable vigente de cada imagen (no `latest`) para que el stack sea reproducible; al actualizar, cambiar los tags a propósito y probar.

## `monitoring/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: backend
    metrics_path: /metrics
    static_configs:
      - targets: ["backend:8000"]
```

## `monitoring/loki.yml`

```yaml
auth_enabled: false
server:
  http_listen_port: 3100
common:
  instance_addr: 127.0.0.1
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory
schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h
limits_config:
  allow_structured_metadata: true
```

## `monitoring/tempo.yml`

```yaml
server:
  http_listen_port: 3200
distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
storage:
  trace:
    backend: local
    wal:
      path: /var/tempo/wal
    local:
      path: /var/tempo/blocks
```

## `monitoring/alloy.river`

```river
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

discovery.relabel "containers" {
  targets = discovery.docker.containers.targets
  rule {
    source_labels = ["__meta_docker_container_name"]
    regex         = "/(.*)"
    target_label  = "container"
  }
  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_service"]
    target_label  = "service"
  }
}

loki.source.docker "containers" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.relabel.containers.output
  forward_to = [loki.write.default.receiver]
}

loki.write "default" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

## `monitoring/grafana/provisioning/datasources/datasources.yml`

`uid` fijos: el dashboard y los enlaces entre datasources los referencian.

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    jsonData:
      exemplarTraceIdDestinations:
        - name: trace_id
          datasourceUid: tempo
  - name: Loki
    uid: loki
    type: loki
    access: proxy
    url: http://loki:3100
    jsonData:
      derivedFields:
        - name: TraceID
          matcherRegex: "trace_id=(\\w+)"
          url: "$${__value.raw}"            # $$ escapa el $ en provisioning
          datasourceUid: tempo
  - name: Tempo
    uid: tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    jsonData:
      tracesToLogsV2:
        datasourceUid: loki
        filterByTraceID: true
      serviceMap:
        datasourceUid: prometheus
```

Si existen datasources creados a mano con el mismo nombre, agregar un bloque `deleteDatasources:` con esos nombres para evitar conflictos de `uid`.

## `monitoring/grafana/provisioning/dashboards/dashboards.yml`

```yaml
apiVersion: 1
providers:
  - name: default
    folder: ""
    type: file
    disableDeletion: false
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards
```

## Dashboard como código

El JSON del dashboard se genera con [build_dashboard.py](../templates/build_dashboard.py) (copiar a `monitoring/`, ajustar `SERVICE`, `CONTAINER` y `TITLE`, correr `python3 monitoring/build_dashboard.py`, versionar el JSON resultante). Para cambiar el dashboard se edita el script, no la UI.

Paneles incluidos:

- **Resumen**: requests/s, % de errores 5xx (umbrales 1 % / 5 %), latencia p95, requests totales.
- **Tráfico**: requests/s por endpoint y por código de estado.
- **Latencia**: p50/p95/p99 global y p95 por endpoint (`histogram_quantile` sobre `http_request_duration_seconds_bucket`).
- **Recursos**: CPU, memoria residente, file descriptors del proceso.
- **Logs (Loki)**: volumen por nivel, logs del backend con buscador (`$search`), solo errores.
- **Trazas (Tempo)**: trazas recientes del servicio y trazas lentas (> 500 ms) vía TraceQL.

## Verificación

1. `docker compose up -d --build` y generar tráfico (Swagger en `/docs`).
2. Prometheus → *Status / Targets*: `backend` en `UP`.
3. Grafana → dashboard: paneles con datos.
4. Explore → Loki `{container="backend_app"}` → abrir un log → link *TraceID* abre la traza en Tempo → desde la traza, *Logs for this span* vuelve a Loki.
