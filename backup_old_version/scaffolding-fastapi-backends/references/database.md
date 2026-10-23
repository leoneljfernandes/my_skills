# Base de datos: SQLAlchemy async, migraciones y seed

## Engine y sesión (`app/database.py`)

```python
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # descarta conexiones muertas (reinicio de Postgres)
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,    # recicla antes de que el servidor corte conexiones ociosas
    echo=settings.DB_ECHO,
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
```

Por qué async: una API es I/O-bound; mientras espera a Postgres el event loop atiende otras requests.
`expire_on_commit=False`: después del `commit` los atributos siguen accesibles sin otra ida a la base (en async, un acceso que dispara I/O implícito rompe).

Una sola `get_db` en todo el proyecto: es la que los tests sobreescriben.

## Modelos (`app/models/`)

`app/models/__init__.py` define `Base` y re-exporta los modelos, así importar el paquete registra todas las tablas:

```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

from app.models.user import User, PasswordResetToken  # noqa: E402,F401
from app.models.notification import Notification, ChannelType  # noqa: E402,F401
```

Estilo SQLAlchemy 2.0 tipado (`Mapped` + `mapped_column`) en todas las columnas:

```python
import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class ChannelType(str, enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(String(500))
    is_read: Mapped[bool] = mapped_column(default=False, server_default="false")
    channel_type: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, values_callable=lambda e: [m.value for m in e])  # guarda "email", no "EMAIL"
    )
    channel_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="notifications", lazy="selectin")
```

Decisiones:

- **Timestamps con zona horaria** (`DateTime(timezone=True)`), generados por el servidor (`server_default=func.now()`).
- **Relaciones con `lazy="selectin"`** (o `selectinload()` en la query): async no soporta lazy loading implícito → `MissingGreenlet`.
- **Cascadas** en el lado padre: `relationship(..., cascade="all, delete-orphan")` + `ondelete="CASCADE"` en la FK.
- **Defaults mutables** con callable (`default=dict`), nunca `default={}`.
- **Enums**: `values_callable` para persistir el valor. En Postgres un enum nativo es un tipo; agregar un valor exige migración manual (`op.execute("ALTER TYPE ... ADD VALUE ...")`).
- **Emails únicos e indexados**; la búsqueda por email compara en minúsculas (`func.lower(User.email) == email.lower()`), y al registrar se guarda normalizado.

## Repositorios (`app/crud/`)

```python
async def get_notification(db: AsyncSession, notification_id: int) -> Notification | None:
    return await db.get(Notification, notification_id)

async def list_notifications(db: AsyncSession, user_id: int, skip: int = 0, limit: int = 50):
    result = await db.execute(
        select(Notification).where(Notification.user_id == user_id).offset(skip).limit(limit)
    )
    return result.scalars().all()

async def update_notification(db: AsyncSession, obj: Notification, data: NotificationUpdate):
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    await db.commit()
    await db.refresh(obj)
    return obj
```

Devuelven entidades o `None`; la decisión 404/403 la toma la capa `api`.

## Migraciones (Alembic, modo async)

Inicializar con la plantilla async: `uv run alembic init -t async alembic`.

`alembic.ini`: dejar `sqlalchemy.url =` vacío (la URL viene de `Settings`).

`alembic/env.py` — cambios sobre la plantilla:

```python
from app.config import settings
from app.models import Base  # importa y registra TODOS los modelos

config = context.config
# configparser interpreta "%": hay que escaparlo (contraseñas con caracteres especiales)
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata
```

El resto de la plantilla async queda igual (`async_engine_from_config(..., poolclass=pool.NullPool)` + `connection.run_sync(do_run_migrations)`).

Flujo para un cambio de esquema:

1. Modificar el modelo.
2. `uv run alembic revision --autogenerate -m "descripcion"`.
3. **Revisar el archivo generado**: autogenerate no detecta renombres (los ve como drop + add, perdiendo datos) ni cambios de valores de enums.
4. `uv run alembic upgrade head` y `uv run alembic check` (sin diferencias = listo).
5. `uv run alembic downgrade -1 && uv run alembic upgrade head` para probar el `downgrade`.
6. Modelo y migración en el **mismo commit**.

Reglas:

- La primera migración se genera contra una base **vacía**. Para adoptar una base existente: `alembic stamp head`.
- Nunca editar una migración ya aplicada en otro entorno; se crea una nueva.
- En Docker, un servicio `migrate` corre `alembic upgrade head` y el backend arranca solo si terminó bien (ver docker.md). Un fallo de migración frena el deploy en vez de levantar una app con esquema roto.

Comandos de consulta: `alembic current`, `alembic history --verbose`, `alembic upgrade head --sql` (ver el SQL sin ejecutar).

## Seed de datos de prueba (`app/seed.py`)

Datos de desarrollo que cubren todas las variantes del dominio (cada canal, un admin y usuarios comunes, leído/no leído).

```python
"""Datos de ejemplo para desarrollo. Uso (con migraciones aplicadas): uv run python -m app.seed"""
import asyncio

from sqlalchemy import select

from app.auth import hash_password
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models import ChannelType, Notification, User

SEED_PASSWORD = "Password123"  # solo desarrollo; documentada en el README

SEED_USERS = [
    {
        "email": "ana@example.com", "name": "Ana Admin", "is_admin": True,
        "notifications": [
            {"title": "Bienvenida", "message": "Cuenta creada.", "channel_type": ChannelType.EMAIL,
             "channel_metadata": {}, "is_read": True},
            {"title": "Código", "message": "Tu código es 482913.", "channel_type": ChannelType.SMS,
             "channel_metadata": {"phone_number": "5491112345678"}},
        ],
    },
    # ... un usuario por combinación relevante
]


async def seed() -> None:
    if settings.ENVIRONMENT == "production":
        raise SystemExit("El seed no corre en producción")

    async with AsyncSessionLocal() as session:
        for data in SEED_USERS:
            exists = await session.scalar(select(User.id).where(User.email == data["email"]))
            if exists:
                print(f"= {data['email']} ya existe, se omite")
                continue
            user = User(
                email=data["email"], name=data["name"], is_admin=data["is_admin"],
                password_hash=hash_password(SEED_PASSWORD),
            )
            user.notifications = [Notification(**n) for n in data["notifications"]]
            session.add(user)
            print(f"+ {data['email']} creado")
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
```

Decisiones:

- **Idempotente** por clave natural (email): se puede correr N veces sin duplicar.
- Corre **después** de las migraciones; nunca crea tablas.
- Usa las mismas funciones del dominio (`hash_password`) que la app: los usuarios del seed pueden loguearse de verdad.
- Se ejecuta como módulo: `uv run python -m app.seed` local, `docker compose exec backend python -m app.seed` en contenedores.
- Tabla de usuarios/roles/contraseña del seed en el README.
