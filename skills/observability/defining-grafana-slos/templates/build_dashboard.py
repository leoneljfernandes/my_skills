"""Genera monitoring/grafana/dashboards/<SERVICE>.json (dashboard provisionado en Grafana).

Uso: ajustar SERVICE / JOB / LOG_SERVICE / TITLE / SLO_TARGET / LATENCY_TARGET / LATENCY_LE y correr
`python3 monitoring/build_dashboard.py`. SLO_TARGET, LATENCY_TARGET y LATENCY_LE tienen que coincidir con las
reglas de monitoring/prometheus/rules/<servicio>-slo.yml (presupuestos 1 - objetivo y el `le` del SLI de latencia).
Versionar el JSON generado. Para cambiar el dashboard se edita este script, no la UI.
Requiere logs JSON con `level` como label y `trace_id` como structured metadata (skill logging-json-to-loki)
y las recording rules de monitoring/prometheus/rules/<servicio>-slo.yml.
"""
import json
from pathlib import Path

SERVICE = "orders-api"        # = service.name de OpenTelemetry (APP_NAME)
JOB = "orders-api"            # = job_name del scrape en prometheus.yml
LOG_SERVICE = "backend"       # = label `service` que Alloy toma del servicio de docker-compose
TITLE = "Orders API - Observabilidad"
SLO_TARGET = 0.999            # disponibilidad 30 días; presupuesto de error = 1 - SLO_TARGET
LATENCY_TARGET = 0.99         # 99 % de las requests bajo LATENCY_LE segundos
LATENCY_LE = "0.5"            # tiene que ser un bucket de http_request_duration_seconds

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
TEMPO = {"type": "tempo", "uid": "tempo"}
SEL = f'job="{JOB}"'
BUDGET = round(1 - SLO_TARGET, 6)
LATENCY_BUDGET = round(1 - LATENCY_TARGET, 6)
panels, pid, cursor = [], 0, 0  # cursor = fila (y) de lo próximo: las filas se apilan en el orden del código


def add(kind, title, x, w, h, targets, ds=PROM, unit=None, options=None, extra=None):
    global pid
    pid += 1
    p = {
        "id": pid, "type": kind, "title": title, "datasource": ds,
        "gridPos": {"x": x, "y": cursor, "w": w, "h": h},
        "targets": [dict(t, datasource=ds, refId=chr(65 + i)) for i, t in enumerate(targets)],
        "fieldConfig": {"defaults": {"unit": unit} if unit else {}, "overrides": []},
        "options": options or {},
    }
    if extra:
        p.update(extra)
    panels.append(p)


def row(title):
    global pid, cursor
    pid += 1
    panels.append({"id": pid, "type": "row", "title": title, "collapsed": False,
                   "gridPos": {"x": 0, "y": cursor, "w": 24, "h": 1}, "panels": []})
    cursor += 1


def band(h):
    """Cierra una banda de paneles de alto h: lo que sigue va debajo."""
    global cursor
    cursor += h


def q(expr, legend=""):
    return {"expr": expr, "legendFormat": legend}


def with_zero(bad, total):
    """`bad` vale 0 (no "sin datos") mientras no haya habido ningún 5xx: el Instrumentator crea cada status al verlo."""
    return f"({bad} or 0 * {total})"


def thresholds(*steps, unit, decimals=None):
    d = {"unit": unit, "thresholds": {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]},
         "color": {"mode": "thresholds"}}
    if decimals is not None:
        d["decimals"] = decimals
    return {"fieldConfig": {"defaults": d, "overrides": []}}


burn_lines = {"fieldConfig": {"defaults": {"custom": {"thresholdsStyle": {"mode": "line"}},
    "thresholds": {"mode": "absolute", "steps": [
        {"color": "green", "value": None}, {"color": "orange", "value": 6}, {"color": "red", "value": 14.4}]}},
    "overrides": []}}

# --- Resumen ---
row("Resumen")
stat = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value"}
errors_5xx = with_zero(f'sum(rate(http_requests_total{{{SEL},status="5xx"}}[5m]))',
                       f'sum(rate(http_requests_total{{{SEL}}}[5m]))')
