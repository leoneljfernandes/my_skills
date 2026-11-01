"""Ola 2: lo que solo se ve armando un proyecto de verdad, con `uv` y sin PYTHONPATH.

Arma un clon limpio con el `pyproject.toml` publicado en scaffolding (bootstrap incluido), le
vuelca los bloques de las skills con `reference/build_ref.py` y corre las herramientas reales.
Necesita `uv` y red (o caché de uv); sin `uv` se saltea. Lo de Docker se saltea sin Docker.

Uso (desde la raíz del repo):
    uv run --with pytest --with pyyaml pytest tests/snippets/test_wave2_project.py -v
"""

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from extract import SKILLS, block, fenced_blocks  # noqa: E402

HERE = Path(__file__).parent
SCAF = "scaffolding-fastapi-backends"
pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="requiere uv")


def clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "SKILLS_DIR_UNSET"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["TEST_DB"] = ""  # el clon corre en SQLite aunque el entorno pida Postgres
    return {**env, **extra}


def run(cmd: list[str], cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=clean_env(**env), capture_output=True, text=True, timeout=600)


def ok(cmd: list[str], cwd: Path, **env: str) -> str:
    done = run(cmd, cwd, **env)
    assert done.returncode == 0, f"{' '.join(cmd)}\n{done.stdout}\n{done.stderr}"
    return done.stdout + done.stderr


@pytest.fixture(scope="module")
def clone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """El bootstrap de scaffolding, tal como está escrito, más los bloques de las skills."""
    root = tmp_path_factory.mktemp("clone")
    ok(["uv", "init", "--bare", "--python", "3.14", "my-api"], root)
    project = root / "my-api"
    assert sorted(p.name for p in project.iterdir()) == ["pyproject.toml"]  # --bare: sin src/ ni build-system
    (project / "pyproject.toml").write_text(block(SCAF, 'name = "my-api"'), encoding="utf-8")
    ok(["uv", "sync"], project)
    ok([sys.executable, str(HERE / "reference" / "build_ref.py"), str(project)], project)
    # El bootstrap no crea tests/__init__.py: `from tests.factories import ...` lo resuelve `pythonpath`.
    (project / "tests" / "__init__.py").unlink()
    return project


def test_bootstrap_installs_what_the_pyproject_declares(clone: Path):
    ok(["uv", "run", "python", "-c", textwrap.dedent("""
        from pydantic import EmailStr, TypeAdapter
        TypeAdapter(EmailStr).validate_python("ana@example.com")
        import jwt, multipart, pwdlib, prometheus_client, prometheus_fastapi_instrumentator
        import opentelemetry.sdk, opentelemetry.instrumentation.fastapi, opentelemetry.instrumentation.sqlalchemy
    """)], clone)
    assert "coverage" in ok(["uv", "run", "coverage", "--version"], clone).lower()


def test_uv_run_pytest_works_without_pythonpath(clone: Path):
    out = ok(["uv", "run", "pytest", "-q", "-p", "no:cacheprovider"], clone)
    assert re.search(r"\d+ passed", out) and "No module named" not in out
    ok(["uv", "run", "coverage", "run", "--source=app", "-m", "pytest", "-q", "-p", "no:cacheprovider"], clone)
    ok(["uv", "run", "coverage", "lcov", "-o", "coverage.lcov"], clone)


def test_layers_are_enforced_by_lint_imports_and_a_violation_fails(clone: Path):
    ok(["uv", "run", "lint-imports"], clone)
    service = clone / "app" / "services" / "order.py"
    original = service.read_text(encoding="utf-8")
    try:
        service.write_text("from app.api import deps  # noqa: F401\n" + original, encoding="utf-8")
        broken = run(["uv", "run", "lint-imports"], clone)
        assert broken.returncode != 0 and "Capas" in broken.stdout
    finally:
        service.write_text(original, encoding="utf-8")


def test_api_importing_crud_outside_deps_is_rejected_and_deps_is_allowed(clone: Path):
    """BE-17: la forma real de `ignore_imports` (ya está en el KEPT de arriba, acá la violación)."""
    router = clone / "app" / "api" / "orders.py"
    original = router.read_text(encoding="utf-8")
    try:
        router.write_text("from app.crud.order import OrderRepository  # noqa: F401\n" + original, encoding="utf-8")
        broken = run(["uv", "run", "lint-imports"], clone)
        assert broken.returncode != 0 and "Solo api/deps.py compone" in broken.stdout
    finally:
        router.write_text(original, encoding="utf-8")


def test_published_blocks_pass_ruff_and_mypy(clone: Path):
    ok(["uv", "run", "mypy", "app"], clone)
    verbatim = ["app/main.py", "app/api/health.py", "app/api/orders.py", "app/crud/health.py", "app/crud/order.py",
                "app/crud/product.py", "app/observability/tracing.py", "app/errors.py", "app/config.py", "app/database.py"]
    ok(["uv", "run", "ruff", "check", *verbatim], clone)


