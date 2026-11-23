---
name: configuring-fastapi-settings
description: Use when a FastAPI/Python service needs configuration or environment variables - adding a setting, secrets, .env files, per-stage config (dev, test, staging, prod), pydantic-settings BaseSettings, DATABASE_URL, or when code reads os.environ/os.getenv directly or a misconfigured deploy started with development defaults.
domain: backend
tags: [python, fastapi, pydantic-settings, configuration, twelve-factor, secrets]
triggers: [pydantic-settings, BaseSettings, ".env", "variables de entorno", "env vars", "staging", "producción", "SecretStr", "os.getenv", "configuración por entorno", "DATABASE_URL"]
---

# Configuración por stage con pydantic-settings

Una sola clase `Settings` es la única fuente de configuración. Valida al arrancar y **falla rápido**: un deploy mal configurado no llega a atender requests.

## Contexto y reglas

**Hacer**

- Un `app/config.py` con `Settings(BaseSettings)`. App, Alembic, seeds, workers y telemetría importan `get_settings()`. Nadie más lee `os.environ`.
- Elegir el stage con `APP_ENV` (`dev | test | staging | prod`), **exportada en el entorno real**: ella decide qué archivo se carga, así que escribirla dentro de un `.env` no sirve y `get_settings()` falla con un error legible si lo intentás. Los archivos se cargan en cascada: `.env` → `.env.<stage>`, y **las variables de entorno reales ganan siempre**. En contenedores y CI la config llega por entorno; los `.env` son solo para desarrollo.
- Anclar los `.env` a la raíz del repositorio con `ROOT_DIR`, no al directorio actual: Alembic o un worker se ejecutan desde otra carpeta.
- Si `APP_ENV=test`, `get_settings()` no lee ningún `.env` (`_env_file=None`): un `.env` local de desarrollo no puede apuntar los tests a otra base.
- Activar `env_ignore_empty=True`: una clave vacía copiada de `.env.example` (`DB_PORT=`) usa el default o falta; no vale `""`.
- Listas en el entorno: `list[str]` se lee como JSON (`'["a","b"]'`). Si se quiere escribir `a,b`, anotar el campo con `NoDecode` y agregar un `field_validator(mode="before")` que divida por comas.
- `SecretStr` para todo secreto: no aparece en `repr`, en logs ni en tracebacks. Se lee con `.get_secret_value()` solo en el punto de uso.
- Secretos, credenciales y URLs obligatorios **sin default** (`SECRET_KEY: SecretStr = Field(min_length=32)`, `DB_PASSWORD`, `DB_HOST`): sin ellos la app no arranca. Un default de desarrollo (`"postgres"`) solo logra que prod arranque contra la base equivocada sin avisar.
- Un `@model_validator(mode="after")` aplica guardas de producción: `DEBUG` apagado, CORS sin `*`, cookies solo por HTTPS.
- Todo campo calculado que contenga un secreto (`DATABASE_URL`, `MIGRATION_DATABASE_URL`) lleva `@computed_field(repr=False)`: sin eso aparece en `repr(settings)`.
- Las migraciones van **directo a Postgres**, nunca por PgBouncer (ahí `SET lock_timeout` se filtra a otros clientes). Con PgBouncer, `DB_HOST`/`DB_PORT` apuntan al pooler y `DB_MIGRATION_HOST`/`DB_MIGRATION_PORT` a la base; sin ellos, `MIGRATION_DATABASE_URL` es igual a `DATABASE_URL`. `DB_DRIVER` elige `asyncpg` (default) o `psycopg` (variante síncrona).
- `get_settings()` con `@lru_cache`: se construye una vez y se inyecta con `Depends(get_settings)`. `app.dependency_overrides[get_settings]` solo cambia lo que se inyecta con `SettingsDep`. El resto no pasa por la inyección: los errores llaman a `get_settings()` en cada request; `create_app()` lo llama una vez y le pasa esa `settings` al logging, las métricas y el tracing; el engine se crea **al importar** `app.database`, con la config de ese momento. Para otra configuración en un test: variables de entorno + `get_settings.cache_clear()` antes de `create_app()` (fixture `env`, abajo). Otra base u otro pool exigen fijar el entorno antes del primer import de `app.database` (lo hace el `conftest.py`) o sobreescribir `get_db`.
- `frozen=True`: la config es inmutable en runtime.
- Versionar un único `.env.example` (el de abajo) con todas las claves: las opcionales, comentadas. Los secretos van **vacíos** (`SECRET_KEY=`), no con un valor de ejemplo: un placeholder que pasa la validación llega a producción. `.env*` reales van en `.gitignore` y `.dockerignore`.

