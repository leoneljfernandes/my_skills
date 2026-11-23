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

- `alembic init -t async alembic`. La URL sale de `get_settings().MIGRATION_DATABASE_URL` (el `sqlalchemy.url` de `alembic.ini` queda vacío) y es la conexión **directa** a Postgres: detrás de PgBouncer (modo transaction) no se migra por el pooler, porque el `SET lock_timeout` queda en un backend que usan otros clientes y las prepared statements pueden chocar. Ahí `DB_HOST`/`DB_PORT` apuntan al pooler y `DB_MIGRATION_HOST`/`DB_MIGRATION_PORT` a la base; sin ellos, `MIGRATION_DATABASE_URL` es la misma `DATABASE_URL`. `env.py` importa `app.models` para registrar **todos** los modelos. Si algún modelo vive fuera de ese paquete (módulos opcionales, extensiones), `env.py` los importa uno por uno: un modelo que `env.py` no ve hace que autogenerate proponga **borrar su tabla**, y `alembic check` lo delata.
- `compare_type=True`, `compare_server_default=True`, `transaction_per_migration=True` en `context.configure`.
- Si el proyecto tiene un tipo propio (`UtcDateTime`), `render_item` lo traduce al tipo base (`sa.DateTime(timezone=True)`): sin él, la migración referencia `app.models.base.UtcDateTime` sin importarlo y `upgrade` falla con `NameError: name 'app' is not defined`; agregar ese import violaría la regla de que las migraciones no importan `app.*`.
- Los datos que la app necesita para funcionar (roles, configuración por defecto) se siembran en la migración con `op.bulk_insert` y SQL literal. Como los tests usan `create_all` y no ejecutan migraciones, `tests/factories.py` tiene su contraparte que los siembra igual.
- `naming_convention` en `Base.metadata` (ver `modeling-postgres-with-sqlalchemy`). Sin nombres deterministas, `drop_constraint` no sabe qué borrar.
- `file_template` con fecha (`20261023_1837_<rev>_<slug>.py`): orden legible en el repo. Hooks `ruff format` y `ruff check --select I --fix` (orden de imports) sobre lo generado.
- `SET lock_timeout` al inicio, también en `run_migrations_offline()`: el SQL de `--sql` que revisa el DBA lleva la misma protección. Si la tabla está tomada, la migración falla rápido en vez de encolar todo el tráfico detrás de ella. Junto a él, `SET statement_timeout = 0`: la migración usa el mismo rol que la app, así que hereda su `ALTER ROLE … SET statement_timeout` (ver `configuring-sqlalchemy-sessions`) y un backfill o un `VALIDATE` largo se cancelaría a mitad de camino. **Después de esos `execute`, `connection.commit()`**: si no, el autobegin de SQLAlchemy 2.0 deja una transacción abierta, Alembic no commitea y la migración se descarta en silencio. Dos causas de `Target database is not up to date` al generar la revisión siguiente: esa migración descartada, o una base con migraciones pendientes (`alembic upgrade head` antes de `revision --autogenerate`).
- Flujo por cambio: modificar modelo → `alembic revision --autogenerate -m "..."` → **leer y corregir el archivo** → `upgrade head` → `alembic check` (sin diferencias) → `downgrade -1` → `upgrade head` → modelo y migración en el **mismo commit**.
- Escribir a mano lo que autogenerate **no detecta**: renombres de tablas o columnas (los ve como drop + add y pierde los datos), **agregar o cambiar** un `CHECK` sobre una tabla existente (incluida la lista de valores de un `Enum` no nativo), valores nuevos de ENUM nativo, cambios dentro de funciones o triggers. En un `create_table` autogenerate sí escribe los CHECK (y el de `Enum(create_constraint=True)`): no duplicarlos a mano.
- **Zero-downtime (expand/contract)**: cada deploy debe funcionar con el esquema anterior y el nuevo.
  1. *Expand*: agregar columna nullable / tabla / índice `CONCURRENTLY`.
  2. Deploy de código que escribe en ambos y lee del nuevo; backfill por lotes.
  3. *Contract* (deploy posterior): `NOT NULL`, borrar lo viejo.