def test_frozen_accepts_a_stale_lock_and_locked_rejects_it(clone: Path, tmp_path: Path):
    shutil.copy(clone / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(clone / "uv.lock", tmp_path / "uv.lock")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('"alembic",', '"alembic", "certifi",', 1), encoding="utf-8")
    assert run(["uv", "sync", "--frozen"], tmp_path).returncode == 0
    stale = run(["uv", "sync", "--locked"], tmp_path)
    assert stale.returncode != 0 and "lock" in (stale.stdout + stale.stderr).lower()


# --- BE-03 · OB-11: la app se arma por pasos -------------------------------------------------------

BLOCKER = textwrap.dedent("""
    import sys
    from importlib.abc import MetaPathFinder

    class Blocker(MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "prometheus_fastapi_instrumentator" or name.startswith(
                ("opentelemetry.sdk", "opentelemetry.exporter", "opentelemetry.instrumentation")
            ):
                raise ImportError(f"blocked at this step: {name}")

    sys.meta_path.insert(0, Blocker())
""")


def strip_steps(code: str, keep_up_to: int) -> str:
    """Quita las líneas que terminan en `# paso N` con N mayor al paso que se está armando."""
    def later(line: str) -> bool:
        m = re.search(r"# paso (\d+)\b", line)
        return bool(m) and int(m.group(1)) > keep_up_to
    return "".join(line for line in code.splitlines(keepends=True) if not later(line))


def write_app(root: Path, step: int) -> None:
    def w(rel: str, body: str) -> None:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")

    for pkg in ("app", "app/api", "app/observability", "app/crud"):
        w(f"{pkg}/__init__.py", "")
    w("app/config.py", block("configuring-fastapi-settings", "class Settings(BaseSettings)"))
    w("app/errors.py", block("handling-fastapi-errors", "class AppError"))
    w("app/observability/tracing.py", block("tracing-with-opentelemetry", "def setup_tracing"))
    w("app/api/router.py", "from fastapi import APIRouter\n\napi_router = APIRouter()\n")
    w("app/api/health.py", strip_steps(block("layering-fastapi-apps", 'prefix="/health"'), step))
    w("app/main.py", strip_steps(block("layering-fastapi-apps", "def create_app"), step))
    if step >= 3:
        w("app/database.py", block("configuring-sqlalchemy-sessions", "def build_engine"))
        w("app/crud/health.py", block("layering-fastapi-apps", "class HealthRepository"))
        w("app/api/deps.py", textwrap.dedent("""
            from typing import Annotated
            from fastapi import Depends
            from app.crud.health import HealthRepository
            from app.database import DbSession

            def get_health_repository(db: DbSession) -> HealthRepository:
                return HealthRepository(db)

            HealthRepoDep = Annotated[HealthRepository, Depends(get_health_repository)]
        """))
    if step >= 8:
        w("app/observability/logging.py", block("logging-json-to-loki", "class JsonFormatter"))
        w("app/observability/metrics.py", block("exposing-prometheus-metrics", "ORDERS_CREATED = Counter"))


ENV = {"APP_ENV": "test", "SECRET_KEY": "k" * 40, "DB_USER": "t", "DB_PASSWORD": "t", "DB_HOST": "test-db.invalid",
       "DB_NAME": "t", "ERRORS_BASE_URL": "https://errors.test.invalid", "COOKIE_SECURE": "false"}


def run_step(clone: Path, tmp_path: Path, step: int, script: str, **env: str) -> str:
    write_app(tmp_path, step)
    prelude = BLOCKER if step < 8 else ""
    (tmp_path / "check.py").write_text(prelude + textwrap.dedent(script), encoding="utf-8")
    return ok(["uv", "run", "--project", str(clone), "python", str(tmp_path / "check.py")], tmp_path,
              PYTHONPATH=str(tmp_path), **{**ENV, **env})


def test_step_2_imports_and_serves_health_live_with_only_the_otel_api(clone: Path, tmp_path: Path):
    out = run_step(clone, tmp_path, 2, """
        import app.main
        from app.observability.tracing import current_trace_id
        from fastapi.testclient import TestClient

        client = TestClient(app.main.app)
        assert client.get("/health/live").json() == {"status": "ok"}
        assert "/health/ready" not in app.main.app.openapi()["paths"]
        assert client.get("/metrics").status_code == 404
        assert client.get("/nope").json()["type"].endswith("/http_404")  # errors.py funciona sin SDK
        assert current_trace_id() is None
        print("STEP2 OK")
    """)
    assert "STEP2 OK" in out


