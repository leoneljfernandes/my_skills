---
name: defining-grafana-slos
description: Use when defining SLIs/SLOs, error budgets and alerting for a service on the Prometheus/Grafana/Loki/Tempo stack - recording rules, multi-window multi-burn-rate alerts, Alertmanager routing/inhibition, standard Grafana dashboards as code, provisioning datasources, or the docker-compose monitoring stack - or when alerts are noisy, flapping, page for non-urgent issues, or dashboards are edited by hand and drift.
domain: observability
tags: [grafana, prometheus, alertmanager, slo, sli, error-budget, dashboards-as-code, loki, tempo]
triggers: [SLO, SLI, "error budget", "presupuesto de error", "burn rate", alertmanager, "alerting rules", "recording rules", promtool, Grafana, dashboard, provisioning, "alert fatigue", "on-call", runbook]
---

# SLOs, alertas y dashboards (Grafana stack)

Se alerta sobre **síntomas que sufre el usuario** (SLOs), no sobre causas (CPU, memoria). La alerta mide la velocidad a la que se consume el presupuesto de error (*burn rate*). Dashboards, reglas y datasources son código versionado y testeado.

## Contexto y reglas

**Cuándo aplica esta skill.** Solo si el despliegue tiene el stack Prometheus/Grafana/Loki/Tempo propio. En una plataforma con monitoreo nativo (p. ej. Vercel), definir los SLO sobre lo que esa plataforma expone: ver `vercel-index`.

**Volumen mínimo, riesgo previsto y sin validar.** El burn rate y alertas como "sin órdenes en 30 minutos" asumen tráfico constante. Con pocos pedidos por hora, un solo 500 puede consumir 14.4 veces el presupuesto y paginar, y de noche el "sin órdenes" dispara siempre. Antes de activar una alerta de este estilo: (a) exigir un volumen mínimo en la expresión (`sum(rate(http_requests_total{job="orders-api"}[1h])) > <umbral medido>`) y (b) limitar las alertas de ausencia al horario en que hay actividad. No se publican umbrales porque dependen del tráfico real del servicio; validar con datos propios al implementarlo.

**Hacer**

- Por servicio, 2 SLOs como mínimo en un archivo de reglas comentado:
  - **Disponibilidad**: % de requests sin 5xx (p. ej. 99.9 % en 30 días → presupuesto 0.1 %).
  - **Latencia**: % de requests bajo un umbral (p. ej. 99 % < 500 ms). El umbral debe coincidir con un bucket del histograma.
- **Recording rules** `sli:<métrica>:rate<ventana>` para cada ventana que usen las alertas (5m, 30m, 1h, 6h, 3d). Las alertas consultan series precomputadas. Agregan con `sum by (job)`: sin el `by`, el label `job` se pierde, dos servicios con los mismos nombres de `record` chocan y la inhibición por `job` no encuentra nada. Con `or 0 * ...` el SLI vale 0, no "sin datos", mientras no haya habido ningún 5xx.
- **Multi-window multi-burn-rate** (SRE Workbook, cap. 5):

  | Severidad | Burn rate | Ventana larga | Ventana corta | Presupuesto consumido |
  |---|---|---|---|---|
  | page | 14.4 | 1h | 5m | 2 % en 1 h |
  | page | 6 | 6h | 30m | 5 % en 6 h |
  | ticket | 1 | 3d | 6h | 10 % en 3 d |

  La ventana corta hace que la alerta se resuelva rápido cuando el problema termina.
