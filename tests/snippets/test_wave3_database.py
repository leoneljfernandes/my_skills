"""Ola 3 (base de datos): lo que las skills de `database` afirman, ejecutado.

Arma el proyecto de referencia con `reference/build_ref.py` en un directorio temporal y corre
alembic, ruff y mypy sobre él. Lo que necesita Postgres usa Docker (`postgres:16.15-alpine`, el
tag de docker.md) con un contenedor propio que se borra al terminar; sin Docker se saltea.

Uso (desde la raíz del repo):
    uv run --with pytest --with pydantic-settings --with fastapi --with 'sqlalchemy[asyncio]>=2.0.40,<2.1' \
        --with pyyaml --with alembic --with asyncpg --with 'psycopg[binary]' --with ruff --with mypy \
        pytest tests/snippets/test_wave3_database.py -v
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from extract import SKILLS, block, fenced_blocks  # noqa: E402
from test_python_snippets import load_settings_module  # noqa: E402

HERE = Path(__file__).parent
SESSIONS = "configuring-sqlalchemy-sessions"
MIGRATING = "migrating-with-alembic"
MODELING = "modeling-postgres-with-sqlalchemy"
IMAGE = "postgres:16.15-alpine"
GLUE_REV = "29d33780007f"  # la revisión base que las migraciones de la skill suponen ya aplicada
REV_CHECK, REV_VALIDATE, REV_INDEX = "4156339bb843", "7c1e5a9d2b30", "a3f9c0de5b71"


def text(rel: str) -> str:
    return (SKILLS / rel).read_text(encoding="utf-8")


def migrating() -> str:
    return text(f"database/{MIGRATING}/SKILL.md")


def sessions() -> str:
    return text(f"database/{SESSIONS}/SKILL.md")


def modeling() -> str:
    return text(f"database/{MODELING}/SKILL.md")


needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="requiere docker")


# --- Estáticos: DB-02, DB-03, DB-05, DB-08, DB-15, DB-17, DB-19, DB-20 y el "SET NOT NULL" ----------


def test_db02_not_valid_and_validate_are_never_in_the_same_block():
    for lang, code, line in fenced_blocks(migrating()):
        if lang != "python":
            continue  # el SQL de "SET NOT NULL" muestra los tres pasos con la nota de que van en revisiones distintas
        assert not ("postgresql_not_valid" in code and "VALIDATE CONSTRAINT" in code), f"migrating:{line}"


def test_db02_rule_says_separate_revisions():
    rules = migrating().split("## Ejemplos")[0]
    assert "en revisiones separadas" in rules
    assert "lo que la skill evita" not in rules


def test_db03_index_revision_has_no_transactional_ddl_and_is_retryable():
    blocks = [code for _, code, _ in fenced_blocks(migrating())]
    index_rev = [c for c in blocks if "autocommit_block" in c and "revision: str" in c]
    assert len(index_rev) == 1
    code = index_rev[0]
    assert "create_check_constraint" not in code and "VALIDATE" not in code and "add_column" not in code
    assert "if_not_exists" not in code  # acepta un índice inválido: no sirve para reintentar
    assert code.index("drop_index") < code.index("create_index")
    assert "if_exists=True" in code


def test_db03_rules_and_checklist():
    t = migrating()
    rules, checklist = t.split("## Ejemplos")[0], t.split("## Checklist de verificación")[1]
    assert "no mezcla DDL transaccional" in rules
    assert "IF NOT EXISTS" in rules and "inválido" in rules
    assert "indisvalid" in checklist and "pg_index" in checklist


def test_db05_autogenerate_does_not_detect_check_only_on_existing_tables():
    t = migrating()
    assert "autogenerate NO detecta CHECK constraints." not in t
    assert "tabla existente" in t.split("## Ejemplos")[0]
    assert "no duplicarlos" in t


def test_db08_rename_example_states_its_maintenance_window():
    t = migrating()
    head = t.split("Renombre de columna")[1][:400]
    assert "ventana de mantenimiento" in head and "expand/contract" in head
    assert "expand/contract" in next(l for l in t.splitlines() if l.startswith("| Aplicar autogenerate sin leerlo"))


def test_db15_many_to_one_example_uses_joinedload():
    code = block(MODELING, "async def get_with_product")
    assert "joinedload(Order.product)" in code and "selectinload" not in code
    assert "carga explícita" in sessions()


def test_db17_native_enum_reason_is_not_the_obsolete_one():
    assert "no corre en transacción" not in modeling()
    assert "no se puede quitar un valor" in modeling()


def test_db19_render_item_explains_the_real_symptom():
    rule = next(l for l in migrating().splitlines() if "render_item" in l)
    assert "NameError" in rule and "import app.models" not in rule


def test_db20_description_symptoms_have_a_diagnosis_in_the_body():
    body = sessions().split("---", 2)[2]
    assert "DetachedInstanceError" in body
    body = migrating().split("---", 2)[2]
    assert "Target database is not up to date" in body


def test_set_not_null_on_big_tables_goes_through_a_validated_check():
    t = migrating().split("## Ejemplos")[0]
    assert "SET NOT NULL" in t and "NOT VALID" in t
    line = next(l for l in t.splitlines() if "SET NOT NULL" in l and l.startswith("|"))
    assert "CHECK" in line and "VALIDATE" in line


def test_health_endpoints_are_not_mounted_under_the_api_prefix():
    """D06: /health/* cuelga de la raíz (layering); sessions no puede decir lo contrario."""
    t = sessions()
    assert "/api/v1/health" not in t
    assert "bajo el prefijo de la API" not in t


# --- Settings: DB-04, DB-06, DB-07 -------------------------------------------------------------------


def test_db04_migration_url_falls_back_to_database_url(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch)
    s = mod.Settings(_env_file=None)
    assert s.MIGRATION_DATABASE_URL == s.DATABASE_URL
    assert "hunter2-pass" not in repr(s) and "MIGRATION_DATABASE_URL" not in repr(s)


def test_db04_migration_url_uses_its_own_host_and_port(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch, DB_HOST="pooler", DB_PORT="6432", DB_MIGRATION_HOST="db", DB_MIGRATION_PORT="5432")
    s = mod.Settings(_env_file=None)
    assert "@pooler:6432/" in s.DATABASE_URL
    assert "@db:5432/" in s.MIGRATION_DATABASE_URL
    assert s.MIGRATION_DATABASE_URL.split("@")[0] == s.DATABASE_URL.split("@")[0]  # mismas credenciales
    monkeypatch.delenv("DB_MIGRATION_PORT")
    assert "@db:6432/" in mod.Settings(_env_file=None).MIGRATION_DATABASE_URL  # el puerto cae en DB_PORT


def test_db04_env_py_reads_the_migration_url():
    env_py = block(MIGRATING, "async def run_async_migrations")
    assert "get_settings().MIGRATION_DATABASE_URL" in env_py
    assert "DATABASE_URL" not in env_py.replace("MIGRATION_DATABASE_URL", "")


def test_db07_database_url_follows_the_driver(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch)
    assert mod.Settings(_env_file=None).DATABASE_URL.startswith("postgresql+asyncpg://")
    monkeypatch.setenv("DB_DRIVER", "psycopg")
    s = mod.Settings(_env_file=None)
    assert s.DATABASE_URL.startswith("postgresql+psycopg://") and s.MIGRATION_DATABASE_URL.startswith("postgresql+psycopg://")
    monkeypatch.setenv("DB_DRIVER", "mysql")
    with pytest.raises(Exception, match="DB_DRIVER"):
        mod.Settings(_env_file=None)


# --- El proyecto armado desde las SKILL.md -------------------------------------------------------------

ENV = {"APP_ENV": "test", "SECRET_KEY": "k" * 40, "DB_USER": "postgres", "DB_PASSWORD": "x", "DB_HOST": "pooler.invalid",
       "DB_NAME": "mig", "ERRORS_BASE_URL": "https://errors.test.invalid", "COOKIE_SECURE": "false"}


def run(cmd: list[str], cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    full = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "TEST_DB": "", **ENV, **env}
    return subprocess.run(cmd, cwd=cwd, env=full, capture_output=True, text=True, timeout=300)


def ok(cmd: list[str], cwd: Path, **env: str) -> str:
    done = run(cmd, cwd, **env)
    assert done.returncode == 0, f"{' '.join(cmd)}\n{done.stdout}\n{done.stderr}"
    return done.stdout + done.stderr


def alembic(proj: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, "-m", "alembic", *args], proj, **env)


def build_project(root: Path) -> None:
    """Sólo lo que esta ola necesita, desde los bloques publicados (el pegamento es el de `reference/build_ref.py`)."""
    def w(rel: str, code: str) -> None:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(code, encoding="utf-8")

    for pkg in ("app", "app/models"):
        w(f"{pkg}/__init__.py", "")
    w("app/config.py", block("configuring-fastapi-settings", "class Settings(BaseSettings)"))
    w("app/database.py", block(SESSIONS, "def build_engine"))
    w("app/models/base.py", block(MODELING, "class UtcDateTime"))
    product_src, order_src = block(MODELING, "class Product(TimestampMixin").split("class OrderStatus(StrEnum):")
    w("app/models/product.py", "from decimal import Decimal\nfrom sqlalchemy import CheckConstraint, Index, Numeric, String\n"
      "from sqlalchemy.orm import Mapped, mapped_column\nfrom app.models.base import Base, BigIntPK, TimestampMixin\n" + product_src)
    w("app/models/order.py", "from decimal import Decimal\nfrom enum import StrEnum\n"
      "from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, String, text\n"
      "from sqlalchemy.orm import Mapped, mapped_column, relationship\nfrom app.models.base import Base, BigIntPK, TimestampMixin\n"
      "from app.models.product import Product\n" + "class OrderStatus(StrEnum):" + order_src)
    w("app/models/__init__.py", block(MODELING, "from app.models.base import Base, BigIntPK"))


@pytest.fixture(scope="module")
def proj(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("wave3") / "project"
    root.mkdir()
    build_project(root)
    return root


def test_db13_blocks_pass_ruff_f_and_i(proj: Path):
    """F (imports duplicados) e I (orden) sobre los bloques completos; `alembic/` y `app/` existen, como en un proyecto real."""
    (proj / "alembic" / "versions").mkdir(parents=True, exist_ok=True)
    files = {
        "app/models/base.py": block(MODELING, "class UtcDateTime"),
        "app/database.py": block(SESSIONS, "def build_engine"),
        "alembic/env.py": block(MIGRATING, "async def run_async_migrations"),
        "alembic/versions/check.py": block(MIGRATING, f'revision: str = "{REV_CHECK}"'),
        "alembic/versions/validate.py": block(MIGRATING, f'revision: str = "{REV_VALIDATE}"'),
        "alembic/versions/index.py": block(MIGRATING, f'revision: str = "{REV_INDEX}"'),
    }
    for rel, code in files.items():
        (proj / rel).write_text(code, encoding="utf-8")
    done = run([sys.executable, "-m", "ruff", "check", "--isolated", "--line-length", "110", "--select", "F,I", *files], proj)
    assert done.returncode == 0, done.stdout + done.stderr


def test_db14_worker_block_passes_mypy_strict(proj: Path):
    """`result.rowcount` no existe en `Result[Any]`: el bloque lo trata como `CursorResult`."""
    (proj / "app" / "workers.py").write_text(block(SESSIONS, "async def expire_pending_orders"), encoding="utf-8")
    done = run([sys.executable, "-m", "mypy", "--strict", "--follow-imports=silent", "--explicit-package-bases",
                "--no-incremental", "--cache-dir=/dev/null", "app/workers.py"], proj)
    assert done.returncode == 0, done.stdout + done.stderr


def test_db05_autogenerate_writes_the_checks_in_create_table(proj: Path):
    """Sobre una tabla nueva autogenerate escribe los CHECK: la migración manual los duplicaría."""
    script = """
import sqlalchemy as sa
from alembic.autogenerate import produce_migrations, render_python_code
from alembic.migration import MigrationContext
from app.models import Base
with sa.create_engine("sqlite://").connect() as conn:
    ops = produce_migrations(MigrationContext.configure(conn), Base.metadata)
    print(render_python_code(ops.upgrade_ops))
"""
    out = ok([sys.executable, "-c", script], proj, PYTHONPATH=str(proj))
    assert "create_constraint=True" in out
    assert "ck_products_price_non_negative" in out


def test_db06_build_engine_with_pgbouncer_flag_uses_nullpool_without_server_settings(proj: Path):
    script = """
import json
from unittest import mock
import app.database as d
from app.config import Settings
from sqlalchemy.pool import NullPool
s = Settings(_env_file=None)
with mock.patch.object(d, "create_async_engine") as m:
    d.build_engine(s)
kw = m.call_args.kwargs
real = d.build_engine(s)  # sin la rama, create_engine falla con TypeError por pool_size
print(json.dumps({"nullpool": kw.get("poolclass") is NullPool, "keys": sorted(kw), "connect_args": kw.get("connect_args"), "pool": type(real.pool).__name__}))
"""
    base = {"PYTHONPATH": str(proj)}
    out = json.loads(ok([sys.executable, "-c", script], proj, DB_PGBOUNCER="true", **base).splitlines()[-1])
    assert out["nullpool"] and out["pool"] == "NullPool"
    assert "pool_size" not in out["keys"] and "server_settings" not in (out["connect_args"] or {})
    assert out["connect_args"] == {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    out = json.loads(ok([sys.executable, "-c", script], proj, DB_PGBOUNCER="false", **base).splitlines()[-1])
    assert not out["nullpool"] and out["connect_args"]["server_settings"]["statement_timeout"] == "15000"


# --- Con Postgres 16.15 en Docker -----------------------------------------------------------------


@pytest.fixture(scope="module")
def pg():
    name = f"wave3_pg_{os.getpid()}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=x",
                    "-e", "POSTGRES_DB=mig", IMAGE], check=True, capture_output=True)
    try:
        port = subprocess.run(["docker", "port", name, "5432/tcp"], check=True, capture_output=True, text=True).stdout.split(":")[-1].strip()
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres", "-d", "mig", "-h", "127.0.0.1"], capture_output=True).returncode == 0:
                break
            time.sleep(1)
        time.sleep(1)
        yield {"name": name, "port": port}
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def psql(pg: dict[str, str], sql: str, db: str = "mig") -> str:
    done = subprocess.run(["docker", "exec", pg["name"], "psql", "-U", "postgres", "-d", db, "-Atc", sql], capture_output=True, text=True)
    return done.stdout.strip() + done.stderr.strip()


GLUE_BASE = f'''"""Base (glue): las tablas que la migración de la skill supone ya creadas."""
import sqlalchemy as sa
from alembic import op

revision = "{GLUE_REV}"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("products", sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True), sa.Column("name", sa.String(100), nullable=False))
    op.create_table("orders", sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True), sa.Column("status", sa.String(20), nullable=False))


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_table("products")
'''


@pytest.fixture(scope="module")
def migrations(proj: Path, pg: dict[str, str]) -> dict[str, str]:
    """`alembic init -t async` + el env.py publicado + la base glue + las tres revisiones publicadas."""
    env = {"DB_HOST": "pooler.invalid", "DB_PORT": "6432", "DB_MIGRATION_HOST": "127.0.0.1", "DB_MIGRATION_PORT": pg["port"]}
    shutil.rmtree(proj / "alembic", ignore_errors=True)
    (proj / "alembic.ini").unlink(missing_ok=True)
    ok([sys.executable, "-m", "alembic", "init", "-t", "async", "alembic"], proj)
    (proj / "alembic" / "env.py").write_text(block(MIGRATING, "async def run_async_migrations"), encoding="utf-8")
    versions = proj / "alembic" / "versions"
    (versions / "base.py").write_text(GLUE_BASE, encoding="utf-8")
    for name, rev in (("check", REV_CHECK), ("validate", REV_VALIDATE), ("index", REV_INDEX)):
        (versions / f"{name}.py").write_text(block(MIGRATING, f'revision: str = "{rev}"'), encoding="utf-8")
    return env


def test_db02_db09_offline_sql_has_lock_timeout_first_and_a_commit_between_not_valid_and_validate(proj: Path, migrations):
    done = alembic(proj, "upgrade", "head", "--sql", **migrations)
    assert done.returncode == 0, done.stderr
    sql = done.stdout
    assert "lock_timeout" in sql and sql.index("lock_timeout") < sql.index("CREATE TABLE")  # DB-09
    add, validate = sql.index("NOT VALID"), sql.index("VALIDATE CONSTRAINT")
    assert "COMMIT;" in sql[add:validate]  # DB-02: dos transacciones
    assert "CONCURRENTLY" in sql


@needs_docker
def test_db04_env_py_connects_through_the_migration_url_and_the_round_trip_is_clean(proj: Path, pg, migrations):
    """DB_HOST apunta a un pooler que no existe: sólo `MIGRATION_DATABASE_URL` llega a la base."""
    assert alembic(proj, "current", **{**migrations, "DB_MIGRATION_HOST": ""}).returncode != 0  # sin ella, el pooler inexistente falla
    ok([sys.executable, "-m", "alembic", "upgrade", "head"], proj, **migrations)
    assert psql(pg, f"SELECT version_num FROM alembic_version") == REV_INDEX
    assert psql(pg, "SELECT convalidated FROM pg_constraint WHERE conname = 'ck_orders_order_status'") == "t"
    assert "violates check constraint" in psql(pg, "INSERT INTO orders (status) VALUES ('bogus')")
    ok([sys.executable, "-m", "alembic", "downgrade", "base"], proj, **migrations)
    ok([sys.executable, "-m", "alembic", "upgrade", "head"], proj, **migrations)
    assert psql(pg, "SELECT count(*) FROM pg_index WHERE NOT indisvalid") == "0"
    ok([sys.executable, "-m", "alembic", "downgrade", "base"], proj, **migrations)
    # el mismo env.py async sirve con el driver psycopg (DB_DRIVER)
    assert alembic(proj, "current", DB_DRIVER="psycopg", **migrations).returncode == 0


@needs_docker
def test_db03_retry_after_a_lock_timeout_leaves_a_valid_index(proj: Path, pg, migrations):
    import psycopg

    ok([sys.executable, "-m", "alembic", "upgrade", REV_VALIDATE], proj, **migrations)
    holder = psycopg.connect(f"host=127.0.0.1 port={pg['port']} user=postgres password=x dbname=mig")
    try:
        holder.execute("INSERT INTO products (name) VALUES ('held')")  # transacción abierta sobre products
        failed = alembic(proj, "upgrade", "head", **migrations)  # lock_timeout = 5s
        assert failed.returncode != 0 and "lock" in (failed.stderr + failed.stdout).lower()
        assert psql(pg, "SELECT version_num FROM alembic_version") == REV_VALIDATE
        assert psql(pg, "SELECT indisvalid FROM pg_index WHERE indexrelid = 'ix_products_name'::regclass") == "f"
    finally:
        holder.rollback()
        holder.close()
    ok([sys.executable, "-m", "alembic", "upgrade", "head"], proj, **migrations)  # reintento
    assert psql(pg, "SELECT version_num FROM alembic_version") == REV_INDEX
    assert psql(pg, "SELECT indisvalid FROM pg_index WHERE indexrelid = 'ix_products_name'::regclass") == "t"
    assert psql(pg, "SELECT count(*) FROM pg_index WHERE NOT indisvalid") == "0"
    ok([sys.executable, "-m", "alembic", "downgrade", "base"], proj, **migrations)


@needs_docker
def test_db04_autogenerate_check_and_round_trip_with_the_published_env_py(proj: Path, pg, migrations):
    """La corrida que respalda la etiqueta de `env.py`: autogenerate, upgrade, check, downgrade base, upgrade."""
    versions = proj / "alembic" / "versions"
    stash = proj / "versions_stash"
    shutil.rmtree(stash, ignore_errors=True)
    shutil.move(str(versions), str(stash))
    versions.mkdir()
    psql(pg, "CREATE DATABASE auto", "postgres")
    env = {**migrations, "DB_NAME": "auto"}
    try:
        ok([sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", "init"], proj, **env)
        ok([sys.executable, "-m", "alembic", "upgrade", "head"], proj, **env)
        assert "No new upgrade operations" in ok([sys.executable, "-m", "alembic", "check"], proj, **env)
        ok([sys.executable, "-m", "alembic", "downgrade", "base"], proj, **env)
        ok([sys.executable, "-m", "alembic", "upgrade", "head"], proj, **env)
        assert "No new upgrade operations" in ok([sys.executable, "-m", "alembic", "check"], proj, **env)
        assert psql(pg, "SELECT 1 FROM pg_constraint WHERE conname = 'ck_orders_order_status'", "auto") == "1"
    finally:
        shutil.rmtree(versions, ignore_errors=True)
        shutil.move(str(stash), str(versions))


@needs_docker
def test_db07_sync_engine_applies_the_timeout_and_reads_settings(proj: Path, pg):
    code = block(SESSIONS, "def get_db() -> Iterator[Session]").split("def get_db")[0]
    (proj / "sync_engine.py").write_text(code, encoding="utf-8")
    script = """
from sqlalchemy import text
import sync_engine as m
with m.engine.connect() as c:
    print("RESULT", c.execute(text("SHOW statement_timeout")).scalar(), c.execute(text("SHOW application_name")).scalar(), m.engine.dialect.driver)
"""
    env = {"DB_DRIVER": "psycopg", "DB_HOST": "127.0.0.1", "DB_PORT": pg["port"], "PYTHONPATH": str(proj), "DB_STATEMENT_TIMEOUT_MS": "15000"}
    out = ok([sys.executable, "-c", script], proj, **env)
    assert "RESULT 15s orders-api psycopg" in out
    assert "hunter2" not in code and "secret@" not in code and "app:secret" not in code


@needs_docker
def test_set_not_null_skips_the_scan_after_a_validated_check(pg):
    """El "dudoso" de la auditoría: con el CHECK `IS NOT NULL` validado, `SET NOT NULL` no escanea la tabla."""
    sql = block(MIGRATING, "ck_orders_buyer_email_not_null CHECK")
    statements = [l for l in sql.splitlines() if l and not l.startswith("--")]
    assert len(statements) == 4
    psql(pg, "CREATE DATABASE nn", "postgres")
    setup = "CREATE TABLE orders (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, buyer_email text); INSERT INTO orders (buyer_email) SELECT 'a@b.c' FROM generate_series(1, 1000)"
    assert "ERROR" not in psql(pg, setup, "nn")
    debug = "SET client_min_messages = debug1; "
    # control: sin el CHECK, SET NOT NULL recorre la tabla
    control = psql(pg, debug + "ALTER TABLE orders ALTER COLUMN buyer_email SET NOT NULL", "nn")
    assert 'verifying table "orders"' in control, control
    psql(pg, "ALTER TABLE orders ALTER COLUMN buyer_email DROP NOT NULL", "nn")
    for stmt in statements[:2]:
        assert "ERROR" not in psql(pg, stmt, "nn")
    scan_free = psql(pg, debug + statements[2], "nn")
    assert "are sufficient to prove that it does not contain nulls" in scan_free and "verifying table" not in scan_free, scan_free
    assert "ERROR" not in psql(pg, statements[3], "nn")
    assert psql(pg, "SELECT attnotnull FROM pg_attribute WHERE attrelid = 'orders'::regclass AND attname = 'buyer_email'", "nn") == "t"


@needs_docker
def test_db06_pgbouncer_branch_connects_and_the_timeout_comes_from_alter_role(proj: Path):
    """PgBouncer 1.26 en modo transaction: 30 clientes concurrentes con la rama de `DB_PGBOUNCER`."""
    tag = f"wave3_{os.getpid()}"
    net = f"{tag}_net"
    docker = lambda *a: subprocess.run(["docker", *a], capture_output=True, text=True)  # noqa: E731
    docker("network", "create", net)
    try:
        assert docker("run", "-d", "--rm", "--name", f"{tag}_pg", "--network", net, "-e", "POSTGRES_PASSWORD=x", "-e", "POSTGRES_DB=mig", IMAGE).returncode == 0
        assert docker("run", "-d", "--rm", "--name", f"{tag}_pgb", "--network", net, "-p", "127.0.0.1::6432", "-e", f"DB_HOST={tag}_pg",
                      "-e", "DB_USER=postgres", "-e", "DB_PASSWORD=x", "-e", "DB_NAME=mig", "-e", "POOL_MODE=transaction",
                      "-e", "AUTH_TYPE=scram-sha-256", "-e", "LISTEN_PORT=6432", "edoburu/pgbouncer:latest").returncode == 0
        for _ in range(60):
            if docker("exec", f"{tag}_pg", "psql", "-U", "postgres", "-d", "mig", "-c", "SELECT 1").returncode == 0:
                break
            time.sleep(1)
        assert docker("exec", f"{tag}_pg", "psql", "-U", "postgres", "-d", "mig", "-c", "ALTER ROLE postgres SET statement_timeout = '7s'").returncode == 0
        port = docker("port", f"{tag}_pgb", "6432/tcp").stdout.split(":")[-1].strip()
        script = """
import asyncio
from sqlalchemy import text
import app.database as d
from app.config import Settings

async def main() -> None:
    engine = d.build_engine(Settings(_env_file=None))

    async def one() -> str:
        async with engine.connect() as conn:
            return str((await conn.execute(text("SHOW statement_timeout"))).scalar())

    print("RESULT", sorted(set(await asyncio.gather(*[one() for _ in range(30)]))))

asyncio.run(main())
"""
        time.sleep(2)
        out = ok([sys.executable, "-c", script], proj, PYTHONPATH=str(proj), DB_PGBOUNCER="true", DB_HOST="127.0.0.1", DB_PORT=port)
        assert "RESULT ['7s']" in out
    finally:
        docker("rm", "-f", f"{tag}_pgb", f"{tag}_pg")
        docker("network", "rm", net)