- Constraints sobre tablas grandes: `NOT VALID` y después `VALIDATE CONSTRAINT`, que valida sin bloquear escrituras, **en revisiones separadas**: en la misma transacción, el lock exclusivo del `ADD` dura todo el `VALIDATE`.
- `SET NOT NULL` sobre una tabla grande escanea con `ACCESS EXCLUSIVE`, salvo que un CHECK `columna IS NOT NULL` ya validado pruebe que no hay NULL (PostgreSQL 12+): primero ese CHECK (`NOT VALID` + `VALIDATE`, en revisiones separadas), después `SET NOT NULL` y borrar el CHECK (ejemplo abajo).
- Índices sobre tablas con tráfico: `postgresql_concurrently=True` dentro de `op.get_context().autocommit_block()`, **solo en su revisión**: `autocommit_block` commitea lo anterior, así que una revisión con él no mezcla DDL transaccional.
- Las revisiones tienen que poder reintentarse tras un `lock_timeout`. `IF NOT EXISTS` no sirve para eso: un `CREATE INDEX CONCURRENTLY` interrumpido deja un índice **inválido** (`indisvalid = f`) y `IF NOT EXISTS` lo acepta sin recrearlo, mientras `alembic check` dice que no hay diferencias. Se hace `drop_index(..., if_exists=True)` y después `create_index`.
- CI corre el round-trip `upgrade head → check → downgrade base → upgrade head` contra Postgres real.
- En deploy, un paso `migrate` previo y bloqueante (job/initContainer/servicio compose). La app no arranca si la migración falla.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| Aplicar autogenerate sin leerlo | renombre = drop + add = datos perdidos | revisar y usar `op.alter_column(new_column_name=...)` con ventana de mantenimiento, o expand/contract si no la hay |
| Editar una migración ya aplicada en otro entorno | entornos con historias distintas e irreconciliables | migración nueva |
| `create_all()` en la app o en scripts de deploy | autogenerate vacío; esquema fuera de control | solo migraciones (create_all solo en tests) |
| `CREATE INDEX` normal sobre tabla grande | bloquea escrituras durante minutos | `CONCURRENTLY` en `autocommit_block`, en su propia revisión |
| `ADD CONSTRAINT ... NOT VALID` y `VALIDATE` en la misma revisión | el `VALIDATE` corre con el lock del `ADD` y bloquea lecturas y escrituras | una revisión para cada uno |
| `create_index(..., if_not_exists=True)` para reintentar | acepta un índice inválido que dejó un intento fallido | `drop_index(if_exists=True)` + `create_index` |
| `ADD COLUMN ... NOT NULL` sin default en tabla poblada | falla, o reescribe la tabla con lock | nullable → backfill → CHECK `IS NOT NULL` (`NOT VALID` + `VALIDATE`) → `SET NOT NULL` |
| Backfill masivo dentro de la migración de esquema | transacción gigante, locks largos, WAL enorme | script por lotes aparte o migración de datos con `LIMIT` en bucle |
| `downgrade()` con `pass` | sin rollback cuando el deploy falla | implementarlo, o documentar por qué es irreversible y fallar explícito |
| `import app.models.order` dentro de una migración | la migración cambia cuando cambia el modelo | SQL/`sa.table()` literal dentro de la migración |

## Ejemplos

`alembic/env.py` (verificado (test) contra PostgreSQL 16.15: autogenerate, `check`, round-trip completo, conexión directa con `DB_HOST` apuntando a un pooler, y una migración más larga que el `statement_timeout` del rol):

```python
import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.config import get_settings
from app.models import Base, UtcDateTime  # importa el paquete → registra TODOS los modelos

# Si hay modelos fuera de app.models, importarlos acá, uno por uno:
# import app.models.extra.invoices  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# La URL sale de Settings (nunca de alembic.ini) y va directo a Postgres, no por PgBouncer.
# configparser interpreta "%": se escapa.
config.set_main_option("sqlalchemy.url", get_settings().MIGRATION_DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata

def render_item(type_: str, obj: Any, _autogen_context: Any) -> str | bool:
    # Las migraciones no importan app.*: el tipo propio se escribe como el tipo de base que es.
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


COMPARE_OPTIONS = {
    "compare_type": True,             # detecta cambios de tipo/longitud
    "compare_server_default": True,   # detecta cambios de server_default
    "transaction_per_migration": True,
    "render_item": render_item,
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
    # El SQL para el DBA lleva la misma protección que la migración en vivo.
    context.execute("SET lock_timeout = '5s'")
    context.execute("SET statement_timeout = 0")
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # lock_timeout: si una tabla está bloqueada por tráfico, la migración falla rápido
    # en vez de encolar (y bloquear) todas las queries de la app detrás de ella.
    connection.execute(text("SET lock_timeout = '5s'"))
    # statement_timeout: el ALTER ROLE ... SET statement_timeout de la app también rige acá (mismo rol);
    # un backfill o un VALIDATE largo no debe cortarse a mitad de camino.
    connection.execute(text("SET statement_timeout = 0"))
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
# Primero el orden de imports (el formato solo no lo toca), después el formato.
hooks = ruff_imports, ruff_format
ruff_imports.type = module
ruff_imports.module = ruff
ruff_imports.options = check --select I --fix REVISION_SCRIPT_FILENAME
ruff_format.type = module
ruff_format.module = ruff
ruff_format.options = format REVISION_SCRIPT_FILENAME
```

Tres revisiones escritas a mano para agregar un CHECK y un índice a tablas con tráfico (la revisión base `29d33780007f` ya creó `orders` y `products`), verificadas (test) contra PostgreSQL 16.15: upgrade, downgrade, re-upgrade, reintento tras un `lock_timeout` con `indisvalid = t`, y Postgres rechaza un `status` inválido. Cada una va en su archivo, y ninguna mezcla un `NOT VALID` con su `VALIDATE` ni DDL transaccional con `autocommit_block`. Primera, el CHECK sin escanear:

```python
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4156339bb843"
down_revision: str | None = "29d33780007f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Agregar un CHECK a una tabla existente no lo detecta autogenerate: va a mano.
    # NOT VALID: rige para las filas nuevas sin escanear la tabla (lock breve).
    op.create_check_constraint(
        "order_status",  # la naming convention lo convierte en ck_orders_order_status
        "orders",
        sa.text("status IN ('pending', 'paid', 'cancelled')"),
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_orders_order_status"), "orders", type_="check")
```

Segunda, que valida las filas existentes. Sola en su revisión, el `VALIDATE` toma un lock que no bloquea lecturas ni escrituras:

```python
from collections.abc import Sequence

from alembic import op

revision: str = "7c1e5a9d2b30"
down_revision: str | None = "4156339bb843"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders VALIDATE CONSTRAINT ck_orders_order_status")


def downgrade() -> None:
    # No-op deliberado: VALIDATE no tiene inverso, y la revisión anterior borra el constraint al bajar.
    pass
```

Tercera, el índice, sola en su revisión y reintentable:

```python
from collections.abc import Sequence

from alembic import op

revision: str = "a3f9c0de5b71"
down_revision: str | None = "7c1e5a9d2b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # CONCURRENTLY no puede correr dentro de una transacción. Si un intento anterior murió por
    # lock_timeout, dejó un índice inválido: se borra y se recrea. IF NOT EXISTS lo daría por bueno.
    with op.get_context().autocommit_block():
        op.drop_index("ix_products_name", table_name="products", postgresql_concurrently=True, if_exists=True)
        op.create_index("ix_products_name", "products", ["name"], postgresql_concurrently=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_products_name", table_name="products", postgresql_concurrently=True, if_exists=True)
```

`SET NOT NULL` sobre una tabla grande, en tres revisiones (verificado (test) contra PostgreSQL 16.15: con el CHECK validado, PostgreSQL no reescanea la tabla):

```sql
-- revisión 1: rige para filas nuevas, sin escanear
ALTER TABLE orders ADD CONSTRAINT ck_orders_buyer_email_not_null CHECK (buyer_email IS NOT NULL) NOT VALID;
-- revisión 2: valida las existentes sin bloquear lecturas ni escrituras
ALTER TABLE orders VALIDATE CONSTRAINT ck_orders_buyer_email_not_null;
-- revisión 3: el CHECK validado ya prueba que no hay NULL, así que no hay escaneo
ALTER TABLE orders ALTER COLUMN buyer_email SET NOT NULL;
ALTER TABLE orders DROP CONSTRAINT ck_orders_buyer_email_not_null;
```

Renombre de columna **con ventana de mantenimiento** (app detenida o sin escrituras: `RENAME COLUMN` es inmediato, y el código anterior deja de encontrar la columna hasta terminar el deploy). Sin ventana va expand/contract: columna nueva, escribir en ambas, backfill por lotes, leer de la nueva y, en un deploy posterior, borrar la vieja. Autogenerate lo propondría como drop + add:

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
uv run alembic upgrade head --sql > migration.sql         # SQL para revisión/DBA (lleva lock_timeout)
uv run alembic heads                                      # >1 head tras merge de ramas…
uv run alembic merge -m "merge heads" <rev_a> <rev_b>     # …se unifican con una migración merge
uv run alembic stamp head                                 # adoptar una base existente (una sola vez)
```

## Checklist de verificación

- [ ] `alembic upgrade head` sobre una base **vacía** crea todo, y `alembic check` dice `No new upgrade operations detected.`
- [ ] `downgrade base` + `upgrade head` funciona (o la irreversibilidad está documentada en la migración).
- [ ] La migración se leyó línea por línea: sin drop + add que en realidad sea un renombre, con a mano los CHECK que autogenerate no ve (los agregados a una tabla existente) y sin duplicar los que ya escribió en un `create_table`.
- [ ] Índices nuevos sobre tablas existentes usan `CONCURRENTLY`; constraints sobre tablas grandes usan `NOT VALID` + `VALIDATE` en revisiones separadas, y el índice va solo en la suya.
- [ ] `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid` no devuelve filas: un `CREATE INDEX CONCURRENTLY` interrumpido deja un índice inválido que `alembic check` no ve.
- [ ] `alembic upgrade head --sql` empieza con `SET lock_timeout` y `SET statement_timeout = 0`.
- [ ] Cambios incompatibles siguen expand/contract en deploys separados.
- [ ] `alembic heads` muestra una sola head.
- [ ] CI corre el round-trip contra Postgres real (ver `scaffolding-fastapi-backends` → references/ci.md).

## Skills relacionadas

- `modeling-postgres-with-sqlalchemy`: naming conventions, enums y constraints que las migraciones reflejan.
- `configuring-sqlalchemy-sessions`: la misma base que la app; detrás de PgBouncer, la URL directa (`MIGRATION_DATABASE_URL`).