- Toda alerta lleva `severity` (`page` | `ticket`), `summary`, `description` con el valor y `runbook_url`. Sin runbook no hay alerta. Cada SLO tiene sus tres alertas de la tabla (disponibilidad y latencia: `FastBurn`, `SlowBurn`, `TicketBurn`).
- **Alertmanager**: un receiver por severidad, `group_by` por `alertname`/`job`, **inhibición** (si `OrdersApiDown` está activa, no paginar también por burn rate del mismo `job`), y secretos de webhooks en archivos (`url_file`), no en el YAML.
- **Retención de Prometheus ≥ ventana del SLO** (`--storage.tsdb.retention.time=35d` para 30 días): con menos, "Disponibilidad 30d" y el presupuesto se calculan sobre menos días sin avisar.
- **Tests de reglas** con `promtool test rules`, en un directorio **separado** de `rules/`. Si el glob `rules/*.yml` de `prometheus.yml` los encuentra, Prometheus no arranca.
- **Dashboards como código**: script que genera el JSON (`templates/build_dashboard.py`), JSON versionado, provisioning con `allowUiUpdates: false`. Estructura estándar: Resumen → Tráfico/errores → Latencia → SLO disponibilidad (30d, presupuesto restante, burn rate) → SLO latencia → Recursos → Logs → Trazas. Los percentiles globales usan `http_request_duration_highr_seconds` (21 buckets, sin `handler`); el SLI de latencia y los percentiles por endpoint usan `http_request_duration_seconds` (ver `exposing-prometheus-metrics`).
- Datasources provisionados con `uid` fijos y correlación cruzada: Loki → Tempo (derived field sobre la structured metadata `trace_id`), Tempo → Loki (`tracesToLogsV2`), Prometheus → Tempo (exemplars), Tempo → Prometheus (service graph). Los exemplars existen solo en las métricas que genera Tempo (`traces_spanmetrics_*`, `traces_service_graph_*`), con el label `traceID`; `http_*` de la app no los tiene. El salto traza → logs usa una consulta propia por `trace_id` (ver references/stack.md), porque el `service` de Loki (nombre en compose) no es el `service.name` de la traza (`APP_NAME`).
- Imágenes con **tag fijo** y actualizaciones a propósito: Tempo 3.x cambió el formato de configuración respecto de 2.x (ver references/stack.md).

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| Alertar por `cpu > 80%` o "un 500" | ruido; páginas sin impacto en usuarios | burn rate sobre SLOs |
| Umbral fijo de error ratio con `for: 1m` | flapping, o páginas por blips de 30 s | multi-window multi-burn-rate |
| Alerta sin `runbook_url` ni `severity` | on-call sin saber qué hacer ni con qué urgencia | anotaciones obligatorias |
| Todo `severity: page` | fatiga; las páginas reales se ignoran | `ticket` para lo no urgente |
| Editar dashboards en la UI | se pierden en el próximo deploy; no hay revisión | script + JSON versionado |
| SLO de 100 % | ningún margen para deploys ni experimentos | 99.x % acordado con negocio |
| Reglas sin tests | expresiones que nunca disparan (o siempre) | `promtool test rules` en CI |

## Ejemplos

`monitoring/prometheus/rules/orders-api-slo.yml` (verificado a mano (2026-11-01, `promtool check rules` y `promtool test rules` en Prometheus 3.15.1): el bloque está completo y se copia tal cual):

