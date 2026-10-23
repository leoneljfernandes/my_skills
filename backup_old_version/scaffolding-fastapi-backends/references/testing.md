# Tests E2E con pytest y base de datos en memoria

## Enfoque

- **E2E a través de HTTP**: cada test usa `TestClient` contra la app real (routers + dependencias + servicios + ORM). Solo se reemplaza la base.
- **Base en memoria**: SQLite `:memory:` con `aiosqlite`. Los tests corren sin Postgres, sin Docker y sin dejar archivos.
- **Clean-Execute-Clean**: el esquema se recrea antes de cada test y se borra al final. Cada test arranca de una base prístina, así el orden no importa.
- Tracing apagado en tests: `setup_telemetry` no hace nada sin `OTEL_EXPORTER_OTLP_ENDPOINT` (ver observability.md).

Por qué SQLite y no Postgres en tests: velocidad y cero infraestructura. El esquema de los tests sale de `Base.metadata.create_all`; la validez de las **migraciones** contra Postgres real se prueba aparte en CI (job `migrations` de ci.md).

## `pytest.ini`

```ini
[pytest]
pythonpath = .
testpaths = tests
```

## `tests/conftest.py`

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base  # importar el paquete registra todos los modelos

# StaticPool: todas las sesiones comparten LA MISMA conexión.
# Sin él, cada conexión a ":memory:" abre una base nueva y vacía.
engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


async def _reset_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def _drop_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c.portal.call(_reset_schema)   # Clean + Setup, en el event loop del TestClient
        yield c
        c.portal.call(_drop_schema)    # Clean
    app.dependency_overrides.clear()
```

Puntos clave:

- El esquema se crea con `c.portal.call(...)`: corre en el mismo event loop que usa la app, así la conexión de `aiosqlite` no queda atada a otro loop. No hace falta `pytest-asyncio`.
- `TestClient(app)` con `raise_server_exceptions=True` (default): un 500 inesperado muestra el traceback real en el test.
- Importar con `from app.models import Base`; un `import app.models.x` reasigna el nombre `app` y rompe `app.dependency_overrides`.
- La app no debe conectarse a Postgres al importar ni en el `lifespan` (el engine de SQLAlchemy es lazy; no hay `create_all` en el `lifespan`).
- `SECRET_KEY` de 32+ caracteres en el entorno de tests (CI la define; localmente la toma de `.env`).

## Fixtures de dominio

Por archivo de test o en `conftest.py` si se comparten:

```python
@pytest.fixture
def auth_user(client):
    payload = {"email": "user@example.com", "name": "Test User", "password": "Password123"}
    user = client.post("/api/users/", json=payload).json()
    token = client.post(
        "/api/users/token", data={"username": payload["email"], "password": payload["password"]}
    ).json()["access_token"]   # OAuth2 → form-data (data=), no json=
    return {"id": user["id"], **payload, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def other_user(client):
    ...  # segundo usuario para probar 403 sobre recursos ajenos
```

El id se lee de la respuesta, no se asume `1`.

## Qué cubrir por recurso

| Caso | Status esperado |
|---|---|
| Happy path de cada endpoint | 200 / 201 / 204 |
| Payload inválido (parametrizado por campo) | 422 |
| Regla de negocio violada (p. ej. SMS > 160 caracteres, teléfono inválido) | 400 / 422 vía exception handler |
| Sin token / token inválido | 401 |
| Recurso de otro usuario | 403 |
| Recurso inexistente | 404 |
| Duplicado (email registrado) | 400 / 409 |
| Una variante por estrategia (email, sms, push) | según regla |

Validaciones con `@pytest.mark.parametrize`:

```python
@pytest.mark.parametrize("bad_payload, error_type, field", [
    ({"email": "no-es-email", "name": "Ok", "password": "Password123"}, "value_error", "email"),
    ({"email": "a@b.com", "name": "Ok", "password": "corta"}, "string_too_short", "password"),
])
def test_register_invalid(client, bad_payload, error_type, field):
    r = client.post("/api/users/", json=bad_payload)
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == error_type
    assert field in r.json()["detail"][0]["loc"]
```

## Comandos

```bash
uv run pytest -v                                    # suite completa
uv run pytest tests/test_notifications.py -v        # un archivo
uv run coverage run --source=app -m pytest && uv run coverage report -m   # cobertura local
```

Scripts de prueba sueltos van en `tests/` o en un scratchpad, nunca en la raíz del repo.
