"""Ola 5 (observabilidad): lo que se comprueba leyendo las skills, sin Docker ni red.

Cada test lleva el ID del hallazgo de docs/plans/2026-11-01-refinamiento-skills/auditoria/observability.md.

Uso (desde la raíz del repo):
    uv run --with pytest --with pyyaml pytest tests/snippets/test_wave5_contracts.py -v
"""

import re
import sys
import tomllib
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from extract import SKILLS, block, fenced_blocks  # noqa: E402

HERE = Path(__file__).parent
OBS = "observability"
SLO, MET, LOG, TRC = "defining-grafana-slos", "exposing-prometheus-metrics", "logging-json-to-loki", "tracing-with-opentelemetry"
SCAF = "backend/scaffolding-fastapi-backends"


def text(rel: str) -> str:
    return (SKILLS / rel).read_text(encoding="utf-8")


def skill(name: str) -> str:
    return text(f"{OBS}/{name}/SKILL.md")


STACK = text(f"{OBS}/{SLO}/references/stack.md")


def stack_yaml(marker: str) -> dict:
    return yaml.safe_load(block(SLO, marker, file="references/stack.md"))


# --- OB-02 -------------------------------------------------------------------------------------------


def test_trace_to_logs_uses_a_custom_query_by_trace_id_not_the_service_name():
    tempo = next(d for d in stack_yaml("tracesToLogsV2")["datasources"] if d["uid"] == "tempo")
    logs = tempo["jsonData"]["tracesToLogsV2"]
    assert logs["customQuery"] is True and logs["datasourceUid"] == "loki"
    assert logs["query"] == '{service=~".+"} | trace_id="${__span.traceId}"'


def test_logging_explains_the_two_meanings_of_service():
    logging_skill = skill(LOG)
    assert "campo JSON" in logging_skill and "label de Loki" in logging_skill and "service_extracted" in logging_skill
    assert "`APP_NAME`" in logging_skill and "nombre del servicio en docker-compose" in logging_skill


# --- OB-04 · OB-05 -----------------------------------------------------------------------------------


def test_prometheus_keeps_35_days_and_the_checklist_asks_for_it():
    prometheus = stack_yaml("--storage.tsdb.retention.time")["prometheus"]
    assert "--storage.tsdb.retention.time=35d" in prometheus["command"]
    assert re.search(r"- \[ \] La retención de Prometheus es mayor o igual", skill(SLO))


def test_exemplars_use_the_label_tempo_writes_and_come_only_from_spanmetrics():
    prometheus = next(d for d in stack_yaml("tracesToLogsV2")["datasources"] if d["uid"] == "prometheus")
    assert prometheus["jsonData"]["exemplarTraceIdDestinations"][0]["name"] == "traceID"
    assert "traces_spanmetrics_*" in skill(SLO) and "traces_spanmetrics_*" in STACK
    assert "send_exemplars: true" in STACK


# --- OB-06 · OB-12 -----------------------------------------------------------------------------------


def test_metrics_block_sets_its_own_latency_buckets_with_the_slo_threshold():
    code = block(MET, "ORDERS_CREATED = Counter")
    assert "latency_lowr_buckets=" in code
    buckets = eval(re.search(r"latency_lowr_buckets=(\([^)]*\))", code).group(1))  # noqa: S307  (literal de la skill)
    assert 0.5 in buckets and 0.3 in buckets
    assert "highr" in skill(MET) and "21 buckets" in skill(MET)


def test_multiprocess_recipe_creates_the_directory_and_uses_uvicorn_worker():
    metrics = skill(MET)
    command = block(MET, "gunicorn app.main:app")
    assert 'rm -rf "$D" && mkdir -p "$D"' in command and "-k uvicorn_worker.UvicornWorker" in command
    assert "-k uvicorn.workers.UvicornWorker" not in "".join(t for t in (p.read_text() for p in SKILLS.rglob("*.md")))
    assert "process_*" in metrics and "no existen" in metrics
    assert "gunicorn" in "\n".join(l for l in text(f"{SCAF}/SKILL.md").splitlines() if "uvicorn-worker" in l)
    assert "process_*" in (SKILLS / OBS / SLO / "templates" / "build_dashboard.py").read_text()


# --- OB-13 -------------------------------------------------------------------------------------------


