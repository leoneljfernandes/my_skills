"""Ola 4 (testing): contratos que se comprueban leyendo las skills, sin levantar nada.

TS-03 (unit sin mocks de repositorios), TS-04/TS-05 (texto de la sesión por request), TS-15 (matriz
y checklist), APP_ENV por asignación directa y la línea de pytest-asyncio en unit.

Uso: uv run --with pytest pytest tests/snippets/test_wave4_contracts.py -v
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import SKILLS, block  # noqa: E402

ENDPOINTS = "testing-fastapi-endpoints"
UNIT = "unit-testing-fastapi-services"


def text(rel: str) -> str:
    return (SKILLS / rel).read_text(encoding="utf-8")


def frontmatter_description(md: str) -> str:
    return re.search(r"^description: (.*)$", md, re.MULTILINE).group(1)  # type: ignore[union-attr]


def test_unit_skill_does_not_mock_repositories() -> None:
    md = text(f"testing/{UNIT}/SKILL.md")
    # Fuera de las menciones prohibitivas (checklist y anti-patrón), ningún bloque los mockea.
    for _, code in re.findall(r"```(\w*)\n(.*?)```", md, re.DOTALL):
        assert not re.search(r"create_autospec\(.*Repository", code), code
        assert "AsyncMock(spec=AsyncSession)" not in code
    assert "mocking repositories" not in frontmatter_description(md)
    assert "AsyncMock(spec=PaymentGateway)" not in md.split("## Checklist")[0].split("## Ejemplos")[1]


def test_unit_skill_names_pytest_asyncio_and_uses_autospec_for_the_gateway() -> None:
    md = text(f"testing/{UNIT}/SKILL.md")
    assert "pytest-asyncio" in md and 'asyncio_mode = "auto"' in md
    assert "mocker.create_autospec(PaymentGateway, instance=True)" in md
    assert "pytest.raises(TypeError)" in md
    assert 'mocker.patch.object(db_session, "commit", side_effect=' in md


def test_layering_says_external_collaborators() -> None:
    md = text("backend/layering-fastapi-apps/SKILL.md")
    assert "los tests reemplazan colaboradores externos sin `patch` de módulos" in md


def test_endpoints_conftest_uses_a_session_per_request_on_a_shared_connection() -> None:
    conftest = block(ENDPOINTS, "def _sqlite_memory_engine")
    assert "async def db_conn" in conftest and "def _override_get_db" in conftest
    assert "yield db_session" not in conftest  # la app no comparte la sesión del test
    assert "client_no_raise" in conftest and "raise_app_exceptions=False" in conftest
    assert "postgres:16.15-alpine" in conftest


def test_endpoints_conftest_assigns_app_env_directly() -> None:
    conftest = block(ENDPOINTS, "def _sqlite_memory_engine")
    assert 'os.environ["APP_ENV"] = "test"' in conftest
    assert 'setdefault("APP_ENV"' not in conftest
    assert 'os.environ.setdefault("SECRET_KEY"' in conftest  # el resto sí puede venir del entorno de CI


def test_endpoints_tests_cover_contract_409_and_500() -> None:
    tests = block(ENDPOINTS, "test_place_order_decrements_stock")
    assert "test_flush_without_commit_does_not_persist" in tests
    assert "assert count == 1" in tests  # el 409 conserva el original
    assert 'assert response.json()["code"] == "internal_error"' in tests
    assert 'assert "hunter2" not in response.text' in tests


def test_checklist_matches_the_matrix() -> None:
    md = text(f"testing/{ENDPOINTS}/SKILL.md")
    matrix = re.search(r"cubrir la matriz: (.*?)\.\n", md).group(1)  # type: ignore[union-attr]
    checklist = re.search(r"- \[ \] Cada recurso cubre la matriz de las reglas \((.*?)\)", md).group(1)  # type: ignore[union-attr]
    for item in ("happy path", "422", "regla de negocio", "401", "403", "404", "409", "500"):
        assert item in matrix and item in checklist, item


def test_polyfactory_block_is_complete() -> None:
    code = block(ENDPOINTS, "class ProductFactory")
    for needle in ("created_at = Ignore()", "updated_at = Ignore()", "__set_primary_key__ = False",
                   "SQLAlchemyPersistenceMethod.FLUSH", "__async_session__ = db_session", "stock = Use(", "price = Use("):
        assert needle in code, needle
