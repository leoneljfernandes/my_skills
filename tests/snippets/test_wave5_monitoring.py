"""Ola 5 (observabilidad), parte con herramientas reales: promtool, amtool, Alertmanager, Alloy y Loki.

OB-01 (`job` en los SLI: dos servicios no chocan y la inhibición funciona), OB-03/OB-08 (cero 5xx y reposo),
OB-07 (cada alerta dispara y no dispara; sin reglas "idem"), OB-14 (`check config` lee las reglas),
OB-18/OB-19 (el dashboard generado). Usa las imágenes con tag fijo de references/stack.md; sin Docker se saltea.

Uso (desde la raíz del repo):
    uv run --with pytest --with pyyaml pytest tests/snippets/test_wave5_monitoring.py -v
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from extract import SKILLS, block, fenced_blocks  # noqa: E402

SLO = "defining-grafana-slos"
LOG = "logging-json-to-loki"
STACK = {"file": "references/stack.md"}
PROM_IMAGE = "prom/prometheus:v3.15.1"
pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="requiere docker")


def sh(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", command], cwd=cwd, capture_output=True, text=True, timeout=900,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def docker_lines(code: str) -> list[str]:
    return [line for line in code.splitlines() if line.startswith("docker run")]


@pytest.fixture(scope="module")
def mon(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """monitoring/ armado con los bloques publicados (el mismo árbol que describe references/stack.md)."""
    root = tmp_path_factory.mktemp("monitoring")
    files = {
        "monitoring/prometheus/prometheus.yml": block(SLO, "scrape_configs", **STACK),
        "monitoring/prometheus/rules/orders-api-slo.yml": block(SLO, "name: orders-api-sli"),
        "monitoring/prometheus/tests/orders-api-slo.test.yml": block(SLO, "rule_files:"),
        "monitoring/alertmanager/alertmanager.yml": block(SLO, "inhibit_rules"),
        "monitoring/loki.yml": block(SLO, "allow_structured_metadata", **STACK),
        "monitoring/tempo.yml": block(SLO, "backend_scheduler", **STACK),
        "monitoring/alloy/config.alloy": block(LOG, "discovery.docker"),
    }
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
    return root


# --- OB-07 · OB-01 · OB-03 · OB-08: las reglas y su test publicado -------------------------------------


def test_published_rules_and_tests_pass_with_the_published_commands(mon: Path):
    code = "\n".join(c for lang, c, _ in fenced_blocks((SKILLS / "observability" / SLO / "SKILL.md").read_text()) if lang == "bash")
    lines = docker_lines(code)
    assert len(lines) == 3, lines  # check config, test rules, amtool check-config
    for line in lines:
        done = sh(line, mon)
        assert done.returncode == 0, f"{line}\n{done.stdout}\n{done.stderr}"
    check_config = sh(lines[0], mon)
    assert re.search(r"\b18 rules found", check_config.stdout + check_config.stderr)  # lee las reglas (OB-14)


def test_the_rules_block_is_complete_and_every_alert_is_tested_both_ways(mon: Path):
    rules = yaml.safe_load((mon / "monitoring/prometheus/rules/orders-api-slo.yml").read_text())
    tests = yaml.safe_load((mon / "monitoring/prometheus/tests/orders-api-slo.test.yml").read_text())
    raw = (mon / "monitoring/prometheus/rules/orders-api-slo.yml").read_text()
    assert "idem" not in raw and "…" not in raw  # OB-07: sin reglas elididas
    records = {r["record"] for g in rules["groups"] for r in g["rules"] if "record" in r}
    windows = ("5m", "30m", "1h", "6h", "3d")
    assert records == {f"sli:{m}:rate{w}" for m in ("http_error_ratio", "http_latency_slow_ratio") for w in windows}
    alerts = {r["alert"]: r for g in rules["groups"] for r in g["rules"] if "alert" in r}
    assert len(alerts) == 8
    for name, alert in alerts.items():
        assert {"summary", "description", "runbook_url"} <= set(alert["annotations"]), name  # OB-22
        assert alert["labels"]["severity"] in {"page", "ticket"}, name
    fires, quiet = set(), set()
    for case in tests["tests"]:
        for check in case.get("alert_rule_test", []):
            (fires if check["exp_alerts"] else quiet).add(check["alertname"])
    assert fires == set(alerts) and quiet >= set(alerts) - {"OrdersApiDown"}, (set(alerts) - fires, set(alerts) - quiet)
    # OB-01: toda expresión agrega por job y toda alerta filtra por job
    for g in rules["groups"]:
        for r in g["rules"]:
            if "record" in r:
                assert "sum by (job)" in r["expr"] and "sum(" not in r["expr"].replace("sum by", ""), r["record"]
            if r.get("alert", "").endswith("Burn"):
                assert r["expr"].count('{job="orders-api"}') == 2, r["alert"]
    assert [r["labels"]["severity"] for r in (alerts["OrdersApiErrorBudgetTicketBurn"], alerts["OrdersApiLatencyTicketBurn"])] == ["ticket"] * 2


def second_service(mon: Path, tmp: Path, *, by_job: bool = True) -> Path:
    """Los mismos SLO para payments-api (un archivo por servicio, mismos nombres de record), más un test de dos servicios."""
    rules = (mon / "monitoring/prometheus/rules/orders-api-slo.yml").read_text()
    if not by_job:
        rules = rules.replace("sum by (job) (", "sum (")
    payments = rules.replace("orders-api", "payments-api").replace("OrdersApi", "PaymentsApi")
    (tmp / "rules").mkdir(parents=True)
    (tmp / "tests").mkdir()
    (tmp / "rules/orders.yml").write_text(rules)
    (tmp / "rules/payments.yml").write_text(payments)
    (tmp / "tests/two.test.yml").write_text(
        """