def test_tracing_block_instruments_httpx_and_scaffolding_lists_the_package():
    code = block(TRC, "def setup_tracing")
    assert "from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor" in code
    assert "HTTPXClientInstrumentor().instrument(tracer_provider=_provider)" in code
    # el SDK sigue importándose dentro de setup_tracing (OB-11): a nivel de módulo solo la API
    module_level = code.split("def setup_tracing")[0]
    assert "opentelemetry.sdk" not in module_level.replace("from opentelemetry.sdk.trace import TracerProvider", "")
    pyproject = tomllib.loads(block("scaffolding-fastapi-backends", 'name = "my-api"'))
    assert "opentelemetry-instrumentation-httpx" in pyproject["project"]["dependencies"]
    assert "si hay llamadas salientes" in text(f"{SCAF}/SKILL.md")


# --- TS-07 · OB-09 -----------------------------------------------------------------------------------


def test_tracing_test_uses_the_testing_skill_helper_and_the_xfail_is_gone():
    code = block(TRC, "test_place_order_emits_manual_span_with_sql_children")
    assert "db_session: AsyncSession" in code and "await create_product(db_session, stock=5)" in code
    assert "ProductFactory" not in "".join(p.read_text() for p in (SKILLS / OBS).rglob("*.md"))
    assert "TS-07" not in (HERE / "reference" / "xfail_plugin.py").read_text()
    assert "getattr(factories" not in (HERE / "reference" / "build_ref.py").read_text()
    assert 'unlink()' not in "\n".join(l for l in (HERE / "test_wave2_project.py").read_text().splitlines() if "test_tracing" in l)


# --- OB-14 · OB-15 · OB-16 · OB-17 · OB-24 -----------------------------------------------------------


def test_check_config_commands_mount_prometheus_where_the_rule_glob_points():
    for code in (block(SLO, "docker run"), block(SLO, "docker run", file="references/stack.md")):
        for line in code.splitlines():
            if "promtool" in line:
                assert "/etc/prometheus" in line and ":/p:" not in line, line
    assert "/etc/prometheus/rules/*.yml" in stack_yaml("scrape_configs")["rule_files"]


def test_log_checklist_excludes_the_supervisor_processes():
    assert "salvo las del proceso supervisor" in skill(LOG) and "gunicorn" in skill(LOG)


def test_end_to_end_check_generates_traffic_that_logs():
    line = next(l for l in STACK.splitlines() if l.startswith("Prueba de punta a punta"))
    assert "POST /api/v1/orders" in line and "404 de dominio" in line and "/docs" in line and "no loguean" in line


def test_loki_labels_match_the_alloy_config_and_env_is_not_one():
    logging_skill = skill(LOG)
    labels_rule = next(l for l in logging_skill.splitlines() if l.startswith("- **Labels de Loki"))
    assert "`service`, `level` y `container`" in labels_rule and "`env` **no** es un label" in labels_rule
    alloy = block(LOG, "discovery.docker")
    assert 'target_label  = "container"' in alloy and "env" not in re.findall(r"values = \{ (\w+)", alloy)


def test_promtail_trigger_stays_with_a_migrate_to_alloy_line():
    logging_skill = skill(LOG)
    assert "Promtail" in logging_skill.split("---")[1] and "migrar a Alloy" in logging_skill


# --- OB-18 · OB-22 -----------------------------------------------------------------------------------


def test_promql_examples_filter_by_job():
    for rel in (f"{OBS}/{MET}/SKILL.md", f"{OBS}/{SLO}/SKILL.md"):
        for lang, code, _ in fenced_blocks(text(rel)):
            if lang == "promql":
                for line in code.splitlines():
                    if "rate(" in line or "increase(" in line:
                        assert 'job="orders-api"' in line, line
    assert 'sum(rate(http_requests_total{job="orders-api"}[1h]))' in skill(SLO)


def test_every_alert_in_the_example_has_the_mandatory_annotations_and_the_inhibition_names_a_real_alert():
    rules = yaml.safe_load(block(SLO, "name: orders-api-sli"))
    alerts = {r["alert"]: r for g in rules["groups"] for r in g["rules"] if "alert" in r}
    for name, alert in alerts.items():
        assert {"summary", "description", "runbook_url"} <= set(alert["annotations"]), name
    inhibit = yaml.safe_load(block(SLO, "inhibit_rules"))["inhibit_rules"][0]
    assert inhibit["source_matchers"] == ['alertname="OrdersApiDown"'] and "OrdersApiDown" in alerts
    assert "`OrdersApiDown`" in skill(SLO) and "ServiceDown" not in skill(SLO)


# --- METRICS_ENABLED en el compose -------------------------------------------------------------------


def test_compose_documents_metrics_enabled_next_to_the_otel_endpoint():
    docker = text(f"{SCAF}/references/docker.md")
    assert 'METRICS_ENABLED: "true"' in docker and "OTEL_EXPORTER_OTLP_ENDPOINT: http://tempo:4317" in docker
    assert 'METRICS_ENABLED: "true"' in STACK