def test_step_3_adds_ready_and_the_engine(clone: Path, tmp_path: Path):
    out = run_step(clone, tmp_path, 3, """
        import app.main
        assert "/health/ready" in app.main.app.openapi()["paths"]
        import asyncio
        async def main():
            async with app.main.app.router.lifespan_context(app.main.app):
                pass
        asyncio.run(main())  # el lifespan del paso 3 cierra el engine sin tracing ni SDK
        print("STEP3 OK")
    """)
    assert "STEP3 OK" in out


def test_step_8_turns_on_metrics_and_tracing_with_their_flags(clone: Path, tmp_path: Path):
    out = run_step(clone, tmp_path, 8, """
        import app.main
        from fastapi.testclient import TestClient
        from app.observability import tracing

        assert TestClient(app.main.app).get("/metrics").status_code == 200
        assert tracing._provider is not None
        tracing.shutdown_tracing()
        print("STEP8 OK")
    """, METRICS_ENABLED="true", OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317")
    assert "STEP8 OK" in out


# --- BE-13 -----------------------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("docker") is None, reason="requiere docker")
def test_docker_compose_config_publishes_only_the_frontend(tmp_path: Path):
    docker = (SKILLS / "backend" / SCAF / "references" / "docker.md").read_text(encoding="utf-8")
    compose, override = [code for lang, code, _ in fenced_blocks(docker) if lang == "yaml" and "services:" in code][:2]
    (tmp_path / "docker-compose.yml").write_text(compose, encoding="utf-8")
    (tmp_path / "docker-compose.override.yml").write_text(override, encoding="utf-8")
    (tmp_path / ".env").write_text("DB_USER=app\nDB_PASSWORD=x\nDB_NAME=app_db\nSECRET_KEY=x\n", encoding="utf-8")
    for service in ("backend", "frontend"):
        (tmp_path / service).mkdir()

    def published(*files: str) -> dict[str, list[object]]:
        args = [arg for f in files for arg in ("-f", f)]
        done = subprocess.run(["docker", "compose", *args, "config", "--format", "json"], cwd=tmp_path,
                              capture_output=True, text=True, env=clean_env(), timeout=120)
        assert done.returncode == 0, done.stderr
        services = json.loads(done.stdout)["services"]
        return {name: svc["ports"] for name, svc in services.items() if svc.get("ports")}

    assert set(published("docker-compose.yml")) == {"frontend"}  # producción: solo el frontend
    assert {"frontend", "db", "backend"} <= set(published("docker-compose.yml", "docker-compose.override.yml"))


def test_compose_files_parse_as_yaml_without_docker():
    docker = (SKILLS / "backend" / SCAF / "references" / "docker.md").read_text(encoding="utf-8")
    for lang, code, _ in fenced_blocks(docker):
        if lang == "yaml":
            yaml.safe_load(code)


# --- DB-10: env.py publicado contra el proyecto de referencia ---------------------------------------


@pytest.mark.skipif(shutil.which("docker") is None, reason="requiere docker")
def test_alembic_env_sees_every_model_through_app_models(clone: Path):
    """env.py publicado + `app/models/__init__.py` publicado: autogenerate propone todas las tablas."""
    image = re.search(r"image: (postgres:[\w.\-]+)", (SKILLS / "backend" / SCAF / "references" / "docker.md").read_text()).group(1)
    name = f"wave2_pg_{os.getpid()}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=x",
                    "-e", "POSTGRES_DB=mig", image], check=True, capture_output=True)
    try:
        port = subprocess.run(["docker", "port", name, "5432/tcp"], check=True, capture_output=True, text=True).stdout.split(":")[-1].strip()
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres", "-d", "mig"], capture_output=True).returncode == 0:
                break
            subprocess.run(["sleep", "1"])
        env = {**ENV, "APP_ENV": "dev", "DB_USER": "postgres", "DB_PASSWORD": "x", "DB_HOST": "127.0.0.1", "DB_PORT": port,
               "DB_NAME": "mig"}
        migrations = clone / "alembic"
        shutil.rmtree(migrations, ignore_errors=True)
        (clone / "alembic.ini").unlink(missing_ok=True)
        ok(["uv", "run", "alembic", "init", "-t", "async", "alembic"], clone)
        (migrations / "env.py").write_text(block("migrating-with-alembic", "async def run_async_migrations"), encoding="utf-8")
        ok(["uv", "run", "alembic", "revision", "--autogenerate", "-m", "init"], clone, **env)
        generated = next((migrations / "versions").glob("*_init.py")).read_text(encoding="utf-8")
        for table in ("products", "orders", "users", "roles", "sessions"):
            assert f"'{table}'" in generated or f'"{table}"' in generated, table
        ok(["uv", "run", "alembic", "upgrade", "head"], clone, **env)
        assert "No new upgrade operations" in ok(["uv", "run", "alembic", "check"], clone, **env)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        shutil.rmtree(clone / "alembic", ignore_errors=True)
        (clone / "alembic.ini").unlink(missing_ok=True)