**Evitar (anti-patrones)**

| Anti-patrón | Por qué es un problema | En su lugar |
|---|---|---|
| `os.getenv("X")` disperso por el código | config invisible, sin validación, `None` silencioso | campo tipado en `Settings` |
| `X: str = os.getenv("X", "...")` dentro de la clase | se evalúa al importar e ignora `env_file` | default literal; pydantic-settings lee el entorno |
| `if ENV == "prod":` repartido por la app | lógica de entorno acoplada al dominio | flags explícitos en `Settings` (`DOCS_ENABLED`, `OTEL_...`) |
| Default de desarrollo para secretos o credenciales (`SECRET_KEY="changeme"`, `DB_PASSWORD="postgres"`) | prod arranca "funcionando" con un valor público o contra la base equivocada | campo obligatorio, sin default |
| `.env.prod` versionado con secretos | filtración permanente en el historial git | gestor de secretos / variables del orquestador |
| `str` para contraseñas | aparecen en logs y en errores de validación | `SecretStr` |
| Leer settings en import-time de módulos de dominio | imposible de sobreescribir en tests | inyectar `Settings` o llamar `get_settings()` en el punto de uso |

## Ejemplos

`app/config.py` (verificado (test) con mypy `--strict` y pytest):

```python
import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from fastapi import Depends
from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL

# Los .env viven en la raíz del repositorio, no en el directorio desde donde se ejecuta el
# comando (Alembic, un worker o pytest corren desde cualquier carpeta). Con el backend en
# `backend/app/config.py` la raíz es parents[2]; con `app/config.py` en la raíz, parents[1].
ROOT_DIR = Path(__file__).resolve().parents[2]


# Prefijos de valores de ejemplo: si llegan a staging/prod, la app no arranca.
SECRET_PLACEHOLDERS = ("test-secret", "changeme", "generar", "cambiar")


class Stage(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class Settings(BaseSettings):
    # Prioridad (mayor a menor): variables de entorno > .env.<stage> > .env > defaults.
    # env_ignore_empty: una clave vacía (como en .env.example) usa el default o falta; no vale "".
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8", extra="ignore", frozen=True, env_ignore_empty=True
    )

    APP_ENV: Stage = Stage.DEV
    APP_NAME: str = "orders-api"
    APP_VERSION: str = "0.1.0"
    APP_INSTALLATION: str | None = None  # sitio o cliente de este deploy; si está, va a logs y trazas
    DEBUG: bool = False
    DOCS_ENABLED: bool = False  # /docs y /openapi.json; solo se enciende en desarrollo
    METRICS_ENABLED: bool = False  # /metrics; solo con Prometheus propio (ver exposing-prometheus-metrics)
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # En el entorno se escribe separada por comas: "invoices,reports"
    ENABLED_FEATURES: Annotated[list[str], NoDecode] = []

    # Credenciales y URLs: obligatorias y sin default, siempre desde .env o el entorno.
    DB_USER: str = Field(min_length=1)
    DB_PASSWORD: SecretStr = Field(min_length=1)
    DB_HOST: str = Field(min_length=1)
    DB_PORT: int = 5432
    DB_NAME: str = Field(min_length=1)
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0)
    DB_POOL_TIMEOUT: int = Field(default=10, ge=1)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=60)
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=15_000, ge=100)
    DB_ECHO: bool = False
    DB_DRIVER: Literal["asyncpg", "psycopg"] = "asyncpg"  # psycopg: variante síncrona
    DB_PGBOUNCER: bool = False  # True: la app va por PgBouncer en modo transaction
    # Migraciones: directo a Postgres. Solo se definen si DB_HOST/DB_PORT apuntan a PgBouncer.
    DB_MIGRATION_HOST: str | None = None
    DB_MIGRATION_PORT: int | None = None

    SECRET_KEY: SecretStr = Field(min_length=32)  # obligatoria: sin ella la app no arranca
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, ge=1)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=14, ge=1)
    COOKIE_SECURE: bool = True  # el refresh va en cookie solo por HTTPS; en dev local (http) se apaga
    CORS_ORIGINS: list[str] = []  # en el entorno, JSON: '["https://app.example.com"]'
    ERRORS_BASE_URL: str = Field(min_length=1)  # prefijo del campo "type" de problem+json
    OWNER_EMAIL: str | None = None  # solo para `python -m app.bootstrap` (primer usuario)
    OWNER_PASSWORD: SecretStr | None = None

    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None  # None = tracing apagado
    OTEL_EXPORTER_OTLP_INSECURE: bool = True  # False si el colector expone TLS
    OTEL_TRACES_SAMPLER_RATIO: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("ENABLED_FEATURES", mode="before")
    @classmethod
    def _split_features(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    # repr=False: la URL lleva la contraseña en claro y no debe aparecer en logs ni tracebacks.
    @computed_field(repr=False)  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        return self._url(self.DB_HOST, self.DB_PORT)

    # La URL de Alembic: cae en DATABASE_URL si no se definió un host o puerto propios.
    @computed_field(repr=False)  # type: ignore[prop-decorator]
    @property
    def MIGRATION_DATABASE_URL(self) -> str:
        return self._url(self.DB_MIGRATION_HOST or self.DB_HOST, self.DB_MIGRATION_PORT or self.DB_PORT)

    def _url(self, host: str, port: int) -> str:
        # URL.create escapa caracteres especiales de la contraseña
        return URL.create(
            f"postgresql+{self.DB_DRIVER}",
            username=self.DB_USER,
            password=self.DB_PASSWORD.get_secret_value(),
            host=host,
            port=port,
            database=self.DB_NAME,
        ).render_as_string(hide_password=False)

    @model_validator(mode="after")
    def _guard_production(self) -> Self:
        if self.APP_ENV in (Stage.STAGING, Stage.PROD):
            if self.DEBUG:
                raise ValueError("DEBUG must be false in staging/prod")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS cannot contain '*' in staging/prod")
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE must be true in staging/prod")
            if self.SECRET_KEY.get_secret_value().startswith(SECRET_PLACEHOLDERS):
                raise ValueError("SECRET_KEY is an example value: generate a real one")
        return self


@lru_cache
def get_settings() -> Settings:
    stage = os.getenv("APP_ENV", Stage.DEV.value)  # única lectura directa: decide qué archivo cargar
    if stage == Stage.TEST.value:
        return Settings(_env_file=None)  # los tests no leen ningún .env local: todo llega por entorno
    settings = Settings(_env_file=(ROOT_DIR / ".env", ROOT_DIR / f".env.{stage}"))  # el último gana
    if settings.APP_ENV.value != stage:  # APP_ENV escrita en un .env: no elige archivo, así que no se acepta
        raise RuntimeError(
            f"APP_ENV={settings.APP_ENV.value} comes from a .env file, but the stage (now: {stage}) "
            "is chosen by the real environment variable: export APP_ENV instead."
        )
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings)]
```

