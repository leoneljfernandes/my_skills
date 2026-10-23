---
name: migrating-with-alembic
description: Use when changing a PostgreSQL schema managed by SQLAlchemy - creating or reviewing Alembic migrations, autogenerate, alembic.ini/env.py setup (async), renaming columns, adding indexes or constraints on large tables, data migrations, downgrade/rollback, multiple heads - or when autogenerate produces an empty or destructive migration, "Target database is not up to date", or a migration locks production tables.
domain: database
tags: [python, alembic, sqlalchemy, postgresql, migrations, zero-downtime]
triggers: [alembic, "alembic revision", autogenerate, "alembic upgrade", downgrade, "alembic check", migración, migration, "CREATE INDEX CONCURRENTLY", "lock_timeout", "expand contract", "multiple heads", "rename column"]
---

# Migraciones con Alembic

El esquema de cualquier entorno se construye **solo** con migraciones versionadas, revisadas por una persona y probadas en ida y vuelta. Autogenerate propone; el humano decide.

## Contexto y reglas

**Hacer**

- `alembic init -t async alembic`. La URL sale de `get_settings()` (el `sqlalchemy.url` de `alembic.ini` queda vacío). `env.py` importa `app.models` para registrar **todos** los modelos.
- `compare_type=True`, `compare_server_default=True`, `transaction_per_migration=True` en `context.configure`.
- `naming_convention` en `Base.metadata` (ver `modeling-postgres-with-sqlalchemy`). Sin nombres deterministas, `drop_constraint` no sabe qué borrar.
- `file_template` con fecha (`20261023_1837_<rev>_<slug>.py`): orden legible en el repo. Hook `ruff format` sobre lo generado.
- `SET lock_timeout` al inicio. Si la tabla está tomada, la migración falla rápido en vez de encolar todo el tráfico detrás de ella. **Después de ese `execute`, `connection.commit()`**: si no, el autobegin de SQLAlchemy 2.0 deja una transacción abierta, Alembic no commitea y la migración se descarta en silencio.
- Flujo por cambio: modificar modelo → `alembic revision --autogenerate -m "..."` → **leer y corregir el archivo** → `upgrade head` → `alembic check` (sin diferencias) → `downgrade -1` → `upgrade head` → modelo y migración en el **mismo commit**.
- Escribir a mano lo que autogenerate **no detecta**: renombres de tablas o columnas (los ve como drop + add y pierde los datos), `CHECK` constraints (incluido el CHECK de un `Enum` no nativo), valores nuevos de ENUM nativo, cambios dentro de funciones o triggers.
- **Zero-downtime (expand/contract)**: cada deploy debe funcionar con el esquema anterior y el nuevo.
  1. *Expand*: agregar columna nullable / tabla / índice `CONCURRENTLY`.
  2. Deploy de código que escribe en ambos y lee del nuevo; backfill por lotes.
  3. *Contract* (deploy posterior): `NOT NULL`, borrar lo viejo.
- Constraints sobre tablas grandes: `NOT VALID` y después `VALIDATE CONSTRAINT`, que valida sin bloquear escrituras.
- Índices sobre tablas con tráfico: `postgresql_concurrently=True` dentro de `op.get_context().autocommit_block()`.
- CI corre el round-trip `upgrade head → check → downgrade base → upgrade head` contra Postgres real.
- En deploy, un paso `migrate` previo y bloqueante (job/initContainer/servicio compose). La app no arranca si la migración falla.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| Aplicar autogenerate sin leerlo | renombre = drop + add = datos perdidos | revisar y usar `op.alter_column(new_column_name=...)` |
| Editar una migración ya aplicada en otro entorno | entornos con historias distintas e irreconciliables | migración nueva |
| `create_all()` en la app o en scripts de deploy | autogenerate vacío; esquema fuera de control | solo migraciones (create_all solo en tests) |
| `CREATE INDEX` normal sobre tabla grande | bloquea escrituras durante minutos | `CONCURRENTLY` en `autocommit_block` |
| `ADD COLUMN ... NOT NULL` sin default en tabla poblada | falla, o reescribe la tabla con lock | nullable → backfill → `SET NOT NULL` |
| Backfill masivo dentro de la migración de esquema | transacción gigante, locks largos, WAL enorme | script por lotes aparte o migración de datos con `LIMIT` en bucle |
| `downgrade()` con `pass` | sin rollback cuando el deploy falla | implementarlo, o documentar por qué es irreversible y fallar explícito |
| `import app.models.order` dentro de una migración | la migración cambia cuando cambia el modelo | SQL/`sa.table()` literal dentro de la migración |

