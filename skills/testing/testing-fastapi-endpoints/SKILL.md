---
name: testing-fastapi-endpoints
description: Use when writing or fixing integration/E2E tests for FastAPI endpoints with a database - conftest.py fixtures, TestClient or httpx AsyncClient, SQLite in-memory vs testcontainers PostgreSQL, per-test isolation with automatic rollback, dependency_overrides for get_db, test data helpers - or when tests leak data between each other, depend on execution order, need a running Postgres, or fail with "no such table", event loop or "attached to a different loop" errors.
domain: testing
tags: [python, pytest, fastapi, integration-testing, sqlalchemy, testcontainers, pytest-asyncio, test-data]
triggers: [pytest, conftest, fixture, TestClient, AsyncClient, ASGITransport, dependency_overrides, "sqlite:///:memory:", aiosqlite, testcontainers, rollback, "datos de prueba", polyfactory, "tests de integración", "tests E2E", "event loop is closed", "different loop"]
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
- **Datos de prueba**: helpers async en `tests/factories.py` (`create_product(session, **overrides)`). Construyen la fila con los mínimos obligatorios, hacen `flush` (obtienen id sin commitear) y devuelven la entidad. El test fija solo los campos que le importan. Los datos que la migración siembra (roles, configuración por defecto) también se siembran acá, porque `create_all` no ejecuta migraciones.
- Si un modelo tiene más de 10 columnas obligatorias cuyo valor no importa al test, generar esos valores con `polyfactory` (`SQLAlchemyFactory` con `__persistence_method__ = FLUSH`). Si no, helpers: sin dependencias, sin magia de campos.
- **pytest-asyncio** con `asyncio_mode = "auto"` y loop scope de sesión para fixtures y tests: el engine de sesión y los tests comparten loop.
- Por recurso, cubrir la matriz: happy path, 422 de validación (parametrizado), regla de negocio, 401, 403, 404, 409, y un 500 forzado.
- Variables de entorno de test fijadas en el `conftest.py` **antes** de importar la app: `APP_ENV=test` no lee ningún `.env`, así que van también las obligatorias (`SECRET_KEY`, `DB_*`, `ERRORS_BASE_URL`) y `COOKIE_SECURE=false` (el cliente de test habla http y no reenvía cookies `Secure`).
- La imagen de PostgreSQL del test es **la misma versión** que usa producción y `docker-compose`. Si el contenedor no arranca porque testcontainers no inicia Ryuk, apagarlo con `TESTCONTAINERS_RYUK_DISABLED=true`: el `with` del fixture ya detiene y borra el contenedor.
- Un invariante que depende de concurrencia real (dos requests que se disputan un lock) no se prueba con el rollback por test: ver la receta de concurrencia más abajo.

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

`tests/conftest.py` (verificado: la misma suite pasa en SQLite y en PostgreSQL 16 vía testcontainers):

```python
import os

# Antes de importar la app: Settings valida al importarse app.main.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-32b+")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_HOST", "test-db.invalid")  # no se usa: SQLite o testcontainers
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("ERRORS_BASE_URL", "https://errors.test.invalid")
os.environ.setdefault("COOKIE_SECURE", "false")

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

    with PostgresContainer("postgres:16-alpine", driver="asyncpg")  # = la versión de producción as pg:
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
from itertools import count

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product

_sku = count(1)


async def create_product(session: AsyncSession, **overrides: object) -> Product:
    """Producto válido con los mínimos obligatorios; el test pisa solo lo que le importa."""
    fields: dict[str, object] = {
        "sku": f"SKU-{next(_sku):04d}",
        "name": "Test product",
        "price": Decimal("19.99"),
        "stock": 10,
        "is_active": True,
    } | overrides
    product = Product(**fields)
    session.add(product)
    await session.flush()  # obtiene el id sin commitear: el test sigue dentro de su transacción
    return product
```

Tests:

