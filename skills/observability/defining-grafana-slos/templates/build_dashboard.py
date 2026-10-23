"""Genera monitoring/grafana/dashboards/<SERVICE>.json (dashboard provisionado en Grafana).

Uso: ajustar SERVICE / JOB / LOG_SERVICE / TITLE y correr `python3 monitoring/build_dashboard.py`.
Versionar el JSON generado. Para cambiar el dashboard se edita este script, no la UI.
Requiere logs JSON con `level` como label y `trace_id` como structured metadata (skill logging-json-to-loki).
"""
import json
from pathlib import Path

SERVICE = "orders-api"        # = service.name de OpenTelemetry (APP_NAME)
JOB = "orders-api"            # = job_name del scrape en prometheus.yml
LOG_SERVICE = "backend"       # = label `service` que Alloy toma del servicio de docker-compose
TITLE = "Orders API - Observabilidad"

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
TEMPO = {"type": "tempo", "uid": "tempo"}
SEL = f'job="{JOB}"'
panels, pid = [], 0


def add(kind, title, x, y, w, h, targets, ds=PROM, unit=None, options=None, extra=None):
    global pid
    pid += 1
    p = {
        "id": pid, "type": kind, "title": title, "datasource": ds,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [dict(t, datasource=ds, refId=chr(65 + i)) for i, t in enumerate(targets)],
        "fieldConfig": {"defaults": {"unit": unit} if unit else {}, "overrides": []},
        "options": options or {},
    }
    if extra:
        p.update(extra)
    panels.append(p)


def row(title, y):
    global pid
    pid += 1
    panels.append({"id": pid, "type": "row", "title": title, "collapsed": False,
                   "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []})


def q(expr, legend=""):
    return {"expr": expr, "legendFormat": legend}


# --- Resumen ---
row("Resumen", 0)
stat = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value"}
add("stat", "Requests/s", 0, 1, 6, 4, [q(f'sum(rate(http_requests_total{{{SEL}}}[1m]))')], unit="reqps", options=stat)
add("stat", "Errores 5xx (%)", 6, 1, 6, 4,
    [q(f'100 * sum(rate(http_requests_total{{{SEL},status="5xx"}}[5m])) / sum(rate(http_requests_total{{{SEL}}}[5m]))')],
    unit="percent", options=stat,
    extra={"fieldConfig": {"defaults": {"unit": "percent", "thresholds": {"mode": "absolute", "steps": [
        {"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 5}]},
        "color": {"mode": "thresholds"}}, "overrides": []}})
add("stat", "Latencia p95", 12, 1, 6, 4,
    [q(f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{SEL}}}[5m])))')],
    unit="s", options=stat)
add("stat", "Requests totales", 18, 1, 6, 4, [q(f'sum(http_requests_total{{{SEL}}})')], unit="short", options=stat)

# --- Tráfico ---
row("Tráfico y errores", 5)
ts = {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "max"]}}
add("timeseries", "Requests/s por endpoint", 0, 6, 12, 8,
    [q(f'sum by (method, handler) (rate(http_requests_total{{{SEL}}}[1m]))', "{{method}} {{handler}}")], unit="reqps", options=ts)
add("timeseries", "Requests/s por código de estado", 12, 6, 12, 8,
    [q(f'sum by (status) (rate(http_requests_total{{{SEL}}}[1m]))', "{{status}}")], unit="reqps", options=ts)

# --- Latencia ---
row("Latencia", 14)
hist = 'http_request_duration_seconds_bucket'
add("timeseries", "Latencia p50 / p95 / p99", 0, 15, 12, 8, [
    q(f'histogram_quantile(0.50, sum by (le) (rate({hist}{{{SEL}}}[5m])))', "p50"),
    q(f'histogram_quantile(0.95, sum by (le) (rate({hist}{{{SEL}}}[5m])))', "p95"),
    q(f'histogram_quantile(0.99, sum by (le) (rate({hist}{{{SEL}}}[5m])))', "p99")], unit="s", options=ts)
add("timeseries", "Latencia p95 por endpoint", 12, 15, 12, 8,
    [q(f'histogram_quantile(0.95, sum by (le, handler) (rate({hist}{{{SEL}}}[5m])))', "{{handler}}")], unit="s", options=ts)

# --- Recursos ---
row("Recursos del proceso", 23)
add("timeseries", "CPU (cores)", 0, 24, 8, 7, [q('rate(process_cpu_seconds_total[1m])', "cpu")], unit="short")
add("timeseries", "Memoria residente", 8, 24, 8, 7, [q('process_resident_memory_bytes', "rss")], unit="bytes")
add("timeseries", "Archivos abiertos", 16, 24, 8, 7, [q('process_open_fds', "fds")], unit="short")