## Ejemplos

`alembic/env.py` (verificado contra PostgreSQL 17: autogenerate, `check`, round-trip completo):

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.config import get_settings
from app.models import Base  # importa el paquete → registra TODOS los modelos

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# La URL sale de Settings (nunca de alembic.ini). configparser interpreta "%": se escapa.
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata

COMPARE_OPTIONS = {
    "compare_type": True,             # detecta cambios de tipo/longitud
    "compare_server_default": True,   # detecta cambios de server_default
    "transaction_per_migration": True,
}


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: genera el SQL para revisión/DBA sin conectarse."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **COMPARE_OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # lock_timeout: si una tabla está bloqueada por tráfico, la migración falla rápido
    # en vez de encolar (y bloquear) todas las queries de la app detrás de ella.
    connection.execute(text("SET lock_timeout = '5s'"))
    connection.commit()  # cierra el autobegin; si no, Alembic no commitea y todo se descarta
    context.configure(connection=connection, target_metadata=target_metadata, **COMPARE_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # proceso efímero: sin pool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
```

`alembic.ini` (fragmentos que cambian respecto de la plantilla):

```ini
file_template = %%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(rev)s_%%(slug)s
sqlalchemy.url =

[post_write_hooks]
hooks = ruff_format
ruff_format.type = module
ruff_format.module = ruff
ruff_format.options = format REVISION_SCRIPT_FILENAME
```

Migración escrita a mano: CHECK sin bloqueo + índice concurrente (verificada: upgrade, downgrade, re-upgrade, y Postgres rechaza un `status` inválido):

```python
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4156339bb843"
down_revision: str | None = "29d33780007f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Escrita a mano: autogenerate NO detecta CHECK constraints.
    # NOT VALID: se aplica a filas nuevas sin escanear la tabla (lock breve);
    # VALIDATE recorre las existentes con un lock que no bloquea lecturas ni escrituras.
    op.create_check_constraint(
        "order_status",  # la naming convention lo convierte en ck_orders_order_status
        "orders",
        sa.text("status IN ('pending', 'paid', 'cancelled')"),
        postgresql_not_valid=True,
    )
    op.execute("ALTER TABLE orders VALIDATE CONSTRAINT ck_orders_order_status")

    # CONCURRENTLY no puede correr dentro de una transacción.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_products_name", "products", ["name"],
            postgresql_concurrently=True, if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_products_name", table_name="products",
                      postgresql_concurrently=True, if_exists=True)
    op.drop_constraint(op.f("ck_orders_order_status"), "orders", type_="check")
```

Renombre de columna (autogenerate lo propondría como drop + add):

```python
def upgrade() -> None:
    op.alter_column("orders", "customer_email", new_column_name="buyer_email")

def downgrade() -> None:
    op.alter_column("orders", "buyer_email", new_column_name="customer_email")
```

Comandos:

```bash
uv run alembic revision --autogenerate -m "add orders"   # proponer
uv run alembic upgrade head && uv run alembic check       # aplicar + sin drift
uv run alembic downgrade -1 && uv run alembic upgrade head   # probar el rollback
uv run alembic upgrade head --sql > migration.sql         # SQL para revisión/DBA
uv run alembic heads                                      # >1 head tras merge de ramas…
uv run alembic merge -m "merge heads" <rev_a> <rev_b>     # …se unifican con una migración merge
uv run alembic stamp head                                 # adoptar una base existente (una sola vez)
```

## Checklist de verificación

- [ ] `alembic upgrade head` sobre una base **vacía** crea todo, y `alembic check` dice `No new upgrade operations detected.`
- [ ] `downgrade base` + `upgrade head` funciona (o la irreversibilidad está documentada en la migración).
- [ ] La migración se leyó línea por línea: sin drop + add que en realidad sea un renombre, y con los CHECK que autogenerate no ve.
- [ ] Índices nuevos sobre tablas existentes usan `CONCURRENTLY`; constraints sobre tablas grandes usan `NOT VALID` + `VALIDATE`.
- [ ] Cambios incompatibles siguen expand/contract en deploys separados.
- [ ] `alembic heads` muestra una sola head.
- [ ] CI corre el round-trip contra Postgres real (ver `scaffolding-fastapi-backends` → references/ci.md).

## Skills relacionadas

- `modeling-postgres-with-sqlalchemy`: naming conventions, enums y constraints que las migraciones reflejan.
- `configuring-sqlalchemy-sessions`: misma `DATABASE_URL`.