```python
async def test_place_order_decrements_stock(client: AsyncClient, db_session: AsyncSession) -> None:
    product = await create_product(db_session, stock=5, price=Decimal("12.50"))

    response = await client.post(
        "/api/v1/orders",
        json={"customer_email": "ana@example.com", "product_id": product.id, "quantity": 2},
    )

    assert response.status_code == 201, response.text
    assert Decimal(response.json()["total"]) == Decimal("25.00")
    await db_session.refresh(product)
    assert product.stock == 3


async def test_duplicate_sku_is_409_problem_json(client: AsyncClient, db_session: AsyncSession) -> None:
    product = await create_product(db_session)
    payload = {"sku": product.sku, "name": "Other", "price": "5.00", "stock": 1}

    response = await client.post("/api/v1/products", json=payload)

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "conflict"


async def test_isolation_part_1_creates_data(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_product(db_session, sku="SKU-ISOLATION")
    assert (await client.get("/api/v1/products")).json()["items"]


async def test_isolation_part_2_sees_clean_database(client: AsyncClient) -> None:
    # Si el rollback por test fallara, vería el producto del test anterior.
    assert (await client.get("/api/v1/products")).json()["items"] == []
```

Receta de concurrencia (aparte del rollback por test): el test usa el `engine` directamente, cada tarea abre **su propia sesión** y commitea de verdad, y la limpieza es manual. Corre solo con PostgreSQL, porque SQLite no tiene `FOR UPDATE`.

```python
pytestmark = pytest.mark.skipif(os.getenv("TEST_DB") != "postgres", reason="requiere PostgreSQL")


async def test_two_orders_for_last_unit_one_wins(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        product = await create_product(s, stock=1)
        await s.commit()

    async def place() -> bool:
        async with factory() as s:
            try:
                await OrderService(s, ProductRepository(s), OrderRepository(s)).place_order(
                    OrderCreate(customer_email="a@example.com", product_id=product.id, quantity=1)
                )
            except InsufficientStockError:
                return False
            return True

    try:
        results = await asyncio.gather(place(), place())
        assert sorted(results) == [False, True]  # sin FOR UPDATE, ambos ganarían
    finally:  # commits reales: nada los deshace
        async with factory() as s:
            await s.execute(delete(Order))
            await s.execute(delete(Product))
            await s.commit()
```

Comandos:

```bash
uv run pytest -q                                  # SQLite en memoria, sin Docker
TEST_DB=postgres uv run pytest -q                 # PostgreSQL real (requiere Docker)
uv run coverage run --source=app -m pytest && uv run coverage report -m
```

## Checklist de verificación

- [ ] `uv run pytest` pasa sin Postgres ni Docker y no deja archivos `.db`.
- [ ] La imagen de PostgreSQL del test tiene la misma versión que `docker-compose` y producción.
- [ ] `TEST_DB=postgres uv run pytest` pasa con Docker (en CI, al menos en un job).
- [ ] El par de tests de aislamiento pasa en ambos órdenes (`pytest -p no:randomly` y con `pytest-randomly`).
- [ ] Ningún test usa ids hardcodeados ni datos creados por otro test.
- [ ] Cada endpoint tiene happy path + 422 + casos de negocio + 404/403 según aplique.
- [ ] `app.dependency_overrides` se limpia en el teardown de cada fixture que lo modifica.
- [ ] Los helpers de datos hacen `flush`, no `commit`: el test no deja nada fuera de su transacción.
- [ ] Si hay tests de concurrencia, `TEST_DB=postgres uv run pytest` corre sus casos sin saltarlos (un `skipif` oculta los que nadie ejecuta).

## Skills relacionadas

- `unit-testing-fastapi-services`: lógica de negocio con mocks, sin base.
- `configuring-sqlalchemy-sessions`: el `get_db` que se sobreescribe.
- `migrating-with-alembic`: tests del esquema real (round-trip).