```yaml
# SLOs de orders-api (ventana 30 días):
#   Disponibilidad: 99.9 % de requests sin 5xx      → presupuesto de error 0.1 %  (burn rate x 0.001)
#   Latencia:       99 % de requests en < 500 ms    → presupuesto 1 %             (burn rate x 0.01)
# Las series SLI llevan el label `job` (sum by (job)): un archivo por servicio no colisiona y la
# inhibición de Alertmanager (equal: [job]) funciona. `or 0 * ...` da 0 (no "sin datos") si nunca hubo un 5xx.
# El umbral de latencia `le="0.5"` tiene que coincidir con LATENCY_LE de build_dashboard.py (y con un bucket de
# http_request_duration_seconds); el 0.01 de las alertas de latencia, con 1 - LATENCY_TARGET; el 0.001, con 1 - SLO_TARGET.
groups:
  - name: orders-api-sli
    interval: 30s
    rules:
      - record: sli:http_error_ratio:rate5m
        expr: |
          (
            sum by (job) (rate(http_requests_total{job="orders-api",status="5xx"}[5m]))
            or 0 * sum by (job) (rate(http_requests_total{job="orders-api"}[5m]))
          )
          / clamp_min(sum by (job) (rate(http_requests_total{job="orders-api"}[5m])), 1e-9)
      - record: sli:http_error_ratio:rate30m
        expr: |
          (
            sum by (job) (rate(http_requests_total{job="orders-api",status="5xx"}[30m]))
            or 0 * sum by (job) (rate(http_requests_total{job="orders-api"}[30m]))
          )
          / clamp_min(sum by (job) (rate(http_requests_total{job="orders-api"}[30m])), 1e-9)
      - record: sli:http_error_ratio:rate1h
        expr: |
          (
            sum by (job) (rate(http_requests_total{job="orders-api",status="5xx"}[1h]))
            or 0 * sum by (job) (rate(http_requests_total{job="orders-api"}[1h]))
          )
          / clamp_min(sum by (job) (rate(http_requests_total{job="orders-api"}[1h])), 1e-9)
      - record: sli:http_error_ratio:rate6h
        expr: |
          (
            sum by (job) (rate(http_requests_total{job="orders-api",status="5xx"}[6h]))
            or 0 * sum by (job) (rate(http_requests_total{job="orders-api"}[6h]))
          )
          / clamp_min(sum by (job) (rate(http_requests_total{job="orders-api"}[6h])), 1e-9)
      - record: sli:http_error_ratio:rate3d
        expr: |
          (
            sum by (job) (rate(http_requests_total{job="orders-api",status="5xx"}[3d]))
            or 0 * sum by (job) (rate(http_requests_total{job="orders-api"}[3d]))
          )
          / clamp_min(sum by (job) (rate(http_requests_total{job="orders-api"}[3d])), 1e-9)
      - record: sli:http_latency_slow_ratio:rate5m
        expr: |
          (
            sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[5m]))
            - sum by (job) (rate(http_request_duration_seconds_bucket{job="orders-api",le="0.5"}[5m]))
          )
          / clamp_min(sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[5m])), 1e-9)
      - record: sli:http_latency_slow_ratio:rate30m
        expr: |
          (
            sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[30m]))
            - sum by (job) (rate(http_request_duration_seconds_bucket{job="orders-api",le="0.5"}[30m]))
          )
          / clamp_min(sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[30m])), 1e-9)
      - record: sli:http_latency_slow_ratio:rate1h
        expr: |
          (
            sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[1h]))
            - sum by (job) (rate(http_request_duration_seconds_bucket{job="orders-api",le="0.5"}[1h]))
          )
          / clamp_min(sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[1h])), 1e-9)
      - record: sli:http_latency_slow_ratio:rate6h
        expr: |
          (
            sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[6h]))
            - sum by (job) (rate(http_request_duration_seconds_bucket{job="orders-api",le="0.5"}[6h]))
          )
          / clamp_min(sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[6h])), 1e-9)
      - record: sli:http_latency_slow_ratio:rate3d
        expr: |
          (
            sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[3d]))
            - sum by (job) (rate(http_request_duration_seconds_bucket{job="orders-api",le="0.5"}[3d]))
          )
          / clamp_min(sum by (job) (rate(http_request_duration_seconds_count{job="orders-api"}[3d])), 1e-9)

  - name: orders-api-slo-alerts
    rules:
      # Disponibilidad. 14.4x durante 1h consume el 2 % del presupuesto mensual → página.
      - alert: OrdersApiErrorBudgetFastBurn
        expr: |
          sli:http_error_ratio:rate1h{job="orders-api"} > (14.4 * 0.001)
          and
          sli:http_error_ratio:rate5m{job="orders-api"} > (14.4 * 0.001)
        for: 2m
        labels:
          severity: page
          slo: availability
        annotations:
          summary: "orders-api quema el presupuesto de error 14x más rápido de lo sostenible"
          description: "Error ratio 1h = {{ $value | humanizePercentage }} (SLO 99.9 %)."
          runbook_url: "https://runbooks.example.com/orders-api/error-budget"
      # 6x durante 6h consume el 5 % del presupuesto → página.
      - alert: OrdersApiErrorBudgetSlowBurn
        expr: |
          sli:http_error_ratio:rate6h{job="orders-api"} > (6 * 0.001)
          and
          sli:http_error_ratio:rate30m{job="orders-api"} > (6 * 0.001)
        for: 15m
        labels:
          severity: page
          slo: availability
        annotations:
          summary: "orders-api quema el presupuesto de error de forma sostenida"
          description: "Error ratio 6h = {{ $value | humanizePercentage }} (SLO 99.9 %)."
          runbook_url: "https://runbooks.example.com/orders-api/error-budget"
      # 1x durante 3d consume el 10 % del presupuesto → ticket, no página.
      - alert: OrdersApiErrorBudgetTicketBurn
        expr: |
          sli:http_error_ratio:rate3d{job="orders-api"} > (1 * 0.001)
          and
          sli:http_error_ratio:rate6h{job="orders-api"} > (1 * 0.001)
        for: 1h
        labels:
          severity: ticket
          slo: availability
        annotations:
          summary: "orders-api consume el presupuesto de error al ritmo del SLO o más"
          description: "Error ratio 3d = {{ $value | humanizePercentage }} (SLO 99.9 %)."
          runbook_url: "https://runbooks.example.com/orders-api/error-budget"
      # Latencia: mismas ventanas y multiplicadores, sobre el presupuesto del 1 %.
      - alert: OrdersApiLatencyFastBurn
        expr: |
          sli:http_latency_slow_ratio:rate1h{job="orders-api"} > (14.4 * 0.01)
          and
          sli:http_latency_slow_ratio:rate5m{job="orders-api"} > (14.4 * 0.01)
        for: 2m
        labels:
          severity: page
          slo: latency
        annotations:
          summary: "orders-api: demasiadas requests lentas (> 500 ms), 14x el ritmo sostenible"
          description: "Requests > 500 ms en 1h = {{ $value | humanizePercentage }} (SLO: 99 % bajo 500 ms)."
          runbook_url: "https://runbooks.example.com/orders-api/latency"
      - alert: OrdersApiLatencySlowBurn
        expr: |
          sli:http_latency_slow_ratio:rate6h{job="orders-api"} > (6 * 0.01)
          and
          sli:http_latency_slow_ratio:rate30m{job="orders-api"} > (6 * 0.01)
        for: 15m
        labels:
          severity: page
          slo: latency
        annotations:
          summary: "orders-api: requests lentas (> 500 ms) de forma sostenida"
          description: "Requests > 500 ms en 6h = {{ $value | humanizePercentage }} (SLO: 99 % bajo 500 ms)."
          runbook_url: "https://runbooks.example.com/orders-api/latency"
      - alert: OrdersApiLatencyTicketBurn
        expr: |
          sli:http_latency_slow_ratio:rate3d{job="orders-api"} > (1 * 0.01)
          and
          sli:http_latency_slow_ratio:rate6h{job="orders-api"} > (1 * 0.01)
        for: 1h
        labels:
          severity: ticket
          slo: latency
        annotations:
          summary: "orders-api consume el presupuesto de latencia al ritmo del SLO o más"
          description: "Requests > 500 ms en 3d = {{ $value | humanizePercentage }} (SLO: 99 % bajo 500 ms)."
          runbook_url: "https://runbooks.example.com/orders-api/latency"
      - alert: OrdersApiDown
        expr: up{job="orders-api"} == 0
        for: 1m
        labels:
          severity: page
        annotations:
          summary: "Prometheus no puede scrapear orders-api ({{ $labels.instance }})"
          description: "up = {{ $value }} durante más de 1 minuto: la API no responde en /metrics."
          runbook_url: "https://runbooks.example.com/orders-api/down"
      # Negocio: la API responde 200 pero nadie compra → ticket, no página.
      - alert: OrdersApiNoOrders
        expr: sum by (job) (increase(shop_orders_created_total{job="orders-api"}[30m])) == 0
        for: 30m
        labels:
          severity: ticket
        annotations:
          summary: "No se creó ninguna orden en los últimos 30 minutos"
          description: "shop_orders_created_total no subió en 30 minutos (job {{ $labels.job }})."
          runbook_url: "https://runbooks.example.com/orders-api/no-orders"
```

