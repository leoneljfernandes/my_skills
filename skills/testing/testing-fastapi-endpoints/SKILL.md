---
name: testing-fastapi-endpoints
description: Use when writing or fixing integration/E2E tests for FastAPI endpoints with a database - conftest.py fixtures, TestClient or httpx AsyncClient, SQLite in-memory vs testcontainers PostgreSQL, per-test isolation with automatic rollback, dependency_overrides for get_db, fake data factories (polyfactory/Faker) - or when tests leak data between each other, depend on execution order, need a running Postgres, or fail with "no such table", event loop or "attached to a different loop" errors.
domain: testing
tags: [python, pytest, fastapi, integration-testing, sqlalchemy, testcontainers, pytest-asyncio, polyfactory]
triggers: [pytest, conftest, fixture, TestClient, AsyncClient, ASGITransport, dependency_overrides, "sqlite:///:memory:", aiosqlite, testcontainers, rollback, polyfactory, Faker, "tests de integración", "tests E2E", "event loop is closed", "different loop"]
---

# Tests de integración de endpoints FastAPI

Cada test atraviesa la app real por HTTP (router → service → repositorio → ORM → base) y deja la base **exactamente** como la encontró, mediante una transacción externa que se revierte al final. Sin borrar tablas, sin depender del orden.

## Contexto y reglas

**Hacer**

- **Cliente**: `httpx.AsyncClient(transport=ASGITransport(app=app))` para apps async: misma event loop que la sesión de base. `TestClient` solo para apps/tests síncronos (Starlette ya lo marca para migrar de `httpx` a `httpx2`).
- **Base de datos, dos modos con el mismo conftest**:
  - Default: SQLite `:memory:` (`aiosqlite` + `StaticPool`): corre en milisegundos, sin Docker.
  - `TEST_DB=postgres`: PostgreSQL real con **testcontainers**, para CI y para lo que SQLite no tiene (`FOR UPDATE`, índices parciales, JSONB, CHECK reales, tipos).
- **Esquema**: `Base.metadata.create_all` **una vez por sesión de pytest**. Las migraciones se prueban aparte (round-trip de `migrating-with-alembic`).
- **Aislamiento por test**: conexión → `BEGIN` externo → `AsyncSession(bind=conn, join_transaction_mode="create_savepoint")`. El `commit()` del código bajo prueba solo libera un SAVEPOINT, y el `rollback` externo al final borra todo.
- En SQLite, desactivar el manejo de transacciones del driver (`isolation_level = None` + `BEGIN` explícito). Sin eso, los SAVEPOINT no funcionan y el rollback por test falla.
- **`dependency_overrides[get_db]`** devuelve la sesión del test: el test y la app ven los mismos datos sin commitear.
- **Datos ficticios**: `polyfactory` (`SQLAlchemyFactory` para filas, `ModelFactory` para payloads Pydantic) con Faker. Persistencia en modo **flush** (obtiene id sin commitear). El test fija solo los campos que le importan.
- **pytest-asyncio** con `asyncio_mode = "auto"` y loop scope de sesión para fixtures y tests: el engine de sesión y los tests comparten loop.
- Por recurso, cubrir la matriz: happy path, 422 de validación (parametrizado), regla de negocio, 401, 403, 404, 409, y un 500 forzado.
- Variables de entorno de test (`APP_ENV=test`, `SECRET_KEY`) fijadas en el `conftest.py` **antes** de importar la app.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `drop_all`/`create_all` por test | suite lenta (O(tablas × tests)) | create_all por sesión + rollback por test |
| Tests contra la base de desarrollo | borran datos reales; no reproducibles | SQLite memoria o contenedor efímero |
| `:memory:` sin `StaticPool` | cada conexión ve una base vacía → `no such table` | `poolclass=StaticPool` |
| Asumir ids (`/products/1`) | se rompe con cualquier cambio de orden o secuencia | leer el id de la fixture/respuesta |
| Test que depende de datos de otro test | falla al correr aislado o en paralelo | cada test crea lo suyo con factories |
| Mockear la base en tests de endpoints | prueba el mock, no las queries reales | base real (memoria/contenedor); mocks solo en unit tests |
| `time.sleep` para esperar efectos | lento y flaky | estado determinista, o esperas por condición |
| Fixtures `async` con loop scope distinto al engine | `attached to a different loop` | `asyncio_default_fixture_loop_scope = "session"` |

## Ejemplos

`pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
filterwarnings = ["error::sqlalchemy.exc.SAWarning"]
```

`tests/conftest.py` (verificado: la misma suite pasa en SQLite y en PostgreSQL 17 vía testcontainers):

