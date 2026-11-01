"""Ola 2 (contratos del backend), sobre el proyecto de referencia armado desde las skills.

BE-03/OB-11 (flags), BE-07/OB-10 (lifespan y salud), BE-14 (docs), BE-18/TS-08 (create_app sin
parámetros), BE-26 (grep de capas) y DB-10 (app.models registra todo).
"""

import inspect
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

import app as app_pkg
import app.main as app_main
from app.api.deps import get_health_repository
from app.config import get_settings
from app.main import app, create_app


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """monkeypatch + cache_clear: la forma que documenta configuring-fastapi-settings."""
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


async def fetch(application, path: str):  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as ac:
        return await ac.get(path)


async def test_health_live_needs_no_database() -> None:
    response = await fetch(app, "/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_is_outside_the_api_prefix(client: AsyncClient) -> None:
    assert (await client.get("/health/ready")).status_code == 200  # SELECT 1 a través de HealthRepository
    assert (await client.get("/api/v1/health/live")).status_code == 404


async def test_ready_is_500_when_the_database_is_down(client: AsyncClient) -> None:
    class Down:
        async def ping(self) -> None:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    app.dependency_overrides[get_health_repository] = lambda: Down()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health/ready")
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"


async def test_lifespan_disposes_the_engine_then_shuts_tracing_down(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    fake_engine = SimpleNamespace(dispose=AsyncMock(side_effect=lambda: calls.append("dispose")))
    monkeypatch.setattr(app_main, "engine", fake_engine)
    monkeypatch.setattr(app_main, "shutdown_tracing", lambda: calls.append("shutdown_tracing"))
    async with app.router.lifespan_context(app):
        assert calls == []  # nada se cierra mientras la app corre
    assert calls == ["dispose", "shutdown_tracing"]  # el flush de spans va al final


def test_create_app_takes_no_settings() -> None:
    assert not inspect.signature(create_app).parameters


async def test_create_app_follows_environment_plus_cache_clear(env: pytest.MonkeyPatch) -> None:
    env.setenv("ERRORS_BASE_URL", "https://errors.other.invalid")
    get_settings.cache_clear()
    response = await fetch(create_app(), "/no-such-route")
    assert response.json()["type"] == "https://errors.other.invalid/http_404"


async def test_docs_and_openapi_are_off_by_default_and_on_with_the_flag(env: pytest.MonkeyPatch) -> None:
    off = create_app()
    assert (await fetch(off, "/docs")).status_code == 404
    assert (await fetch(off, "/openapi.json")).status_code == 404  # D7: el esquema tampoco queda público
    env.setenv("DOCS_ENABLED", "true")
    get_settings.cache_clear()
    on = create_app()
    assert (await fetch(on, "/docs")).status_code == 200
    assert (await fetch(on, "/openapi.json")).status_code == 200


async def test_metrics_endpoint_only_with_the_flag(env: pytest.MonkeyPatch) -> None:
    assert (await fetch(create_app(), "/metrics")).status_code == 404
    env.setenv("METRICS_ENABLED", "true")
    get_settings.cache_clear()
    response = await fetch(create_app(), "/metrics")
    assert response.status_code == 200
    assert "shop_orders_created_total" in response.text


def test_sql_lives_only_in_crud() -> None:
    """El grep del checklist de layering: nada de select( ni .execute( en api/ ni services/."""
    root = Path(inspect.getfile(app_pkg)).parent
    hits = [
        f"{path.relative_to(root)}:{n}"
        for folder in ("api", "services")
        for path in (root / folder).rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if "select(" in line or ".execute(" in line
    ]
    assert not hits, hits


def test_models_package_registers_every_table() -> None:
    from app.models import Base, UtcDateTime  # noqa: F401  (env.py importa exactamente esto)

    assert {"products", "orders", "users", "roles", "sessions"} <= set(Base.metadata.tables)
