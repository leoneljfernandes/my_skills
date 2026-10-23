# Stack de observabilidad: configuración completa

Versiones verificadas el 2026-10-23 (todas arrancaron o validaron con estos archivos): Prometheus 3.15.1, Alertmanager 0.34.1, Loki 3.7.9, Tempo 3.1.1, Grafana 13.2.4, Alloy 1.21.2. Al actualizar una imagen, cambiar el tag a propósito y repetir las verificaciones del final.

## Estructura

```text
monitoring/
├── prometheus/
│   ├── prometheus.yml
│   ├── rules/<servicio>-slo.yml        # cargado por el glob rules/*.yml
│   └── tests/<servicio>-slo.test.yml   # FUERA de rules/: si no, Prometheus no arranca
├── alertmanager/
│   ├── alertmanager.yml
│   └── secrets/                        # url_file de webhooks (no versionado)
├── alloy/config.alloy                  # ver skill logging-json-to-loki
├── loki.yml
├── tempo.yml
├── build_dashboard.py                  # templates/build_dashboard.py de esta skill
└── grafana/
    ├── provisioning/datasources/datasources.yml
    ├── provisioning/dashboards/dashboards.yml
    └── dashboards/<servicio>.json      # generado, versionado
```

## Servicios de docker-compose

```yaml
# Agregar a los servicios de docker-compose.yml (el backend expone :8000/metrics y exporta OTLP a tempo:4317).
  prometheus:
    image: prom/prometheus:v3.15.1
    restart: unless-stopped
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=15d
      - --web.enable-remote-write-receiver     # recibe métricas del metrics-generator de Tempo
      - --enable-feature=exemplar-storage      # exemplars → salto de métrica a traza
    ports: ["9090:9090"]
    volumes:
      - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro,z
      - ./monitoring/prometheus/rules:/etc/prometheus/rules:ro,z
      - prometheus_data:/prometheus

  alertmanager:
    image: prom/alertmanager:v0.34.1
    restart: unless-stopped
    command: ["--config.file=/etc/alertmanager/alertmanager.yml"]
    ports: ["9093:9093"]
    volumes:
      - ./monitoring/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro,z
      - ./monitoring/alertmanager/secrets:/etc/alertmanager/secrets:ro,z   # no versionado

  loki:
    image: grafana/loki:3.7.9
    restart: unless-stopped
    command: ["-config.file=/etc/loki/loki.yml"]
    ports: ["3100:3100"]
    volumes:
      - ./monitoring/loki.yml:/etc/loki/loki.yml:ro,z
      - loki_data:/loki

  alloy:
    image: grafana/alloy:v1.21.2
    restart: unless-stopped
    command: ["run", "--server.http.listen-addr=0.0.0.0:12345", "/etc/alloy/config.alloy"]
    security_opt: [label=disable]          # SELinux: permite leer el socket de Docker
    volumes:
      - ./monitoring/alloy/config.alloy:/etc/alloy/config.alloy:ro,z
      - /var/run/docker.sock:/var/run/docker.sock:ro
    depends_on: [loki]

  tempo:
    image: grafana/tempo:3.1.1
    restart: unless-stopped
    user: root                             # escribe en el volumen /var/tempo
    command: ["-config.file=/etc/tempo/tempo.yml"]
    ports: ["3200:3200"]
    volumes:
      - ./monitoring/tempo.yml:/etc/tempo/tempo.yml:ro,z
      - tempo_data:/var/tempo

  grafana:
    image: grafana/grafana:13.2.4
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_USER:?definir en .env}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:?definir en .env}
    ports: ["3000:3000"]
    volumes:
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro,z
      - ./monitoring/grafana/dashboards:/var/lib/grafana/dashboards:ro,z
      - grafana_data:/var/lib/grafana
    depends_on: [prometheus, loki, tempo, alertmanager]

# volumes: prometheus_data, loki_data, tempo_data, grafana_data
```

`monitoring/prometheus/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 30s

rule_files:
  - /etc/prometheus/rules/*.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]

scrape_configs:
  - job_name: orders-api          # = label job de las reglas SLO
    metrics_path: /metrics
    static_configs:
      - targets: ["backend:8000"]
```

