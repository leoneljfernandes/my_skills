---
name: configuring-sqlalchemy-sessions
description: Use when wiring SQLAlchemy 2.0 to PostgreSQL in a Python/FastAPI service - create_async_engine or create_engine, async_sessionmaker, asyncpg/psycopg, connection pool sizing, get_db dependency, PgBouncer - or on errors like MissingGreenlet, QueuePool limit reached / TimeoutError, "too many connections", stale connections after a database restart, or DetachedInstanceError.
domain: database
tags: [python, sqlalchemy, postgresql, asyncpg, connection-pool, fastapi]
triggers: [create_async_engine, async_sessionmaker, sessionmaker, asyncpg, psycopg, pool_size, max_overflow, "QueuePool limit", MissingGreenlet, "too many connections", PgBouncer, get_db, AsyncSession, expire_on_commit]
---

# Engine, pool y sesiones (SQLAlchemy 2.0 + PostgreSQL)

Un engine por proceso, una sesión por request (o por unidad de trabajo en workers). El pool se dimensiona contra `max_connections` del servidor, no por intuición.

## Contexto y reglas

**Hacer**

- **Async por defecto** (`asyncpg`) en APIs I/O-bound. **Sync** (`psycopg` 3) si el resto del stack es síncrono o hay librerías bloqueantes; en ese caso `DB_DRIVER=psycopg`, los endpoints se declaran `def` y FastAPI los corre en su threadpool. `layering-fastapi-apps` y `testing-fastapi-endpoints` muestran `AsyncSession`: en un proyecto sync se adaptan a `Session`.
- `engine` y `SessionFactory` a nivel de módulo (`app/database.py`), creados desde `Settings`. `await engine.dispose()` en el `lifespan` al apagar (el bloque está en `layering-fastapi-apps`).
- **Versión**: `sqlalchemy[asyncio]>=2.0.40,<2.1`. Con 2.1 la instrumentación de OpenTelemetry se desactiva y se pierden los spans SQL (ver `tracing-with-opentelemetry`).
- `async_sessionmaker(engine, expire_on_commit=False)`. Con `expire_on_commit=True` (el default), leer un atributo después del commit dispara I/O implícito, que en async rompe con `MissingGreenlet`.
- `get_db()` abre la sesión con `async with` y **no commitea**: el commit lo decide el service (ver `layering-fastapi-apps`). Al cerrar, lo no commiteado se descarta.
- `pool_pre_ping=True` (sobrevive a failovers y reinicios), `pool_recycle` < timeout de inactividad de firewalls/LB, `pool_timeout` corto (falla rápido en vez de colgar requests).
- `application_name` y `statement_timeout` en cada conexión: trazabilidad en `pg_stat_activity` y ninguna query eterna. El mecanismo depende del driver: con asyncpg, `connect_args={"server_settings": {...}}`; con psycopg, `connect_args={"application_name": ..., "options": "-c statement_timeout=15000"}` (`server_settings` no existe ahí). Detrás de PgBouncer `statement_timeout` no sirve por ninguno de los dos (rechaza el parámetro de arranque: `unsupported startup parameter`): se fija en el servidor, `ALTER ROLE app SET statement_timeout = '15s'`.
- **Dimensionar el pool**: `(pool_size + max_overflow) × procesos × réplicas ≤ max_connections − reservadas` (superuser, migraciones, monitoreo). Ejemplo: 4 workers × 3 réplicas × 20 = 240 → hace falta `max_connections ≥ 260` o PgBouncer.
- **PgBouncer en modo transaction** (`DB_PGBOUNCER=true`): el pooling lo hace PgBouncer, así que `build_engine` usa `poolclass=NullPool` (sin `pool_size` ni compañía, que `NullPool` no acepta), desactiva las prepared statements de asyncpg (`statement_cache_size=0`, `prepared_statement_cache_size=0`) y no pasa `server_settings`. Las migraciones **no** pasan por el pooler: `env.py` usa `MIGRATION_DATABASE_URL`, la conexión directa (`DB_MIGRATION_HOST`/`DB_MIGRATION_PORT`).
- Los endpoints de salud (`/health/live`, `/health/ready`) cuelgan de la raíz, fuera de `/api/v1` (ver `layering-fastapi-apps`): `ready` usa esta base, y las exclusiones de métricas y trazas (`/health/.*`) ya los cubren.
- Workers, CLIs y seeds abren su propia sesión con `async with SessionFactory() as session:`. Nunca reutilizar la sesión de una request.
- Relaciones con `lazy="raise"` y carga explícita en el repositorio (`selectinload` para colecciones, `joinedload` para muchos-a-uno) (ver `modeling-postgres-with-sqlalchemy`).

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `create_async_engine(...)` por request o por test de la app | conexiones nuevas cada vez, el pool no sirve | un engine por proceso |
| Sesión global compartida entre requests | estado cruzado entre usuarios, condiciones de carrera | sesión por request vía `Depends(get_db)` |
| Commit dentro de `get_db` después del `yield` | se ejecuta tras enviar la respuesta: el cliente ve 200 aunque el commit falle | commit explícito en el service |
| Acceder a `obj.relacion` sin cargarla (async) | `MissingGreenlet` | carga explícita en la query (`selectinload()`/`joinedload()`) |
| Leer un atributo no cargado de un objeto cuya sesión ya se cerró | `DetachedInstanceError` | `expire_on_commit=False` y cargar lo que se necesita antes de cerrar la sesión |
| `pool_size=100` "por si acaso" | agota `max_connections` con pocas réplicas | fórmula de arriba + métricas del pool |
| Endpoint `async def` que llama a un driver sync | bloquea el event loop entero | `def` + engine sync, o driver async |
| Mezclar `asyncio.gather` sobre la misma `AsyncSession` | una sesión no es concurrente: error o corrupción | una sesión por tarea concurrente |

