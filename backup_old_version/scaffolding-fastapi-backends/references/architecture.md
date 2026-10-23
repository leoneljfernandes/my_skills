# Arquitectura: capas, config y patrones

## Estructura de carpetas

```text
proyecto/
├── app/
│   ├── main.py            # crea FastAPI, lifespan, routers, /metrics, telemetría
│   ├── config.py          # Settings (pydantic-settings) — única fuente de config
│   ├── database.py        # engine async, AsyncSessionLocal, get_db()
│   ├── auth.py            # hashing, JWT, get_current_user / CurrentUser
│   ├── telemetry.py       # OpenTelemetry (ver observability.md)
│   ├── seed.py            # datos de desarrollo (ver database.md)
│   ├── api/               # PRESENTACIÓN: routers, solo HTTP
│   │   ├── __init__.py    # api_router que agrupa los sub-routers
│   │   └── <recurso>.py
│   ├── services/          # CASOS DE USO: lógica de negocio, estrategias
│   ├── crud/              # REPOSITORIOS: único lugar con queries SQLAlchemy
│   ├── models/            # ENTIDADES ORM; __init__.py define Base
│   └── schemas/           # DTOs Pydantic: <X>Create / <X>Update / <X>Response
├── alembic/  alembic.ini  # migraciones
├── tests/                 # E2E (conftest.py + test_<recurso>.py)
├── frontend/              # app web con su propio Dockerfile
├── monitoring/            # config versionada de Prometheus/Loki/Tempo/Alloy/Grafana
├── Dockerfile  .dockerignore  docker-compose.yml
├── .circleci/config.yml
├── pyproject.toml  uv.lock  pytest.ini
└── README.md
```

## Responsabilidad de cada capa

| Capa | Hace | Depende de |
|---|---|---|
| `api/` | valida entrada (schemas), resuelve dependencias (`get_db`, `CurrentUser`), chequea **ownership** (403), traduce `None` → 404, elige status code | `services`, `crud`, `schemas` |
| `services/` | reglas de negocio, orquesta repositorios, lanza **excepciones de dominio** (nunca `HTTPException`) | `crud`, `models` |
| `crud/` | queries `select/insert/update/delete`, `commit` + `refresh`; devuelve entidades o `None` | `models`, `schemas` (para leer DTOs) |
| `models/` | tablas y relaciones | `Base` |
| `schemas/` | contratos de entrada/salida; los `Response` nunca incluyen `password_hash` | — |

Por qué: los routers quedan finos y testeables vía HTTP; cambiar de base o de proveedor (email, SMS) toca una sola capa.

## Config: `app/config.py`

`pydantic-settings` lee `.env` y el entorno. Todo valor viene de acá.

```python
from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DB_USER: str = "postgres"
    DB_PASSWORD: SecretStr = SecretStr("postgres")
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "app_db"
    DB_ECHO: bool = False

    SECRET_KEY: SecretStr = Field(min_length=32)  # obligatoria: sin ella la app no arranca
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    ENVIRONMENT: str = "development"  # development | test | production

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        # URL.create escapa caracteres especiales de la contraseña
        return URL.create(
            "postgresql+asyncpg",
            username=self.DB_USER,
            password=self.DB_PASSWORD.get_secret_value(),
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        ).render_as_string(hide_password=False)


settings = Settings()
```

- Los campos se declaran con default literal; **no** `os.getenv(...)` en el cuerpo de la clase (se evalúa al importar e ignora `env_file`).
- Listas desde el entorno van en JSON: `CORS_ORIGINS='["http://localhost:5173"]'`.
- `SecretStr` para todo secreto: no aparece en logs ni en `repr`.
- `SECRET_KEY` de 32+ bytes (`python -c "import secrets; print(secrets.token_urlsafe(32))"`); PyJWT advierte con claves más cortas.

## `app/main.py`

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api import api_router
from app.config import settings
from app.database import engine
from app.errors import register_exception_handlers
from app.telemetry import setup_telemetry


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # el esquema lo crean las migraciones, no create_all
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # lista explícita, nunca "*" con credenciales
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")
setup_telemetry(app, engine)
app.include_router(api_router, prefix="/api")
```

`app/api/__init__.py` agrupa sub-routers con `prefix` y `tags`:

```python
from fastapi import APIRouter
from app.api import notifications, users