# --- Logs ---
row("Logs (Loki)", 31)
add("timeseries", "Volumen de logs por nivel", 0, 32, 24, 5,
    [{"expr": 'sum by (level) (count_over_time({service="%s"}[1m]))' % LOG_SERVICE,
      "legendFormat": "{{level}}"}], ds=LOKI, unit="short", options=ts)
add("logs", "Logs del backend", 0, 37, 24, 10,
    [{"expr": '{service="%s"} |~ "(?i)$search" | json' % LOG_SERVICE}], ds=LOKI,
    options={"showTime": True, "wrapLogMessage": True, "enableLogDetails": True, "sortOrder": "Descending"})
add("logs", "Solo errores (backend)", 0, 47, 24, 8,
    [{"expr": '{service="%s", level=~"error|critical"} | json' % LOG_SERVICE}], ds=LOKI,
    options={"showTime": True, "wrapLogMessage": True, "enableLogDetails": True})

# --- Trazas ---
row("Trazas (Tempo)", 55)
add("table", "Trazas recientes", 0, 56, 24, 10,
    [{"queryType": "traceqlSearch", "limit": 20, "tableType": "traces",
      "filters": [{"id": "service-name", "tag": "service.name", "operator": "=", "scope": "resource",
                   "value": [SERVICE], "valueType": "string"}]}], ds=TEMPO)
add("table", "Trazas lentas (> 500ms)", 0, 66, 24, 8,
    [{"queryType": "traceql", "query": '{ resource.service.name = "%s" && duration > 500ms }' % SERVICE,
      "limit": 20, "tableType": "traces"}], ds=TEMPO)

# --- SLO (requiere las recording rules de monitoring/prometheus/rules/*-slo.yml) ---
SLO_TARGET = 0.999  # disponibilidad 30 días; presupuesto de error = 1 - SLO_TARGET
BUDGET = 1 - SLO_TARGET
row("SLO disponibilidad (30 días)", 74)
ratio_30d = (f'sum(increase(http_requests_total{{{SEL},status="5xx"}}[30d])) '
             f'/ clamp_min(sum(increase(http_requests_total{{{SEL}}}[30d])), 1e-9)')
add("stat", "Disponibilidad 30d", 0, 75, 8, 4, [q(f"1 - ({ratio_30d})")], unit="percentunit", options=stat,
    extra={"fieldConfig": {"defaults": {"unit": "percentunit", "decimals": 3, "thresholds": {"mode": "absolute", "steps": [
        {"color": "red", "value": None}, {"color": "green", "value": SLO_TARGET}]},
        "color": {"mode": "thresholds"}}, "overrides": []}})
add("stat", "Presupuesto de error restante", 8, 75, 8, 4, [q(f"1 - (({ratio_30d}) / {BUDGET})")],
    unit="percentunit", options=stat,
    extra={"fieldConfig": {"defaults": {"unit": "percentunit", "thresholds": {"mode": "absolute", "steps": [
        {"color": "red", "value": None}, {"color": "orange", "value": 0.25}, {"color": "green", "value": 0.5}]},
        "color": {"mode": "thresholds"}}, "overrides": []}})
add("timeseries", "Burn rate (1 = consumo sostenible)", 16, 75, 8, 8, [
    q(f"sli:http_error_ratio:rate1h / {BUDGET}", "1h"),
    q(f"sli:http_error_ratio:rate6h / {BUDGET}", "6h")], unit="short", options=ts,
    extra={"fieldConfig": {"defaults": {"custom": {"thresholdsStyle": {"mode": "line"}},
        "thresholds": {"mode": "absolute", "steps": [
            {"color": "green", "value": None}, {"color": "orange", "value": 6}, {"color": "red", "value": 14.4}]}},
        "overrides": []}})

dashboard = {
    "uid": SERVICE, "title": TITLE,
    "tags": ["fastapi", "observability", "slo"], "timezone": "browser", "schemaVersion": 39,
    "version": 1, "refresh": "10s", "time": {"from": "now-30m", "to": "now"},
    "templating": {"list": [{"name": "search", "label": "Buscar en logs", "type": "textbox",
                             "query": "", "current": {"value": "", "text": ""}}]},
    "panels": panels,
}
out = Path(__file__).parent / "grafana" / "dashboards" / f"{SERVICE}.json"
out.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
print(out)