`monitoring/prometheus/tests/orders-api-slo.test.yml` (un caso que dispara y otro que no por cada alerta; los de 3 días tardan unos 40 s):

```yaml
rule_files:
  - ../rules/orders-api-slo.yml
evaluation_interval: 30s
tests:
  # Disponibilidad, 5 % de errores sostenidos (fast burn: umbral 1.44 %) → página. La API está arriba.
  - interval: 30s
    input_series:
      - series: 'http_requests_total{job="orders-api",status="2xx"}'
        values: '0+95x240'
      - series: 'http_requests_total{job="orders-api",status="5xx"}'
        values: '0+5x240'
      - series: 'up{job="orders-api",instance="backend:8000"}'
        values: '1x240'
    alert_rule_test:
      - eval_time: 70m
        alertname: OrdersApiErrorBudgetFastBurn
        exp_alerts:
          - exp_labels: {job: orders-api, severity: page, slo: availability}
            exp_annotations:
              summary: "orders-api quema el presupuesto de error 14x más rápido de lo sostenible"
              description: "Error ratio 1h = 5% (SLO 99.9 %)."
              runbook_url: "https://runbooks.example.com/orders-api/error-budget"
      - eval_time: 70m
        alertname: OrdersApiDown
        exp_alerts: []
  # Latencia: 20 % de las requests por encima de 500 ms (fast burn: umbral 14.4 %) → página.
  - interval: 30s
    input_series:
      - series: 'http_request_duration_seconds_count{job="orders-api"}'
        values: '0+100x240'
      - series: 'http_request_duration_seconds_bucket{job="orders-api",le="0.5"}'
        values: '0+80x240'
    alert_rule_test:
      - eval_time: 70m
        alertname: OrdersApiLatencyFastBurn
        exp_alerts:
          - exp_labels: {job: orders-api, severity: page, slo: latency}
            exp_annotations:
              summary: "orders-api: demasiadas requests lentas (> 500 ms), 14x el ritmo sostenible"
              description: "Requests > 500 ms en 1h = 20% (SLO: 99 % bajo 500 ms)."
              runbook_url: "https://runbooks.example.com/orders-api/latency"
  # Burn lento, 7 h: 1 % de errores (> 0.6 %, < 1.44 %) y 8 % de requests lentas (> 6 %, < 14.4 %).
  # Dispara solo las alertas slow; las fast quedan quietas.
  - interval: 30s
    input_series:
      - series: 'http_requests_total{job="orders-api",status="2xx"}'
        values: '0+99x840'
      - series: 'http_requests_total{job="orders-api",status="5xx"}'
        values: '0+1x840'
      - series: 'http_request_duration_seconds_count{job="orders-api"}'
        values: '0+100x840'
      - series: 'http_request_duration_seconds_bucket{job="orders-api",le="0.5"}'
        values: '0+92x840'
    alert_rule_test:
      - eval_time: 7h
        alertname: OrdersApiErrorBudgetSlowBurn
        exp_alerts:
          - exp_labels: {job: orders-api, severity: page, slo: availability}
            exp_annotations:
              summary: "orders-api quema el presupuesto de error de forma sostenida"
              description: "Error ratio 6h = 1% (SLO 99.9 %)."
              runbook_url: "https://runbooks.example.com/orders-api/error-budget"
      - eval_time: 7h
        alertname: OrdersApiLatencySlowBurn
        exp_alerts:
          - exp_labels: {job: orders-api, severity: page, slo: latency}
            exp_annotations:
              summary: "orders-api: requests lentas (> 500 ms) de forma sostenida"
              description: "Requests > 500 ms en 6h = 8% (SLO: 99 % bajo 500 ms)."
              runbook_url: "https://runbooks.example.com/orders-api/latency"
      - eval_time: 7h
        alertname: OrdersApiErrorBudgetFastBurn
        exp_alerts: []
      - eval_time: 7h
        alertname: OrdersApiLatencyFastBurn
        exp_alerts: []
  # Burn de 3 días: 0.2 % de errores (> 0.1 %, < 0.6 %) y 1.5 % de requests lentas (> 1 %, < 6 %)
  # → solo los ticket. Las alertas de página no se activan.
  - interval: 30s
    input_series:
      - series: 'http_requests_total{job="orders-api",status="2xx"}'
        values: '0+998x9000'
      - series: 'http_requests_total{job="orders-api",status="5xx"}'
        values: '0+2x9000'
      - series: 'http_request_duration_seconds_count{job="orders-api"}'
        values: '0+200x9000'
      - series: 'http_request_duration_seconds_bucket{job="orders-api",le="0.5"}'
        values: '0+197x9000'
    alert_rule_test:
      - eval_time: 3d6h
        alertname: OrdersApiErrorBudgetTicketBurn
        exp_alerts:
          - exp_labels: {job: orders-api, severity: ticket, slo: availability}
            exp_annotations:
              summary: "orders-api consume el presupuesto de error al ritmo del SLO o más"
              description: "Error ratio 3d = 0.2% (SLO 99.9 %)."
              runbook_url: "https://runbooks.example.com/orders-api/error-budget"
      - eval_time: 3d6h
        alertname: OrdersApiLatencyTicketBurn
        exp_alerts:
          - exp_labels: {job: orders-api, severity: ticket, slo: latency}
            exp_annotations:
              summary: "orders-api consume el presupuesto de latencia al ritmo del SLO o más"
              description: "Requests > 500 ms en 3d = 1.5% (SLO: 99 % bajo 500 ms)."
              runbook_url: "https://runbooks.example.com/orders-api/latency"
      - eval_time: 3d6h
        alertname: OrdersApiErrorBudgetSlowBurn
        exp_alerts: []
      - eval_time: 3d6h
        alertname: OrdersApiLatencySlowBurn
        exp_alerts: []
  # Dentro del SLO durante 3 días (0.05 % de errores, 0.5 % de requests lentas): no dispara nada.
  - interval: 30s
    input_series:
      - series: 'http_requests_total{job="orders-api",status="2xx"}'
        values: '0+1999x9000'
      - series: 'http_requests_total{job="orders-api",status="5xx"}'
        values: '0+1x9000'
      - series: 'http_request_duration_seconds_count{job="orders-api"}'
        values: '0+200x9000'
      - series: 'http_request_duration_seconds_bucket{job="orders-api",le="0.5"}'
        values: '0+199x9000'
    alert_rule_test:
      - eval_time: 3d6h
        alertname: OrdersApiErrorBudgetFastBurn
        exp_alerts: []
      - eval_time: 3d6h
        alertname: OrdersApiErrorBudgetSlowBurn
        exp_alerts: []
      - eval_time: 3d6h
        alertname: OrdersApiErrorBudgetTicketBurn
        exp_alerts: []
      - eval_time: 3d6h
        alertname: OrdersApiLatencyFastBurn
        exp_alerts: []
      - eval_time: 3d6h
        alertname: OrdersApiLatencySlowBurn
        exp_alerts: []
      - eval_time: 3d6h
        alertname: OrdersApiLatencyTicketBurn
        exp_alerts: []
  # Servicio sano sin ningún 5xx (la serie no existe) y en reposo (contadores quietos): los SLI valen 0,
  # no "sin datos" ni 1.
  - interval: 30s
    input_series:
      - series: 'http_requests_total{job="orders-api",status="2xx"}'
        values: '0+100x240'
      - series: 'http_request_duration_seconds_count{job="orders-api"}'
        values: '500x240'
      - series: 'http_request_duration_seconds_bucket{job="orders-api",le="0.5"}'
        values: '500x240'
    promql_expr_test:
      - expr: sli:http_error_ratio:rate1h
        eval_time: 70m
        exp_samples:
          - labels: 'sli:http_error_ratio:rate1h{job="orders-api"}'
            value: 0
      - expr: sli:http_latency_slow_ratio:rate5m
        eval_time: 70m
        exp_samples:
          - labels: 'sli:http_latency_slow_ratio:rate5m{job="orders-api"}'
            value: 0
  # La API cae: OrdersApiDown dispara (página).
  - interval: 30s
    input_series:
      - series: 'up{job="orders-api",instance="backend:8000"}'
        values: '1x20 0x40'
    alert_rule_test:
      - eval_time: 25m
        alertname: OrdersApiDown
        exp_alerts:
          - exp_labels: {job: orders-api, instance: "backend:8000", severity: page}
            exp_annotations:
              summary: "Prometheus no puede scrapear orders-api (backend:8000)"
              description: "up = 0 durante más de 1 minuto: la API no responde en /metrics."
              runbook_url: "https://runbooks.example.com/orders-api/down"
  # Negocio: sin órdenes durante 1 h → ticket; con órdenes, no.
  - interval: 30s
    input_series:
      - series: 'shop_orders_created_total{job="orders-api"}'
        values: '5x240'
    alert_rule_test:
      - eval_time: 70m
        alertname: OrdersApiNoOrders
        exp_alerts:
          - exp_labels: {job: orders-api, severity: ticket}
            exp_annotations:
              summary: "No se creó ninguna orden en los últimos 30 minutos"
              description: "shop_orders_created_total no subió en 30 minutos (job orders-api)."
              runbook_url: "https://runbooks.example.com/orders-api/no-orders"
  - interval: 30s
    input_series:
      - series: 'shop_orders_created_total{job="orders-api"}'
        values: '0+1x240'
    alert_rule_test:
      - eval_time: 70m
        alertname: OrdersApiNoOrders
        exp_alerts: []
```