`monitoring/loki.yml`

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
  allow_structured_metadata: true   # trace_id/span_id sin crear streams
  retention_period: 336h            # 14 días
compactor:
  working_directory: /loki/compactor
  retention_enabled: true
  delete_request_store: filesystem
```

## Tempo 3.x

Tempo 3 reemplazó el compactor de 2.x por `backend_scheduler` + `backend_worker`. Una config de 2.x con `compactor:` falla al arrancar con `field compactor not found in type app.Config`. La configuración efectiva se ve en `GET :3200/status/config`.

`monitoring/tempo.yml`

```yaml
server:
  http_listen_port: 3200
distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318
storage:
  trace:
    backend: local
    wal:
      path: /var/tempo/wal
    local:
      path: /var/tempo/blocks
# Tempo 3.x: el bloque `compactor:` de 2.x ya no existe ("field compactor not found").
# La retención se fija en el scheduler y en el worker; verificar en GET /status/config.
backend_scheduler:
  provider:
    compaction:
      compaction:
        block_retention: 168h       # 7 días
backend_worker:
  compaction:
    block_retention: 168h
metrics_generator:
  registry:
    external_labels:
      source: tempo
  storage:
    path: /var/tempo/generator/wal
    remote_write:
      - url: http://prometheus:9090/api/v1/write
        send_exemplars: true
overrides:
  defaults:
    metrics_generator:
      processors: [service-graphs, span-metrics]
```

## Grafana: datasources y dashboards

`uid` fijos: el dashboard y los saltos entre datasources los referencian. El derived field de Loki usa `matcherType: label` porque `trace_id` llega como structured metadata (no está dentro del texto de la línea).

`monitoring/grafana/provisioning/datasources/datasources.yml`

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
          matcherType: label          # trace_id llega como structured metadata
          matcherRegex: trace_id
          url: "$${__value.raw}"      # $$ escapa el $ en provisioning
          datasourceUid: tempo
          urlDisplayLabel: "Ver traza"
  - name: Tempo
    uid: tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    jsonData:
      tracesToLogsV2:
        datasourceUid: loki
        filterByTraceID: true
        spanStartTimeShift: "-5m"
        spanEndTimeShift: "5m"
      tracesToMetrics:
        datasourceUid: prometheus
      serviceMap:
        datasourceUid: prometheus
      nodeGraph:
        enabled: true
  - name: Alertmanager
    uid: alertmanager
    type: alertmanager
    access: proxy
    url: http://alertmanager:9093
    jsonData:
      implementation: prometheus
```

`monitoring/grafana/provisioning/dashboards/dashboards.yml`

```yaml
apiVersion: 1
providers:
  - name: default
    folder: ""
    type: file
    disableDeletion: true
    allowUiUpdates: false             # el dashboard se cambia en el script, no en la UI
    options:
      path: /var/lib/grafana/dashboards
```

## Verificación del stack

```bash
docker run --rm -v "$PWD/monitoring/loki.yml:/l.yml:ro,z" grafana/loki:3.7.9 -config.file=/l.yml -verify-config
docker run --rm -v "$PWD/monitoring/alloy:/a:ro,z" grafana/alloy:v1.21.2 validate /a/config.alloy
docker run --rm -v "$PWD/monitoring/prometheus:/p:ro,z" --entrypoint promtool prom/prometheus:v3.15.1 check config /p/prometheus.yml
docker run --rm -v "$PWD/monitoring/prometheus:/p:ro,z" -w /p/tests --entrypoint promtool prom/prometheus:v3.15.1 test rules orders-api-slo.test.yml
docker run --rm -v "$PWD/monitoring/alertmanager:/a:ro,z" --entrypoint amtool prom/alertmanager:v0.34.1 check-config /a/alertmanager.yml
docker compose up -d && curl -s localhost:3200/status/config | grep block_retention   # Tempo aplicó la retención
```

Prueba de punta a punta: generar tráfico (`/docs`) → Grafana → Explore → Loki `{service="backend"}` → abrir un log → *Ver traza* → en la traza, *Logs for this span* vuelve a Loki → el dashboard muestra tráfico, latencia y burn rate.
