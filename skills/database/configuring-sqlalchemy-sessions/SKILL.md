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

- **Async por defecto** (`asyncpg`) en APIs I/O-bound. **Sync** (`psycopg` 3) si el resto del stack es síncrono o hay librerías bloqueantes; en ese caso los endpoints se declaran `def` y FastAPI los corre en su threadpool.
- `engine` y `SessionFactory` a nivel de módulo (`app/database.py`), creados desde `Settings`. `await engine.dispose()` en el `lifespan` al apagar.
- `async_sessionmaker(engine, expire_on_commit=False)`. Con `expire_on_commit=True` (el default), leer un atributo después del commit dispara I/O implícito, que en async rompe con `MissingGreenlet`.
- `get_db()` abre la sesión con `async with` y **no commitea**: el commit lo decide el service (ver `layering-fastapi-apps`). Al cerrar, lo no commiteado se descarta.
- `pool_pre_ping=True` (sobrevive a failovers y reinicios), `pool_recycle` < timeout de inactividad de firewalls/LB, `pool_timeout` corto (falla rápido en vez de colgar requests).
- `application_name` y `statement_timeout` por conexión vía `connect_args`: trazabilidad en `pg_stat_activity` y ninguna query eterna.
- **Dimensionar el pool**: `(pool_size + max_overflow) × procesos × réplicas ≤ max_connections − reservadas` (superuser, migraciones, monitoreo). Ejemplo: 4 workers × 3 réplicas × 20 = 240 → hace falta `max_connections ≥ 260` o PgBouncer.
- **PgBouncer en modo transaction**: el pooling lo hace PgBouncer, así que usar `poolclass=NullPool` y desactivar las prepared statements de asyncpg (`statement_cache_size=0`, `prepared_statement_cache_size=0`).
- Los endpoints de salud (`/health/live`, `/health/ready`) pueden montarse bajo el prefijo de la API (`/api/v1/health`) para que un cliente web los consulte. Las exclusiones de métricas y trazas (`/health/.*`) son regex sin anclar y siguen cubriéndolos (verificado con `/api/v1/health/live`): no hace falta repetirlas.
- Workers, CLIs y seeds abren su propia sesión con `async with SessionFactory() as session:`. Nunca reutilizar la sesión de una request.
- Relaciones con `lazy="raise"` y carga explícita (`selectinload`/`joinedload`) en el repositorio (ver `modeling-postgres-with-sqlalchemy`).

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `create_async_engine(...)` por request o por test de la app | conexiones nuevas cada vez, el pool no sirve | un engine por proceso |
| Sesión global compartida entre requests | estado cruzado entre usuarios, condiciones de carrera | sesión por request vía `Depends(get_db)` |
| Commit dentro de `get_db` después del `yield` | se ejecuta tras enviar la respuesta: el cliente ve 200 aunque el commit falle | commit explícito en el service |
| Acceder a `obj.relacion` sin cargarla (async) | `MissingGreenlet` | `selectinload()` en la query |
| `pool_size=100` "por si acaso" | agota `max_connections` con pocas réplicas | fórmula de arriba + métricas del pool |
| Endpoint `async def` que llama a un driver sync | bloquea el event loop entero | `def` + engine sync, o driver async |
| Mezclar `asyncio.gather` sobre la misma `AsyncSession` | una sesión no es concurrente: error o corrupción | una sesión por tarea concurrente |

## Ejemplos

`app/database.py` async (verificado contra PostgreSQL 17 con pytest + testcontainers):

```python
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings


def build_engine(settings: Settings) -> AsyncEngine:
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

Detrás de PgBouncer (modo transaction):

```python
from sqlalchemy.pool import NullPool

engine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,  # PgBouncer ya hace el pooling
    connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
)
```

Variante síncrona (verificada con `psycopg` 3 contra PostgreSQL 17):

```python
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

engine = create_engine(
    "postgresql+psycopg://app:secret@db:5432/app_db",
    pool_size=40,          # = hilos del threadpool de AnyIO: cada endpoint `def` toma un hilo y una conexión
    max_overflow=0,
    pool_timeout=10,
    pool_recycle=1800,
    pool_pre_ping=True,
)
SessionFactory = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionFactory() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


@app.get("/health/ready")
def ready(db: DbSession) -> dict[str, int]:  # `def`, no `async def`: corre en el threadpool
    return {"one": db.execute(text("SELECT 1")).scalar_one()}
```

Sesión fuera de una request (worker, CLI, seed):

```python
async def expire_pending_orders() -> int:
    async with SessionFactory() as session:
        result = await session.execute(
            update(Order)
            .where(Order.status == OrderStatus.PENDING, Order.created_at < func.now() - text("interval '1 day'"))
            .values(status=OrderStatus.CANCELLED)
        )
        await session.commit()
        return result.rowcount
```

## Checklist de verificación

- [ ] `grep -rn "create_async_engine\|create_engine" app/` aparece solo en `app/database.py` (y en `tests/conftest.py`).
- [ ] `expire_on_commit=False` en la fábrica de sesiones.
- [ ] La cuenta `(pool_size + max_overflow) × procesos × réplicas` está documentada y es menor a `max_connections − reservadas`.
- [ ] `/health/ready` (donde esté montado) ejecuta `SELECT 1` y devuelve 500 si la base no responde, y no aparece en métricas ni trazas.
- [ ] Reiniciar Postgres con la app arriba: la siguiente request funciona sin reiniciar la app (gracias a `pool_pre_ping`).
- [ ] `lifespan` llama a `engine.dispose()` al apagar.
- [ ] Ningún endpoint `async def` usa drivers o librerías bloqueantes.

## Skills relacionadas

- `modeling-postgres-with-sqlalchemy`: modelos, índices y transacciones.
- `migrating-with-alembic`: el `env.py` reutiliza `get_settings().DATABASE_URL`.
- `testing-fastapi-endpoints`: cómo se reemplaza `get_db` en tests con rollback por test.