add("stat", "Requests/s", 0, 6, 4, [q(f'sum(rate(http_requests_total{{{SEL}}}[1m]))')], unit="reqps", options=stat)
add("stat", "Errores 5xx (%)", 6, 6, 4, [q(f'100 * {errors_5xx} / sum(rate(http_requests_total{{{SEL}}}[5m]))')],
    unit="percent", options=stat,
    extra=thresholds(("green", None), ("orange", 1), ("red", 5), unit="percent"))
# Percentiles globales: la métrica highr (21 buckets, sin handler); lowr solo tiene los buckets del SLO.
HIGHR = 'http_request_duration_highr_seconds_bucket'
add("stat", "Latencia p95", 12, 6, 4,
    [q(f'histogram_quantile(0.95, sum by (le) (rate({HIGHR}{{{SEL}}}[5m])))')], unit="s", options=stat)
add("stat", "Requests totales", 18, 6, 4, [q(f'sum(http_requests_total{{{SEL}}})')], unit="short", options=stat)
band(4)

# --- Tráfico ---
row("Tráfico y errores")
ts = {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "max"]}}
add("timeseries", "Requests/s por endpoint", 0, 12, 8,
    [q(f'sum by (method, handler) (rate(http_requests_total{{{SEL}}}[1m]))', "{{method}} {{handler}}")], unit="reqps", options=ts)
add("timeseries", "Requests/s por código de estado", 12, 12, 8,
    [q(f'sum by (status) (rate(http_requests_total{{{SEL}}}[1m]))', "{{status}}")], unit="reqps", options=ts)
band(8)

# --- Latencia ---
row("Latencia")
LOWR = 'http_request_duration_seconds_bucket'
add("timeseries", "Latencia p50 / p95 / p99", 0, 12, 8, [
    q(f'histogram_quantile(0.50, sum by (le) (rate({HIGHR}{{{SEL}}}[5m])))', "p50"),
    q(f'histogram_quantile(0.95, sum by (le) (rate({HIGHR}{{{SEL}}}[5m])))', "p95"),
    q(f'histogram_quantile(0.99, sum by (le) (rate({HIGHR}{{{SEL}}}[5m])))', "p99")], unit="s", options=ts)
add("timeseries", "Latencia p95 por endpoint", 12, 12, 8,
    [q(f'histogram_quantile(0.95, sum by (le, handler) (rate({LOWR}{{{SEL}}}[5m])))', "{{handler}}")], unit="s", options=ts)
band(8)

# --- SLO disponibilidad (requiere las recording rules de monitoring/prometheus/rules/*-slo.yml) ---
row("SLO disponibilidad (30 días)")
ratio_30d = (with_zero(f'sum(increase(http_requests_total{{{SEL},status="5xx"}}[30d]))',
                       f'sum(increase(http_requests_total{{{SEL}}}[30d]))')
             + f' / clamp_min(sum(increase(http_requests_total{{{SEL}}}[30d])), 1e-9)')
add("stat", "Disponibilidad 30d", 0, 8, 4, [q(f"1 - ({ratio_30d})")], unit="percentunit", options=stat,
    extra=thresholds(("red", None), ("green", SLO_TARGET), unit="percentunit", decimals=3))
add("stat", "Presupuesto de error restante", 8, 8, 4, [q(f"1 - (({ratio_30d}) / {BUDGET})")],
    unit="percentunit", options=stat,
    extra=thresholds(("red", None), ("orange", 0.25), ("green", 0.5), unit="percentunit"))
add("timeseries", "Burn rate (1 = consumo sostenible)", 16, 8, 8, [
    q(f"sli:http_error_ratio:rate1h{{{SEL}}} / {BUDGET}", "1h"),
    q(f"sli:http_error_ratio:rate6h{{{SEL}}} / {BUDGET}", "6h")], unit="short", options=ts, extra=burn_lines)
band(8)

# --- SLO latencia ---
row("SLO latencia (30 días)")
slow_30d = (f'(sum(increase(http_request_duration_seconds_count{{{SEL}}}[30d])) '
            f'- sum(increase(http_request_duration_seconds_bucket{{{SEL},le="{LATENCY_LE}"}}[30d]))) '
            f'/ clamp_min(sum(increase(http_request_duration_seconds_count{{{SEL}}}[30d])), 1e-9)')