Uso en un endpoint:

```python
@router.get("/info")
async def info(settings: SettingsDep) -> dict[str, str]:
    return {"service": settings.APP_NAME, "version": settings.APP_VERSION}
```

Configuración distinta en un test: fixture `env` (en `tests/conftest.py` o en el módulo que la use). Limpia la caché antes y después, así el test siguiente no hereda la config; tras cada `env.setenv(...)` se vuelve a llamar a `get_settings.cache_clear()` y recién entonces `create_app()`. Alcanza a los errores y al tracing, no al engine (ver la regla de `get_settings()` arriba):

```python
from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """monkeypatch + cache_clear: la forma que documenta configuring-fastapi-settings."""
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


async def test_errors_follow_the_environment(env: pytest.MonkeyPatch) -> None:
    env.setenv("ERRORS_BASE_URL", "https://errors.other.invalid")
    get_settings.cache_clear()
    app = create_app()  # lee la config nueva
    ...
```

El entorno de los tests (`APP_ENV=test`, que no lee ningún `.env`, y todo lo obligatorio, incluido `DB_HOST=test-db.invalid`) se fija en el `conftest.py` de `testing-fastapi-endpoints`, antes de importar la app. No se repite acá: dos listas se desincronizan, y un `DB_HOST=localhost` apuntaría un test olvidadizo a una base real.

Archivos por stage. Este es el **único** `.env.example` del proyecto (`docker.md` y el resto remiten acá); lleva todas las claves de `Settings`, las opcionales comentadas:

```ini
# .env.example (versionado). Copiar a .env y completar.
# APP_ENV no se escribe acá: elige qué archivo se carga, así que va en el entorno real
# (export APP_ENV=staging). Sin ella el stage es dev.
# APP_ENV=dev

# Obligatoria y sin valor de ejemplo: la app no arranca hasta que la generes.
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
SECRET_KEY=

DB_USER=app
DB_PASSWORD=cambiar
DB_HOST=localhost
DB_PORT=5432
DB_NAME=app_db
ERRORS_BASE_URL=https://errors.example.com
CORS_ORIGINS=["http://localhost:5173"]
COOKIE_SECURE=false  # solo en desarrollo local (http)
DOCS_ENABLED=true  # /docs y /openapi.json: solo en desarrollo

# Opcionales (valores por defecto):
# APP_NAME=orders-api
# APP_VERSION=0.1.0
# APP_INSTALLATION=sucursal-centro  # etiqueta `installation` en logs y trazas; sin esto no se agrega
# DEBUG=false
# LOG_LEVEL=INFO
# ENABLED_FEATURES=invoices,reports
# DB_POOL_SIZE=5
# DB_MAX_OVERFLOW=5
# DB_POOL_TIMEOUT=10
# DB_POOL_RECYCLE=1800
# DB_STATEMENT_TIMEOUT_MS=15000
# DB_ECHO=false
# DB_DRIVER=asyncpg  # psycopg para la variante síncrona
# DB_PGBOUNCER=false  # true: la app va por PgBouncer (modo transaction)
# DB_MIGRATION_HOST=db  # Alembic directo a Postgres; con PgBouncer, DB_HOST apunta al pooler
# DB_MIGRATION_PORT=5432
# ACCESS_TOKEN_EXPIRE_MINUTES=15
# REFRESH_TOKEN_EXPIRE_DAYS=14
# METRICS_ENABLED=true  # solo con Prometheus propio
# Sin OTEL_EXPORTER_OTLP_ENDPOINT, tracing apagado. Dentro de compose va en `environment` del
# backend (docker.md); este valor es el de la app corriendo en el host:
# OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
# OTEL_EXPORTER_OTLP_INSECURE=true
# OTEL_TRACES_SAMPLER_RATIO=1.0
# OWNER_EMAIL=owner@example.com  # solo para `python -m app.bootstrap`
# OWNER_PASSWORD=

# No son de Settings: los leen otras piezas.
FRONTEND_API_PROXY_TARGET=http://localhost:8000  # proxy del dev server de Vite (building-axios-clients)
# GRAFANA_USER=admin  # solo con el stack de observabilidad en contenedores
# GRAFANA_PASSWORD=

# .env.staging / .env.prod NO se versionan: en esos entornos todo llega por variables del
# orquestador (Kubernetes Secret, ECS task definition, Docker secrets, Vault...).
```

## Checklist de verificación

- [ ] `grep -rn "os.getenv\|os.environ" app/` solo encuentra `get_settings()`.
- [ ] Arrancar con `APP_ENV=prod` sin `SECRET_KEY`, o con `DEBUG=true`, falla con un `ValidationError` legible.
- [ ] Todo secreto es `SecretStr` y `repr(get_settings())` no muestra ningún valor sensible (incluida `DATABASE_URL`).
- [ ] `.env.example` lista todas las claves de `Settings` (las opcionales, comentadas) y deja `SECRET_KEY` vacía. `.env*` reales están en `.gitignore` y `.dockerignore`.
- [ ] `APP_ENV=staging` escrita en un `.env` hace fallar `get_settings()` con un mensaje que pide exportarla.
- [ ] Los tests fijan `APP_ENV=test` y todo lo obligatorio por entorno (ver el `conftest.py` de `testing-fastapi-endpoints`). Con `APP_ENV=test` y un `.env` local con otro `LOG_LEVEL`, `get_settings().LOG_LEVEL` no cambia.
- [ ] Alembic ejecutado desde `backend/` encuentra el mismo `.env` que la app (los archivos se anclan a `ROOT_DIR`).
- [ ] Alembic (`env.py`: `MIGRATION_DATABASE_URL`), el seed y la telemetría usan `get_settings()`, no URLs propias.

## Skills relacionadas

- `layering-fastapi-apps`: dónde se inyecta `SettingsDep`.
- `configuring-sqlalchemy-sessions`: cómo `DATABASE_URL` y el pool consumen estos settings.