rule_files: [../rules/orders.yml, ../rules/payments.yml]
evaluation_interval: 30s
tests:
  - interval: 30s
    input_series:
      - series: 'http_requests_total{job="orders-api",status="2xx"}'
        values: '0+100x240'
      - series: 'http_requests_total{job="payments-api",status="2xx"}'
        values: '0+50x240'
      - series: 'http_requests_total{job="payments-api",status="5xx"}'
        values: '0+50x240'
    promql_expr_test:
      - expr: sli:http_error_ratio:rate1h
        eval_time: 70m
        exp_samples:
          - labels: 'sli:http_error_ratio:rate1h{job="orders-api"}'
            value: 0
          - labels: 'sli:http_error_ratio:rate1h{job="payments-api"}'
            value: 0.5
    alert_rule_test:
      - eval_time: 70m
        alertname: OrdersApiErrorBudgetFastBurn
        exp_alerts: []
      - eval_time: 70m
        alertname: PaymentsApiErrorBudgetFastBurn
        exp_alerts:
          - exp_labels: {job: payments-api, severity: page, slo: availability}
            exp_annotations:
              summary: "payments-api quema el presupuesto de error 14x más rápido de lo sostenible"
              description: "Error ratio 1h = 50% (SLO 99.9 %)."
              runbook_url: "https://runbooks.example.com/payments-api/error-budget"