add("stat", f"Requests bajo {LATENCY_LE} s (30d)", 0, 8, 4, [q(f"1 - ({slow_30d})")], unit="percentunit", options=stat,
    extra=thresholds(("red", None), ("green", LATENCY_TARGET), unit="percentunit", decimals=3))
add("stat", "Presupuesto de latencia restante", 8, 8, 4, [q(f"1 - (({slow_30d}) / {LATENCY_BUDGET})")],
    unit="percentunit", options=stat,
    extra=thresholds(("red", None), ("orange", 0.25), ("green", 0.5), unit="percentunit"))
add("timeseries", "Burn rate de latencia (1 = consumo sostenible)", 16, 8, 8, [
    q(f"sli:http_latency_slow_ratio:rate1h{{{SEL}}} / {LATENCY_BUDGET}", "1h"),
    q(f"sli:http_latency_slow_ratio:rate6h{{{SEL}}} / {LATENCY_BUDGET}", "6h")], unit="short", options=ts,
    extra=burn_lines)
band(8)

# --- Recursos ---
# process_* NO existe en multiproceso (gunicorn con varios workers): estos tres paneles quedan vacíos.
# Con un solo proceso por contenedor sí se llenan; con varios, tomar CPU/memoria del contenedor.
row("Recursos del proceso")
add("timeseries", "CPU (cores)", 0, 8, 7, [q(f'rate(process_cpu_seconds_total{{{SEL}}}[1m])', "cpu")], unit="short")
add("timeseries", "Memoria residente", 8, 8, 7, [q(f'process_resident_memory_bytes{{{SEL}}}', "rss")], unit="bytes")
add("timeseries", "Archivos abiertos", 16, 8, 7, [q(f'process_open_fds{{{SEL}}}', "fds")], unit="short")
band(7)

# --- Logs ---
row("Logs (Loki)")
add("timeseries", "Volumen de logs por nivel", 0, 24, 5,
    [{"expr": 'sum by (level) (count_over_time({service="%s"}[1m]))' % LOG_SERVICE,
      "legendFormat": "{{level}}"}], ds=LOKI, unit="short", options=ts)
band(5)
add("logs", "Logs del backend", 0, 24, 10,
    [{"expr": '{service="%s"} |~ "(?i)$search" | json' % LOG_SERVICE}], ds=LOKI,
    options={"showTime": True, "wrapLogMessage": True, "enableLogDetails": True, "sortOrder": "Descending"})
band(10)
add("logs", "Solo errores (backend)", 0, 24, 8,
    [{"expr": '{service="%s", level=~"error|critical"} | json' % LOG_SERVICE}], ds=LOKI,
    options={"showTime": True, "wrapLogMessage": True, "enableLogDetails": True})
band(8)

# --- Trazas ---
row("Trazas (Tempo)")
add("table", "Trazas recientes", 0, 24, 10,
    [{"queryType": "traceqlSearch", "limit": 20, "tableType": "traces",
      "filters": [{"id": "service-name", "tag": "service.name", "operator": "=", "scope": "resource",
                   "value": [SERVICE], "valueType": "string"}]}], ds=TEMPO)
band(10)
add("table", f"Trazas lentas (> {int(float(LATENCY_LE) * 1000)}ms)", 0, 24, 8,
    [{"queryType": "traceql",
      "query": '{ resource.service.name = "%s" && duration > %dms }' % (SERVICE, int(float(LATENCY_LE) * 1000)),
      "limit": 20, "tableType": "traces"}], ds=TEMPO)
band(8)

dashboard = {
    "uid": SERVICE, "title": TITLE,
    "tags": ["fastapi", "observability", "slo"], "timezone": "browser", "schemaVersion": 39,
    "version": 1, "refresh": "10s", "time": {"from": "now-30m", "to": "now"},
    "templating": {"list": [{"name": "search", "label": "Buscar en logs", "type": "textbox",
                             "query": "", "current": {"value": "", "text": ""}}]},
    "panels": panels,
}
out = Path(__file__).parent / "grafana" / "dashboards" / f"{SERVICE}.json"
out.parent.mkdir(parents=True, exist_ok=True)  # en un proyecto nuevo la carpeta todavía no existe
out.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
print(out)
