"""Ola 5 (observabilidad), parte Python: lo que se ve ejecutando el código publicado.

OB-06 (buckets en /metrics), OB-12 (dos workers de gunicorn suman bien), OB-13 (span CLIENT con
`traceparent` contra un servidor HTTP local en 127.0.0.1; `httpx.MockTransport` no se instrumenta),
OB-16 (una request que sí loguea deja `trace_id`), TS-07·OB-09 (el test de tracing publicado pasa en el
proyecto armado desde las skills) y, del plan 2026-11-22, D1 (un segundo `create_app()` sigue trazado)
y D3 (`APP_INSTALLATION` en logs y en el `Resource`).

Arma el mismo clon que test_wave2_project.py (bootstrap de scaffolding + bloques de las skills);
necesita `uv` y red o caché de uv.

Uso (desde la raíz del repo):
    uv run --with pytest --with pyyaml pytest tests/snippets/test_wave5_python.py -v
"""

import json
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from extract import block  # noqa: E402
from test_wave2_project import ENV, clean_env, clone, ok  # noqa: E402,F401  (clone: fixture del módulo de la ola 2)

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="requiere uv")

OTLP = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4317", "OTEL_EXPORTER_OTLP_INSECURE": "true"}


def python(clone: Path, tmp_path: Path, script: str, *extra: str, **env: str) -> str:
    (tmp_path / "check.py").write_text(textwrap.dedent(script), encoding="utf-8")
    return ok(["uv", "run", "--project", str(clone), *extra, "python", str(tmp_path / "check.py")], tmp_path,
              PYTHONPATH=str(clone), **{**ENV, **env})


# --- OB-06 -------------------------------------------------------------------------------------------


def test_metrics_block_exposes_the_slo_bucket_and_the_highr_histogram(clone: Path, tmp_path: Path):
    out = python(clone, tmp_path, """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.config import get_settings
        from app.observability.metrics import setup_metrics

        app = FastAPI()

        @app.get("/items/{item_id}")
        def item(item_id: int) -> dict[str, int]:
            return {"id": item_id}

        setup_metrics(app, get_settings())
        client = TestClient(app)
        client.get("/items/1")
        text = client.get("/metrics").text
        lowr = [line for line in text.splitlines() if line.startswith("http_request_duration_seconds_bucket")]
        assert any('le="0.3"' in line and 'handler="/items/{item_id}"' in line for line in lowr), lowr  # umbral propio
        assert any('le="0.5"' in line for line in lowr)  # el umbral del SLO
        highr = [line for line in text.splitlines() if line.startswith("http_request_duration_highr_seconds_bucket")]
        assert len(highr) > 15 and all("handler" not in line for line in highr), highr
        print("OB06 OK")
    """, METRICS_ENABLED="true")
    assert "OB06 OK" in out


