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

**Hacer**

- Por servicio, 2 SLOs como mínimo en un archivo de reglas comentado:
  - **Disponibilidad**: % de requests sin 5xx (p. ej. 99.9 % en 30 días → presupuesto 0.1 %).
  - **Latencia**: % de requests bajo un umbral (p. ej. 99 % < 500 ms). El umbral debe coincidir con un bucket del histograma.
- **Recording rules** `sli:<métrica>:rate<ventana>` para cada ventana que usen las alertas (5m, 30m, 1h, 6h). Las alertas consultan series precomputadas.
- **Multi-window multi-burn-rate** (SRE Workbook, cap. 5):

  | Severidad | Burn rate | Ventana larga | Ventana corta | Presupuesto consumido |
  |---|---|---|---|---|
  | page | 14.4 | 1h | 5m | 2 % en 1 h |
  | page | 6 | 6h | 30m | 5 % en 6 h |
  | ticket | 1 | 3d | 6h | 10 % en 3 d |

  La ventana corta hace que la alerta se resuelva rápido cuando el problema termina.
- Toda alerta lleva `severity` (`page` | `ticket`), `summary`, `description` con el valor y `runbook_url`. Sin runbook no hay alerta.
- **Alertmanager**: un receiver por severidad, `group_by` por `alertname`/`job`, **inhibición** (si `ServiceDown` está activa, no paginar también por burn rate), y secretos de webhooks en archivos (`url_file`), no en el YAML.
- **Tests de reglas** con `promtool test rules`, en un directorio **separado** de `rules/`. Si el glob `rules/*.yml` de `prometheus.yml` los encuentra, Prometheus no arranca.
- **Dashboards como código**: script que genera el JSON (`templates/build_dashboard.py`), JSON versionado, provisioning con `allowUiUpdates: false`. Estructura estándar: Resumen → Tráfico/errores → Latencia → SLO (disponibilidad 30d, presupuesto restante, burn rate) → Recursos → Logs → Trazas.
- Datasources provisionados con `uid` fijos y correlación cruzada: Loki → Tempo (derived field sobre la structured metadata `trace_id`), Tempo → Loki (`tracesToLogsV2`), Prometheus → Tempo (exemplars), Tempo → Prometheus (service graph).
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

`monitoring/prometheus/rules/orders-api-slo.yml` (verificado: `promtool check rules` y `promtool test rules` pasan en Prometheus 3.15.1):

```yaml
# SLOs de orders-api (ventana 30 días):
#   Disponibilidad: 99.9 % de requests sin 5xx      → presupuesto de error 0.1 %
#   Latencia:       99 % de requests en < 500 ms    → presupuesto 1 %
groups:
  - name: orders-api-sli
    interval: 30s
    rules:
      - record: sli:http_error_ratio:rate5m
        expr: |
          sum(rate(http_requests_total{job="orders-api",status="5xx"}[5m]))
          / clamp_min(sum(rate(http_requests_total{job="orders-api"}[5m])), 1e-9)
      # … idem rate30m, rate1h, rate6h (misma expresión, otra ventana)
      - record: sli:http_latency_slow_ratio:rate5m
        expr: |
          1 - (
            sum(rate(http_request_duration_seconds_bucket{job="orders-api",le="0.5"}[5m]))
            / clamp_min(sum(rate(http_request_duration_seconds_count{job="orders-api"}[5m])), 1e-9)
          )
      # … idem rate1h

  - name: orders-api-slo-alerts
    rules:
      # 14.4x durante 1h consume el 2 % del presupuesto mensual → página.
      - alert: OrdersApiErrorBudgetFastBurn
        expr: |
          sli:http_error_ratio:rate1h > (14.4 * 0.001)
          and
          sli:http_error_ratio:rate5m > (14.4 * 0.001)
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
          sli:http_error_ratio:rate6h > (6 * 0.001)
          and
          sli:http_error_ratio:rate30m > (6 * 0.001)
        for: 15m
        labels:
          severity: page
          slo: availability
        annotations:
          summary: "orders-api quema el presupuesto de error de forma sostenida"
          description: "Error ratio 6h = {{ $value | humanizePercentage }} (SLO 99.9 %)."
          runbook_url: "https://runbooks.example.com/orders-api/error-budget"
      - alert: OrdersApiDown
        expr: up{job="orders-api"} == 0
        for: 1m
        labels:
          severity: page
        annotations:
          summary: "Prometheus no puede scrapear orders-api ({{ $labels.instance }})"
          runbook_url: "https://runbooks.example.com/orders-api/down"
      # Negocio: la API responde 200 pero nadie compra → ticket, no página.
      - alert: OrdersApiNoOrders
        expr: sum(increase(shop_orders_created_total{job="orders-api"}[30m])) == 0
        for: 30m
        labels:
          severity: ticket
        annotations:
          summary: "No se creó ninguna orden en la última hora"
          runbook_url: "https://runbooks.example.com/orders-api/no-orders"
```