```python
import os

# Antes de importar la app: Settings valida al importarse app.main.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-32b+")

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base
from tests.factories import OrderFactory, ProductFactory


def _sqlite_memory_engine() -> AsyncEngine:
    # StaticPool: una sola conexión compartida (cada conexión nueva a :memory: es otra base vacía).
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    # El driver sqlite maneja BEGIN por su cuenta y rompe los SAVEPOINT.
    # Se le quita ese control para que el rollback por test funcione.
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        dbapi_conn.isolation_level = None
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")  # SQLite no valida FKs por defecto
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _on_begin(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN")

    return engine


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    # TEST_DB=postgres → Postgres real en contenedor (CI); default → SQLite en memoria (rápido).
    if os.getenv("TEST_DB") == "postgres":
        eng = create_async_engine(request.getfixturevalue("postgres_url"))
    else:
        eng = _sqlite_memory_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # en tests sí; en la app, Alembic
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Sesión aislada: todo lo que el test (y la app) commitea se deshace al final."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",  # commit() del código = RELEASE SAVEPOINT
        )
        ProductFactory.__async_session__ = session
        OrderFactory.__async_session__ = session
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
```

`tests/factories.py`:

```python
from decimal import Decimal

from faker import Faker
from polyfactory import Use
from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory, SQLAlchemyPersistenceMethod

from app.models import Order, OrderStatus, Product
from app.schemas.product import ProductCreate

fake = Faker()


class ProductFactory(SQLAlchemyFactory[Product]):
    __set_primary_key__ = False      # lo asigna la base
    __set_relationships__ = False
    # flush: obtiene el id sin commitear; el test sigue dentro de su transacción.
    __persistence_method__ = SQLAlchemyPersistenceMethod.FLUSH

    sku = Use(lambda: fake.unique.bothify("SKU-####-???").upper())
    name = Use(fake.catch_phrase)
    price = Use(lambda: Decimal(fake.pydecimal(left_digits=3, right_digits=2, positive=True)))
    stock = 10
    is_active = True
    created_at = None  # server_default
    updated_at = None


class ProductCreatePayload(ModelFactory[ProductCreate]):
    sku = Use(lambda: fake.unique.bothify("SKU-####-???").upper())
    price = Use(lambda: Decimal("19.99"))
    stock = 5
```

Tests:

```python
async def test_place_order_decrements_stock(client: AsyncClient, db_session: AsyncSession) -> None:
    product = await ProductFactory.create_async(stock=5, price=Decimal("12.50"))

    response = await client.post(
        "/api/v1/orders",
        json={"customer_email": "ana@example.com", "product_id": product.id, "quantity": 2},
    )

    assert response.status_code == 201, response.text
    assert Decimal(response.json()["total"]) == Decimal("25.00")
    await db_session.refresh(product)
    assert product.stock == 3


async def test_duplicate_sku_is_409_problem_json(client: AsyncClient) -> None:
    product = await ProductFactory.create_async()
    payload = ProductCreatePayload.build(sku=product.sku).model_dump(mode="json")

    response = await client.post("/api/v1/products", json=payload)

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "conflict"


async def test_isolation_part_1_creates_data(client: AsyncClient) -> None:
    await ProductFactory.create_async(sku="SKU-ISOLATION")
    assert (await client.get("/api/v1/products")).json()["items"]


async def test_isolation_part_2_sees_clean_database(client: AsyncClient) -> None:
    # Si el rollback por test fallara, vería el producto del test anterior.
    assert (await client.get("/api/v1/products")).json()["items"] == []
```

Comandos:

```bash
uv run pytest -q                                  # SQLite en memoria, sin Docker
TEST_DB=postgres uv run pytest -q                 # PostgreSQL real (requiere Docker)
uv run coverage run --source=app -m pytest && uv run coverage report -m
```

## Checklist de verificación

- [ ] `uv run pytest` pasa sin Postgres ni Docker y no deja archivos `.db`.
- [ ] `TEST_DB=postgres uv run pytest` pasa con Docker (en CI, al menos en un job).
- [ ] El par de tests de aislamiento pasa en ambos órdenes (`pytest -p no:randomly` y con `pytest-randomly`).
- [ ] Ningún test usa ids hardcodeados ni datos creados por otro test.
- [ ] Cada endpoint tiene happy path + 422 + casos de negocio + 404/403 según aplique.
- [ ] `app.dependency_overrides` se limpia en el teardown de cada fixture que lo modifica.
- [ ] Las factories usan `SQLAlchemyPersistenceMethod.FLUSH`. Con el default (`COMMIT`) también pasa, pero solo gracias al savepoint.

## Skills relacionadas

- `unit-testing-fastapi-services`: lógica de negocio con mocks, sin base.
- `configuring-sqlalchemy-sessions`: el `get_db` que se sobreescribe.
- `migrating-with-alembic`: tests del esquema real (round-trip).