`monitoring/alertmanager/alertmanager.yml` (verificado a mano (2026-11-01, `amtool check-config` y una inhibición real contra Alertmanager 0.34.1: la página de burn rate del mismo `job` queda suprimida; la de otro `job`, no)):

```yaml
global:
  resolve_timeout: 5m

route:
  receiver: team-backend-ticket          # default: nada queda sin dueño
  group_by: [alertname, job, slo]
  group_wait: 30s                        # agrupa la ráfaga inicial
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - matchers: [severity="page"]
      receiver: team-backend-oncall
      repeat_interval: 1h
    - matchers: [severity="ticket"]
      receiver: team-backend-ticket
      repeat_interval: 24h

inhibit_rules:
  # Si la API está caída, no sumar páginas de burn-rate/latencia del mismo job.
  - source_matchers: [alertname="OrdersApiDown"]
    target_matchers: [severity="page"]
    equal: [job]

receivers:
  - name: team-backend-oncall
    webhook_configs:
      - url_file: /etc/alertmanager/secrets/oncall_webhook_url   # secreto fuera del YAML
        send_resolved: true
  - name: team-backend-ticket
    webhook_configs:
      - url_file: /etc/alertmanager/secrets/ticket_webhook_url
        send_resolved: false
```

Dashboard como código: copiar [build_dashboard.py](templates/build_dashboard.py) a `monitoring/`, ajustar `SERVICE`/`JOB`/`LOG_SERVICE`/`TITLE`/`SLO_TARGET`/`LATENCY_TARGET`/`LATENCY_LE` y versionar el JSON generado. `SLO_TARGET`, `LATENCY_TARGET` y `LATENCY_LE` tienen que coincidir con el archivo de reglas (`0.001`, `0.01` y `le="0.5"` en el ejemplo): el dashboard calcula el presupuesto con ellos. El stack completo (compose, Prometheus, Loki, Tempo 3, provisioning de Grafana) está en [references/stack.md](references/stack.md).

