"""Ola 5 (observabilidad), parte Python: lo que se ve ejecutando el código publicado.

OB-06 (buckets en /metrics), OB-12 (dos workers de gunicorn suman bien), OB-13 (span CLIENT con
`traceparent` contra httpx.MockTransport), OB-16 (una request que sí loguea deja `trace_id`) y
TS-07·OB-09 (el test de tracing publicado pasa en el proyecto armado desde las skills).

Arma el mismo clon que test_wave2_project.py (bootstrap de scaffolding + bloques de las skills);
necesita `uv` y red o caché de uv.

Uso (desde la raíz del repo):
    uv run --with pytest --with pyyaml pytest tests/snippets/test_wave5_python.py -v
"""

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