`monitoring/prometheus/tests/orders-api-slo.test.yml`:

```yaml
rule_files:
  - ../rules/orders-api-slo.yml
evaluation_interval: 30s
tests:
  # 5 % de errores sostenidos → fast burn (umbral 1.44 %) debe disparar.
  - interval: 30s
    input_series:
      - series: 'http_requests_total{job="orders-api",status="2xx"}'
        values: '0+95x240'
      - series: 'http_requests_total{job="orders-api",status="5xx"}'
        values: '0+5x240'
      - series: 'up{job="orders-api",instance="api:8000"}'
        values: '1x240'
    alert_rule_test:
      - eval_time: 70m
        alertname: OrdersApiErrorBudgetFastBurn
        exp_alerts:
          - exp_labels: {severity: page, slo: availability}
            exp_annotations:
              summary: "orders-api quema el presupuesto de error 14x más rápido de lo sostenible"
              description: "Error ratio 1h = 5% (SLO 99.9 %)."
              runbook_url: "https://runbooks.example.com/orders-api/error-budget"
      - eval_time: 70m
        alertname: OrdersApiDown
        exp_alerts: []
  # 0.05 % de errores (dentro del SLO) → no dispara nada.
  - interval: 30s
    input_series:
      - series: 'http_requests_total{job="orders-api",status="2xx"}'
        values: '0+1999x240'
      - series: 'http_requests_total{job="orders-api",status="5xx"}'
        values: '0+1x240'
    alert_rule_test:
      - eval_time: 70m
        alertname: OrdersApiErrorBudgetFastBurn
        exp_alerts: []
```

`monitoring/alertmanager/alertmanager.yml` (verificado con `amtool check-config`):

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

Dashboard como código: copiar [build_dashboard.py](templates/build_dashboard.py) a `monitoring/`, ajustar `SERVICE`/`JOB`/`LOG_SERVICE`/`SLO_TARGET` y versionar el JSON generado. El stack completo (compose, Prometheus, Loki, Tempo 3, provisioning de Grafana) está en [references/stack.md](references/stack.md).

```bash
python3 monitoring/build_dashboard.py                       # regenera grafana/dashboards/<service>.json
docker run --rm -v "$PWD/monitoring/prometheus:/p:ro,z" --entrypoint promtool prom/prometheus:v3.15.1 check config /p/prometheus.yml
docker run --rm -v "$PWD/monitoring/prometheus:/p:ro,z" -w /p/tests --entrypoint promtool prom/prometheus:v3.15.1 test rules orders-api-slo.test.yml
docker run --rm -v "$PWD/monitoring/alertmanager:/a:ro,z" --entrypoint amtool prom/alertmanager:v0.34.1 check-config /a/alertmanager.yml
```

## Checklist de verificación

- [ ] Cada servicio tiene SLO de disponibilidad y de latencia documentados en el archivo de reglas.
- [ ] `promtool check config`, `promtool test rules` y `amtool check-config` pasan en CI.
- [ ] Hay un test que dispara el fast-burn y otro que verifica que el tráfico dentro del SLO **no** alerta.
- [ ] Toda alerta tiene `severity`, `summary` y un `runbook_url` que existe.
- [ ] El dashboard se genera por script, está versionado y el provisioning tiene `allowUiUpdates: false`.
- [ ] En Grafana: log → *Ver traza* abre Tempo; traza → *Logs for this span* abre Loki; el panel de burn rate muestra datos.
- [ ] Las imágenes del stack tienen tag fijo, no `latest`.

## Skills relacionadas

- `exposing-prometheus-metrics`: las métricas sobre las que se calculan los SLIs.
- `logging-json-to-loki`, `tracing-with-opentelemetry`: las otras dos señales.