# --- OB-12 -------------------------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_two_gunicorn_workers_add_up_with_the_published_command(clone: Path, tmp_path: Path):
    skill = "exposing-prometheus-metrics"
    (tmp_path / "gunicorn.conf.py").write_text(block(skill, "def child_exit"), encoding="utf-8")
    (tmp_path / "mpapp.py").write_text(textwrap.dedent("""
        from fastapi import FastAPI
        from app.config import get_settings
        from app.observability.metrics import setup_metrics

        app = FastAPI()

        @app.get("/items/{item_id}")
        def item(item_id: int) -> dict[str, int]:
            return {"id": item_id}

        setup_metrics(app, get_settings())
    """), encoding="utf-8")
    command = block(skill, "gunicorn app.main:app")
    assert "uvicorn_worker.UvicornWorker" in command and "mkdir -p" in command and "uvicorn.workers" not in command
    port = free_port()
    mp_dir = tmp_path / "prom"
    mp_dir.mkdir()
    (mp_dir / "counter_999999.db").write_bytes(b"stale")  # resto de un deploy anterior: el comando lo vacía
    script = (command.replace("app.main:app", "mpapp:app").replace("/tmp/prometheus", str(mp_dir))
              .replace("-w 4", f"-w 2 -b 127.0.0.1:{port}"))
    env = clean_env(PYTHONPATH=f"{clone}:{tmp_path}", METRICS_ENABLED="true", **ENV)
    proc = subprocess.Popen(
        ["uv", "run", "--project", str(clone), "--with", "gunicorn", "--with", "uvicorn-worker", "bash", "-c", script],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                urllib.request.urlopen(f"{base}/items/0", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("gunicorn no arrancó")
        for i in range(1, 8):  # 1 de arranque + 7 = 8 requests
            urllib.request.urlopen(f"{base}/items/{i}", timeout=5).read()
        text = urllib.request.urlopen(f"{base}/metrics", timeout=5).read().decode()
        sample = re.search(r'http_requests_total\{handler="/items/\{item_id\}",method="GET",status="2xx"\} ([\d.]+)', text)
        assert sample and float(sample.group(1)) == 8.0, text
        assert "process_resident_memory_bytes" not in text and "process_cpu_seconds_total" not in text  # no existen en multiproceso
        assert not (mp_dir / "counter_999999.db").exists()  # el directorio se vació al arrancar
    finally:
        import os
        import signal

        os.killpg(proc.pid, signal.SIGTERM)
        output = proc.communicate(timeout=60)[0]
    assert "deprecated" not in output.lower()


# --- OB-13 -------------------------------------------------------------------------------------------


def test_httpx_calls_become_client_spans_that_send_traceparent(clone: Path, tmp_path: Path):
    """El instrumentor global de `setup_tracing` solo envuelve los transportes reales de httpx: un
    `httpx.MockTransport` queda fuera (el plan lo proponía y no se instrumenta), así que el servicio
    "de afuera" es un servidor HTTP local en 127.0.0.1 que anota los headers que recibe."""
    out = python(clone, tmp_path, """
        import asyncio

        import httpx
        from fastapi import FastAPI
        from httpx import ASGITransport
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from opentelemetry.trace import SpanKind
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.config import get_settings
        from app.observability import tracing

        app = FastAPI()
        tracing.setup_tracing(app, create_async_engine("sqlite+aiosqlite://"), get_settings())
        exporter = InMemorySpanExporter()
        tracing._provider.add_span_processor(SimpleSpanProcessor(exporter))
        received: list[bytes] = []
        remote = {"url": ""}

        async def payments(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            received.append(await reader.readuntil(b"\\r\\n\\r\\n"))
            writer.write(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\nConnection: close\\r\\n\\r\\n{}")
            await writer.drain()
            writer.close()

        @app.get("/charge")
        async def charge() -> dict[str, bool]:
            async with httpx.AsyncClient() as outbound:
                await outbound.get(remote["url"] + "/v1/charge")
            return {"ok": True}

        async def main() -> None:
            server = await asyncio.start_server(payments, "127.0.0.1", 0)
            remote["url"] = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get("/charge")).status_code == 200
            server.close()

        asyncio.run(main())
        spans = exporter.get_finished_spans()
        client_spans = [s for s in spans if s.kind == SpanKind.CLIENT and "/v1/charge" in str(dict(s.attributes or {}))]
        assert client_spans, [(s.name, s.kind) for s in spans]
        span = client_spans[0]
        server_span = next(s for s in spans if s.kind == SpanKind.SERVER and s.name.startswith("GET /charge"))
        assert span.context.trace_id == server_span.context.trace_id and span.parent is not None
        headers = {k.lower(): v for k, v in (l.split(": ", 1) for l in received[0].decode().split("\\r\\n")[1:] if ": " in l)}
        expected = f"00-{span.context.trace_id:032x}-{span.context.span_id:016x}-"
        assert headers.get("traceparent", "").startswith(expected), (headers, expected)
        tracing.shutdown_tracing()
        print("OB13 OK")
    """, **OTLP)
    assert "OB13 OK" in out


# --- D1 · D3 (plan 2026-11-22) -----------------------------------------------------------------------


def test_a_second_create_app_in_the_same_process_still_emits_request_spans(clone: Path, tmp_path: Path):
    """D1: la guardia de "ya configurado" cubre el provider, SQLAlchemy y httpx, no `instrument_app`.

    Antes, el segundo `create_app()` (lo que hacen los tests) quedaba sin instrumentar. Con FastAPI 0.165 igual
    sale un span de request (telemetría OTel nativa de FastAPI con el provider global), pero sin `excluded_urls`:
    `/health/*` y `/metrics` se trazan. Por eso el test pide las dos cosas: span de `/ping` y ninguno de `/health/live`."""
    out = python(clone, tmp_path, """
        from fastapi.testclient import TestClient
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from opentelemetry.trace import SpanKind

        from app.main import create_app
        from app.observability import tracing

        apps = [create_app(), create_app()]
        assert tracing._provider is not None
        exporter = InMemorySpanExporter()
        tracing._provider.add_span_processor(SimpleSpanProcessor(exporter))
        for i, app in enumerate(apps):
            @app.get("/ping")
            def ping() -> dict[str, bool]:
                return {"ok": True}

            client = TestClient(app)
            exporter.clear()
            assert client.get("/health/live").status_code == 200
            assert not exporter.get_finished_spans(), (i, [s.name for s in exporter.get_finished_spans()])
            assert client.get("/ping").status_code == 200
            server = [s.name for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER]
            assert server == ["GET /ping"], (i, server)
        tracing.shutdown_tracing()
        print("D1 OK")
    """, **OTLP)
    assert "D1 OK" in out


def test_app_installation_reaches_the_log_line_and_the_trace_resource(clone: Path, tmp_path: Path):
    script = """
        import json
        import logging
        import sys

        from fastapi import FastAPI
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.config import get_settings
        from app.observability import tracing
        from app.observability.logging import configure_logging

        settings = get_settings()
        configure_logging(settings)
        tracing.setup_tracing(FastAPI(), create_async_engine("sqlite+aiosqlite://"), settings)
        logging.getLogger("check").warning("hello")
        sys.stdout.flush()
        resource = dict(tracing._provider.resource.attributes)
        print("RESOURCE", json.dumps(resource.get("installation")))
        tracing.shutdown_tracing()
    """
    with_name = python(clone, tmp_path, script, APP_INSTALLATION="tienda-norte", **OTLP)
    line = json.loads(next(l for l in with_name.splitlines() if '"msg": "hello"' in l))
    assert line["installation"] == "tienda-norte" and 'RESOURCE "tienda-norte"' in with_name
    without = python(clone, tmp_path, script, **OTLP)
    line = json.loads(next(l for l in without.splitlines() if '"msg": "hello"' in l))
    assert "installation" not in line and "RESOURCE null" in without


# --- OB-16 -------------------------------------------------------------------------------------------


def test_a_domain_404_leaves_a_log_line_with_trace_id_and_docs_does_not(clone: Path, tmp_path: Path):
    out = python(clone, tmp_path, """
        import json
        import re
        import sys

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.config import get_settings
        from app.errors import NotFoundError, register_exception_handlers
        from app.observability.logging import configure_logging
        from app.observability import tracing

        settings = get_settings()
        configure_logging(settings)
        app = FastAPI()
        register_exception_handlers(app)
        tracing.setup_tracing(app, create_async_engine("sqlite+aiosqlite://"), settings)

        @app.get("/api/v1/orders/{order_id}")
        def order(order_id: int) -> None:
            raise NotFoundError(f"Order {order_id} not found")

        client = TestClient(app)
        marker = "---docs---"
        client.get("/docs")
        sys.stdout.write(marker + "\\n")
        assert client.get("/api/v1/orders/999999").status_code == 404
        tracing.shutdown_tracing()
        print("OB16 DONE")
    """, DOCS_ENABLED="true", **OTLP)
    before, after = out.split("---docs---")
    assert "trace_id" not in before  # /docs no deja ningún log: no sirve para probar la correlación
    lines = [line for line in after.splitlines() if line.startswith("{")]
    domain = [line for line in lines if '"domain error"' in line]
    assert domain and re.search(r'"trace_id": "[0-9a-f]{32}"', domain[0]), after


# --- TS-07 · OB-09 -----------------------------------------------------------------------------------


def test_published_tracing_test_passes_in_the_clone(clone: Path):
    assert (clone / "tests" / "test_tracing.py").exists()
    out = ok(["uv", "run", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_tracing.py"], clone)
    assert "1 passed" in out


# --- plan 2026-11-22 · el envío real por OTLP ---------------------------------------------------------------


def test_spans_reach_tempo_over_otlp_and_come_back_from_its_api(clone: Path, tmp_path: Path):
    """`setup_tracing` publicado exporta por gRPC (4317) a Tempo con la config y el tag de `stack.md`, y la traza
    vuelve por `/api/v2/traces/<id>` con `service.name`. Reemplaza la corrida manual del 2026-10-23 (módulo sin
    el instrumentor de httpx). Sin Docker se saltea."""
    if shutil.which("docker") is None:
        pytest.skip("requiere docker")
    stack = {"file": "references/stack.md"}
    image = re.search(r"image: (grafana/tempo:[\w.\-]+)", block("defining-grafana-slos", "grafana/tempo:", **stack)).group(1)
    (tmp_path / "tempo.yml").write_text(block("defining-grafana-slos", "backend_scheduler", **stack), encoding="utf-8")
    name = f"tempo-otlp-{time.monotonic_ns()}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "--user", "root", "-p", "127.0.0.1::4317",
                    "-p", "127.0.0.1::3200", "-v", f"{tmp_path / 'tempo.yml'}:/etc/tempo/tempo.yml:ro,z", image,
                    "-config.file=/etc/tempo/tempo.yml"], check=True, capture_output=True)
    try:
        def host_port(container_port: str) -> str:
            return subprocess.run(["docker", "port", name, f"{container_port}/tcp"], check=True, capture_output=True,
                                  text=True).stdout.split(":")[-1].strip()

        grpc, http = host_port("4317"), host_port("3200")
        for _ in range(60):  # Tempo tarda unos segundos en declararse listo
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{http}/ready", timeout=2).read().startswith(b"ready"):
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            pytest.fail("Tempo no llegó a ready: " + subprocess.run(["docker", "logs", "--tail", "20", name],
                                                                   capture_output=True, text=True).stderr)
        out = python(clone, tmp_path, """
            from fastapi import FastAPI
            from opentelemetry import trace
            from sqlalchemy.ext.asyncio import create_async_engine

            from app.config import get_settings
            from app.observability import tracing

            tracing.setup_tracing(FastAPI(), create_async_engine("sqlite+aiosqlite://"), get_settings())
            with trace.get_tracer("otlp-check").start_as_current_span("otlp-check") as span:
                print("TRACE", format(span.get_span_context().trace_id, "032x"))
            tracing.shutdown_tracing()  # flush del BatchSpanProcessor
        """, OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{grpc}", OTEL_EXPORTER_OTLP_INSECURE="true")
        trace_id = re.search(r"TRACE ([0-9a-f]{32})", out).group(1)
        body = ""
        for _ in range(30):  # el ingester demora en servir lo recién escrito
            try:
                body = urllib.request.urlopen(f"http://127.0.0.1:{http}/api/v2/traces/{trace_id}", timeout=3).read().decode()
                if "otlp-check" in body:
                    break
            except OSError:
                pass
            time.sleep(1)
        assert "otlp-check" in body and "orders-api" in body, body[:500]
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)