api_router = APIRouter()
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
```

## Errores de dominio → HTTP

Los `services` lanzan excepciones propias; un handler global las traduce. Así ningún error de validación de negocio termina en 500.

```python
# app/errors.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = 400

class NotFoundError(DomainError):
    status_code = 404

class ValidationFailed(DomainError):
    status_code = 422


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})
```

## Patrón Strategy (para variantes intercambiables)

Usado para canales de notificación (email/SMS/push). Aplica a cualquier "mismo contrato, N implementaciones" (proveedores de pago, exportadores, etc.).

```python
# services/channel.py — interfaz
from abc import ABC, abstractmethod

class ChannelStrategy(ABC):          # heredar de ABC hace cumplir @abstractmethod
    @abstractmethod
    async def send(self, notification: Notification) -> None: ...

# services/sms.py — estrategia concreta
class SMSStrategy(ChannelStrategy):
    async def send(self, notification):
        phone = notification.channel_metadata.get("phone_number")
        if not phone or not phone.isdigit():
            raise ValidationFailed("Invalid phone number provided.")
        ...

# services/dispatcher.py — contexto con registro
class NotificationDispatcher:
    _strategies: dict[ChannelType, ChannelStrategy] = {
        ChannelType.EMAIL: EmailStrategy(),
        ChannelType.SMS: SMSStrategy(),
        ChannelType.PUSH: PushStrategy(),
    }

    @classmethod
    async def dispatch(cls, notification) -> None:
        strategy = cls._strategies.get(notification.channel_type)
        if strategy is None:
            raise ValidationFailed(f"No strategy for channel: {notification.channel_type}")
        await strategy.send(notification)
```

Por qué: Open/Closed — un canal nuevo es una clase nueva + una entrada en el registro; endpoints y dispatcher no cambian.

## Schemas Pydantic

- Trío por recurso: `XCreate` (campos requeridos + validadores), `XUpdate` (todo `Optional`, se aplica con `model_dump(exclude_unset=True)`), `XResponse` (`model_config = ConfigDict(from_attributes=True)`).
- Valores cerrados como `Literal[...]` o el `enum` del modelo, no `str` + validador manual.
- `EmailStr` para emails (`email-validator` en dependencias).
- Todo endpoint declara `response_model`: filtra campos sensibles aunque el ORM los tenga.

## Endpoints

- Recursos REST: `GET /api/notifications`, `POST /api/notifications` (201), `PUT /api/notifications/{id}`, `DELETE /api/notifications/{id}` (204). Verbo en el método HTTP, no en la URL.
- Listados con paginación `skip`/`limit` desde el inicio.
- Dependencias tipadas con `Annotated`: `db: DbSession`, `user: CurrentUser`.
- Ownership: buscar → 404 si no existe → 403 si `obj.user_id != user.id` → operar.
- Trabajo lento (envíos a proveedores externos) va a `BackgroundTasks` o a una cola (ARQ/Celery) devolviendo 202.

## Dependencias (`pyproject.toml`)

```toml
[project]
requires-python = ">=3.14"
dependencies = [
  "fastapi", "uvicorn[standard]", "pydantic", "pydantic-settings", "email-validator",
  "python-multipart",                         # OAuth2PasswordRequestForm
  "sqlalchemy[asyncio]", "asyncpg", "alembic",
  "pyjwt", "pwdlib[argon2,bcrypt]",
  "prometheus-fastapi-instrumentator",
  "opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-grpc",
  "opentelemetry-instrumentation-fastapi", "opentelemetry-instrumentation-sqlalchemy",
  "opentelemetry-instrumentation-logging",
]

[dependency-groups]
dev = ["pytest", "httpx", "aiosqlite", "coverage", "ruff"]
```

Solo lo que se importa. Las herramientas de test y cobertura van en el grupo `dev` (uv lo instala por defecto en `uv sync`; la imagen de producción usa `--no-dev`).