""")
    return tmp


def mountable(path: Path) -> Path:
    """Los directorios de pytest son 0700 y el usuario del contenedor (nobody) no los lee."""
    path.chmod(0o755)
    return path


def promtool_test(tmp: Path) -> subprocess.CompletedProcess[str]:
    return sh(f'docker run --rm -v "{tmp}:/t:ro,z" -w /t/tests --entrypoint promtool {PROM_IMAGE} test rules two.test.yml', tmp)


def test_two_services_do_not_collide_and_only_the_failing_one_alerts(mon: Path, tmp_path: Path):
    done = promtool_test(mountable(second_service(mon, tmp_path)))
    assert done.returncode == 0, done.stdout + done.stderr


def test_without_by_job_two_services_collide(mon: Path, tmp_path: Path):
    """Rojo de OB-01: con el `sum` sin `by (job)` el mismo test falla con `duplicate sample`."""
    done = promtool_test(mountable(second_service(mon, tmp_path, by_job=False)))
    assert done.returncode != 0 and "duplicate sample" in done.stdout + done.stderr


# --- OB-01: la inhibición con Alertmanager real --------------------------------------------------------


def post_alerts(base: str, alerts: list[dict[str, dict[str, str]]]) -> None:
    request = urllib.request.Request(f"{base}/api/v2/alerts", data=json.dumps(alerts).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(request, timeout=10).read()


def test_alertmanager_inhibits_burn_pages_of_the_same_job_only(mon: Path, tmp_path: Path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for name in ("oncall_webhook_url", "ticket_webhook_url"):
        (secrets / name).write_text("http://127.0.0.1:9/hook")
    name = f"w5_am_{os.getpid()}"
    config = mon / "monitoring/alertmanager/alertmanager.yml"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::9093",
                    "-v", f"{config}:/etc/alertmanager/alertmanager.yml:ro,z", "-v", f"{secrets}:/etc/alertmanager/secrets:ro,z",
                    "prom/alertmanager:v0.34.1", "--config.file=/etc/alertmanager/alertmanager.yml"],
                   check=True, capture_output=True)
    try:
        port = subprocess.run(["docker", "port", name, "9093/tcp"], check=True, capture_output=True, text=True).stdout.split(":")[-1].strip()
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{base}/-/ready", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        # Los labels son los que `promtool` confirma que llevan las alertas de las reglas publicadas.
        def alert(name: str, **labels: str) -> dict[str, dict[str, str]]:
            return {"labels": {"alertname": name, **labels}, "annotations": {}}
        post_alerts(base, [
            alert("OrdersApiDown", job="orders-api", severity="page"),
            alert("OrdersApiErrorBudgetFastBurn", job="orders-api", severity="page", slo="availability"),
            alert("OrdersApiLatencySlowBurn", job="orders-api", severity="page", slo="latency"),
            alert("PaymentsApiErrorBudgetFastBurn", job="payments-api", severity="page", slo="availability"),
            alert("OrdersApiErrorBudgetTicketBurn", job="orders-api", severity="ticket", slo="availability"),
            alert("BurnWithoutJob", severity="page", slo="availability"),  # lo que producía el `sum` sin `by (job)`
        ])
        time.sleep(1)
        state = {a["labels"]["alertname"]: a["status"] for a in json.load(urllib.request.urlopen(f"{base}/api/v2/alerts", timeout=10))}
        assert state["OrdersApiDown"]["state"] == "active"
        for suppressed in ("OrdersApiErrorBudgetFastBurn", "OrdersApiLatencySlowBurn"):
            assert state[suppressed]["state"] == "suppressed" and state[suppressed]["inhibitedBy"], suppressed
        for active in ("PaymentsApiErrorBudgetFastBurn", "OrdersApiErrorBudgetTicketBurn", "BurnWithoutJob"):
            assert state[active]["state"] == "active", active  # otro job, otra severidad o sin job: no se inhibe
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)


# --- OB-14 · stack.md ----------------------------------------------------------------------------------


def test_check_config_reads_the_rule_files_so_a_broken_rule_fails(mon: Path, tmp_path: Path):
    stack_lines = docker_lines(block(SLO, "docker run", **STACK))
    check_config = next(line for line in stack_lines if "check config" in line)
    assert "/etc/prometheus" in check_config
    work = tmp_path / "w"
    shutil.copytree(mon, work)
    assert sh(check_config, work).returncode == 0
    (work / "monitoring/prometheus/rules/broken.yml").write_text(
        "groups:\n  - name: x\n    rules:\n      - record: bad\n        expr: sum(rate(foo[5m])\n")
    broken = sh(check_config, work)
    assert broken.returncode == 1 and "unclosed left parenthesis" in broken.stdout + broken.stderr
    old = check_config.replace("/etc/prometheus", "/p")
    assert sh(old, work).returncode == 0  # el comando anterior daba verde sin leer ninguna regla


def test_stack_verification_commands_for_loki_and_alloy_pass(mon: Path):
    for line in docker_lines(block(SLO, "docker run", **STACK)):
        if "loki" in line or "alloy" in line:
            done = sh(line, mon)
            assert done.returncode == 0, f"{line}\n{done.stdout}\n{done.stderr}"


# --- OB-18 · OB-19: el dashboard generado --------------------------------------------------------------


def build_dashboard(tmp: Path) -> dict:
    dest = tmp / "monitoring"
    dest.mkdir()
    shutil.copy(SKILLS / "observability" / SLO / "templates" / "build_dashboard.py", dest)
    done = subprocess.run([sys.executable, str(dest / "build_dashboard.py")], cwd=tmp, capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0, done.stderr  # sin la carpeta grafana/dashboards/ previa (OB-19)
    return json.loads((dest / "grafana/dashboards/orders-api.json").read_text())


def test_dashboard_runs_in_a_clean_project_in_the_declared_order(tmp_path: Path):
    dashboard = build_dashboard(tmp_path)
    rows = [p["title"] for p in dashboard["panels"] if p["type"] == "row"]
    assert rows == ["Resumen", "Tráfico y errores", "Latencia", "SLO disponibilidad (30 días)", "SLO latencia (30 días)",
                    "Recursos del proceso", "Logs (Loki)", "Trazas (Tempo)"]
    ys = [p["gridPos"]["y"] for p in dashboard["panels"] if p["type"] == "row"]
    assert ys == sorted(ys)
    boxes = [(p["gridPos"]["y"], p["gridPos"]["y"] + p["gridPos"]["h"], p["gridPos"]["x"], p["gridPos"]["x"] + p["gridPos"]["w"])
             for p in dashboard["panels"]]
    for i, a in enumerate(boxes):  # ningún panel se pisa con otro
        for b in boxes[i + 1:]:
            assert not (a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]), (a, b)


def test_every_prometheus_query_filters_by_job_parses_and_percentiles_use_highr(mon: Path, tmp_path: Path):
    dashboard = build_dashboard(tmp_path)
    exprs = [t["expr"] for p in dashboard["panels"] if p.get("datasource", {}).get("type") == "prometheus" for t in p["targets"]]
    assert len(exprs) > 20
    for expr in exprs:
        assert 'job="orders-api"' in expr, expr  # OB-18
    # OB-06: los percentiles globales (sin `handler`) salen de la métrica highr; los de endpoint, de la lowr
    global_q = [e for e in exprs if "histogram_quantile" in e and "handler" not in e]
    assert global_q and all("highr" in e for e in global_q), global_q
    per_endpoint = [e for e in exprs if "histogram_quantile" in e and "handler" in e]
    assert per_endpoint and all("highr" not in e for e in per_endpoint)
    # OB-03: sin ningún 5xx, la disponibilidad y el % de errores valen 0 en vez de "sin datos"
    assert all("or 0 *" in e for e in exprs if 'status="5xx"' in e and "sli:" not in e), exprs
    # todas las expresiones son PromQL válido: se las prueba como reglas
    rules = {"groups": [{"name": "dash", "rules": [{"record": f"dash:q{i}", "expr": e} for i, e in enumerate(exprs)]}]}
    mountable(tmp_path)
    (tmp_path / "dash.yml").write_text(yaml.safe_dump(rules))
    done = sh(f'docker run --rm -v "{tmp_path}:/t:ro,z" --entrypoint promtool {PROM_IMAGE} check rules /t/dash.yml', tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr


def test_dashboard_latency_row_uses_the_recording_rules_of_the_slo_file(tmp_path: Path):
    dashboard = build_dashboard(tmp_path)
    queries = " ".join(t["expr"] for p in dashboard["panels"] for t in p.get("targets", []) if "expr" in t)
    for series in ("sli:http_latency_slow_ratio:rate1h", "sli:http_latency_slow_ratio:rate6h"):
        assert series + '{job="orders-api"}' in queries
    assert "0.0010000000000000009" not in queries