## Ejemplos

`app/database.py` async (verificado (test) contra PostgreSQL 16 con pytest + testcontainers):

```python
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings


def build_engine(settings: Settings) -> AsyncEngine:
    if settings.DB_PGBOUNCER:
        # PgBouncer (modo transaction) ya hace el pooling: NullPool, sin prepared statements y sin
        # server_settings (PgBouncer los rechaza). El statement_timeout se fija en el servidor:
        # ALTER ROLE app SET statement_timeout = '15s'.
        return create_async_engine(
            settings.DATABASE_URL,
            poolclass=NullPool,
            echo=settings.DB_ECHO,
            connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
        )
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DB_POOL_SIZE,        # conexiones persistentes por proceso
        max_overflow=settings.DB_MAX_OVERFLOW,  # ráfagas por encima de pool_size
        pool_timeout=settings.DB_POOL_TIMEOUT,  # falla rápido si el pool está agotado
        pool_recycle=settings.DB_POOL_RECYCLE,  # recicla antes que firewalls/LB corten conexiones ociosas
        pool_pre_ping=True,                     # descarta conexiones muertas (failover, reinicio)
        echo=settings.DB_ECHO,
        connect_args={
            "server_settings": {
                "application_name": settings.APP_NAME,  # visible en pg_stat_activity
                "statement_timeout": str(settings.DB_STATEMENT_TIMEOUT_MS),
            },
        },
    )


engine = build_engine(get_settings())
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    # Sesión por request. Al cerrar, lo no commiteado se descarta (rollback implícito).
    async with SessionFactory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
```

Variante síncrona (`DB_DRIVER=psycopg`; verificada a mano (2026-11-01, `psycopg` 3 contra PostgreSQL 16.15: `SHOW statement_timeout` y `application_name`)). La URL, la contraseña y el timeout salen de `Settings`, igual que en la async:

```python
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.DATABASE_URL,
        # Cada endpoint `def` toma un hilo del threadpool de AnyIO (40) y una conexión:
        # DB_POOL_SIZE=40 y DB_MAX_OVERFLOW=0.
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
        echo=settings.DB_ECHO,
        connect_args={  # psycopg no tiene server_settings: son parámetros de conexión
            "application_name": settings.APP_NAME,
            "options": f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS}",
        },
    )


engine = build_engine(get_settings())
SessionFactory = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionFactory() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


class HealthRepository:  # versión sync del repositorio de `layering-fastapi-apps`: el SQL vive en crud/
    def __init__(self, session: Session) -> None:
        self._session = session

    def ping(self) -> None:
        self._session.execute(text("SELECT 1"))


router = APIRouter(prefix="/health", tags=["health"])  # el de app/api/health.py


@router.get("/ready")
def ready(db: DbSession) -> dict[str, str]:  # `def`, no `async def`: corre en el threadpool
    HealthRepository(db).ping()
    return {"status": "ok"}
```

Sesión fuera de una request (worker, CLI, seed):

```python
from typing import Any, cast

from sqlalchemy import func, text, update
from sqlalchemy.engine import CursorResult

from app.database import SessionFactory
from app.models import Order, OrderStatus


async def expire_pending_orders() -> int:
    async with SessionFactory() as session:
        # Un UPDATE devuelve un CursorResult, pero execute() lo declara como Result[Any], que no tiene rowcount.
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(Order)
                .where(Order.status == OrderStatus.PENDING, Order.created_at < func.now() - text("interval '1 day'"))
                .values(status=OrderStatus.CANCELLED)
            ),
        )
        await session.commit()
        return result.rowcount
```

## Checklist de verificación

- [ ] `grep -rn "create_async_engine\|create_engine" app/` aparece solo en `app/database.py` (y en `tests/conftest.py`).
- [ ] `expire_on_commit=False` en la fábrica de sesiones.
- [ ] La cuenta `(pool_size + max_overflow) × procesos × réplicas` está documentada y es menor a `max_connections − reservadas`.
- [ ] `/health/ready` ejecuta `SELECT 1` y devuelve 500 si la base no responde, y no aparece en métricas ni trazas.
- [ ] Reiniciar Postgres con la app arriba: la siguiente request funciona sin reiniciar la app (gracias a `pool_pre_ping`).
- [ ] El `lifespan` de `layering-fastapi-apps` llama a `engine.dispose()` al apagar.
- [ ] Ningún endpoint `async def` usa drivers o librerías bloqueantes.

## Skills relacionadas

- `modeling-postgres-with-sqlalchemy`: modelos, índices y transacciones.
- `migrating-with-alembic`: el `env.py` usa `get_settings().MIGRATION_DATABASE_URL`: la misma base, por conexión directa (detrás de PgBouncer, no el pooler).
- `testing-fastapi-endpoints`: cómo se reemplaza `get_db` en tests con rollback por test.
