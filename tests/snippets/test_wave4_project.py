"""Ola 4 (testing): rojo antes, verde después, sobre el proyecto de referencia.

Cada caso copia las skills a un directorio temporal, les aplica una mutación (la regresión que la
skill debe detectar), arma el proyecto de referencia desde esa copia (`SKILLS_DIR`) y corre sus
tests con el entorno de `reference/` (`uv sync` hecho por `reference/run.sh`; sin `uv` se saltea).

TS-04/TS-05: `commit` -> `flush` en place_order y la sesión compartida tienen que dar rojo.
TS-06: polyfactory sin `Ignore()` en created_at rompe con UtcDateTime.
TS-11: `AsyncMock(spec=)` acepta una firma incorrecta; autospec no.

Uso: uv run --with pytest --with pyyaml pytest tests/snippets/test_wave4_project.py -v
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from extract import SKILLS  # noqa: E402

HERE = Path(__file__).parent
REF = HERE / "reference"
pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="requiere uv")

ENDPOINTS = "testing/testing-fastapi-endpoints/SKILL.md"
UNIT = "testing/unit-testing-fastapi-services/SKILL.md"
LAYERING = "backend/layering-fastapi-apps/SKILL.md"

# (archivo, texto actual, texto mutado)
SHARED_SESSION = (
    ENDPOINTS,
    "def _override_get_db(db_conn: AsyncConnection) -> Iterator[None]:\n"
    "    async def _get_db() -> AsyncIterator[AsyncSession]:\n"
    "        async with _session_on(db_conn) as session:  # como get_db: al cerrar se descarta lo no commiteado\n"
    "            yield session\n",
    "def _override_get_db(db_session: AsyncSession) -> Iterator[None]:\n"
    "    async def _get_db() -> AsyncIterator[AsyncSession]:\n"
    "        yield db_session\n",
)


def run_project(
    tmp_path: Path, mutations: list[tuple[str, str, str]], select: list[str], test_db: str = ""
) -> subprocess.CompletedProcess[str]:
    skills = tmp_path / "skills"
    shutil.copytree(SKILLS, skills)
    for rel, old, new in mutations:
        path = skills / rel
        text = path.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"la mutación no aplica (cambió el texto): {old[:60]!r}"
        path.write_text(text.replace(old, new), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}}
    env.update(SKILLS_DIR=str(skills), PYTHONDONTWRITEBYTECODE="1", TEST_DB=test_db, TESTCONTAINERS_RYUK_DISABLED="true")
    project = tmp_path / "project"
    shutil.copy(REF / "pyproject.toml", tmp_path / "pyproject.toml")  # build_ref ve que declara polyfactory
    built = subprocess.run([sys.executable, str(REF / "build_ref.py"), str(project)], env=env, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return subprocess.run(
        ["uv", "run", "--project", str(REF), "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly",
         "-c", str(REF / "pyproject.toml"), "--rootdir", str(project), "-o", f"pythonpath={REF} {project}",
         "-o", "testpaths=tests", *[str(project / s) for s in select]],
        env=env, capture_output=True, text=True, timeout=600,
    )


ENDPOINT_TESTS = ["tests/test_endpoints.py", "tests/unit/test_order_service.py", "tests/test_product_factory.py"]


def test_published_blocks_pass(tmp_path: Path) -> None:
    done = run_project(tmp_path, [], ENDPOINT_TESTS)
    assert done.returncode == 0, done.stdout + done.stderr


def test_commit_replaced_by_flush_in_place_order_turns_red(tmp_path: Path) -> None:
    """TS-04: con la sesión compartida esto pasaba en verde (4 passed)."""
    mutation = (LAYERING, "await self._session.commit()  # un solo commit por caso de uso",
                "await self._session.flush()  # MUTACION")
    done = run_project(tmp_path, [mutation], ENDPOINT_TESTS)
    out = done.stdout + done.stderr
    assert done.returncode != 0
    assert "test_endpoints.py::test_place_order_decrements_stock" in out
    assert "test_order_service.py::test_place_order_decrements_stock_and_commits" in out


def test_shared_session_loses_the_factory_row_after_a_409(tmp_path: Path) -> None:
    """TS-05: con una sola sesión, el rollback del service borra lo que creó la factory."""
    done = run_project(tmp_path, [SHARED_SESSION], ["tests/test_endpoints.py"])
    assert done.returncode != 0
    assert "test_duplicate_sku_is_409_problem_json" in done.stdout


def test_shared_session_hides_the_missing_commit(tmp_path: Path) -> None:
    """TS-04, el estado anterior: con la sesión compartida, `flush` por `commit` pasa en verde."""
    mutation = (LAYERING, "await self._session.commit()  # un solo commit por caso de uso",
                "await self._session.flush()  # MUTACION")
    done = run_project(tmp_path, [SHARED_SESSION, mutation], ["tests/test_endpoints.py::test_place_order_decrements_stock"])
    assert done.returncode == 0, done.stdout


def test_polyfactory_without_ignore_of_timestamps_breaks(tmp_path: Path) -> None:
    """TS-06: sin Ignore(), polyfactory rellena created_at con fechas naive y UtcDateTime las rechaza."""
    mutation = (ENDPOINTS, "    created_at = Ignore()  # UtcDateTime rechaza las fechas sin zona que genera polyfactory\n", "")
    done = run_project(tmp_path, [mutation], ["tests/test_product_factory.py"])
    assert done.returncode != 0
    assert "naive datetime" in done.stdout


def test_asyncmock_spec_accepts_a_wrong_signature_but_autospec_does_not(tmp_path: Path) -> None:
    """TS-11."""
    mutation = (UNIT, "return mocker.create_autospec(PaymentGateway, instance=True)",
                "return mocker.AsyncMock(spec=PaymentGateway)")
    done = run_project(tmp_path, [mutation], ["tests/unit/test_order_service.py"])
    assert done.returncode != 0
    assert "test_autospec_rejects_a_wrong_signature" in done.stdout


@pytest.mark.skipif(shutil.which("docker") is None, reason="requiere docker")
def test_published_blocks_pass_on_postgres(tmp_path: Path) -> None:
    """TS-06: las 30 instancias de polyfactory (con CHECK y UNIQUE) y el resto, en PostgreSQL 16."""
    done = run_project(tmp_path, [], ENDPOINT_TESTS, test_db="postgres")
    assert done.returncode == 0, done.stdout + done.stderr