```bash
python3 monitoring/build_dashboard.py                       # regenera grafana/dashboards/<service>.json
# Montado en /etc/prometheus: el glob absoluto de rule_files lo encuentra y `check config` valida también las reglas.
docker run --rm -v "$PWD/monitoring/prometheus:/etc/prometheus:ro,z" --entrypoint promtool prom/prometheus:v3.15.1 check config /etc/prometheus/prometheus.yml
docker run --rm -v "$PWD/monitoring/prometheus:/etc/prometheus:ro,z" -w /etc/prometheus/tests --entrypoint promtool prom/prometheus:v3.15.1 test rules orders-api-slo.test.yml
docker run --rm -v "$PWD/monitoring/alertmanager:/a:ro,z" --entrypoint amtool prom/alertmanager:v0.34.1 check-config /a/alertmanager.yml
```

## Checklist de verificación

- [ ] Cada servicio tiene SLO de disponibilidad y de latencia documentados en el archivo de reglas, cada uno con sus alertas `FastBurn`, `SlowBurn` y `TicketBurn`.
- [ ] La retención de Prometheus es mayor o igual que la ventana del SLO (35 d para 30 d).
- [ ] `promtool check config`, `promtool test rules` y `amtool check-config` pasan en CI.
- [ ] Hay un test que dispara cada alerta y otro que verifica que el tráfico dentro del SLO **no** alerta; las series SLI conservan `job` (con dos servicios no hay `duplicate sample`).
- [ ] Toda alerta tiene `severity`, `summary`, `description` y un `runbook_url` que existe.
- [ ] El dashboard se genera por script, está versionado y el provisioning tiene `allowUiUpdates: false`.
- [ ] En Grafana: log → *Ver traza* abre Tempo; traza → *Logs for this span* abre Loki; el panel de burn rate muestra datos.
- [ ] Las imágenes del stack tienen tag fijo, no `latest`.

## Skills relacionadas

- `exposing-prometheus-metrics`: las métricas sobre las que se calculan los SLIs.
- `logging-json-to-loki`, `tracing-with-opentelemetry`: las otras dos señales.
