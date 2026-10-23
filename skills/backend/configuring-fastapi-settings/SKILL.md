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
- Elegir el stage con `APP_ENV` (`dev | test | staging | prod`). Los archivos se cargan en cascada: `.env` → `.env.<stage>`, y **las variables de entorno reales ganan siempre**. En contenedores y CI la config llega por entorno; los `.env` son solo para desarrollo.
- `SecretStr` para todo secreto: no aparece en `repr`, en logs ni en tracebacks. Se lee con `.get_secret_value()` solo en el punto de uso.
- Secretos obligatorios **sin default** (`SECRET_KEY: SecretStr = Field(min_length=32)`): sin ellos la app no arranca.
- Un `@model_validator(mode="after")` aplica guardas de producción: `DEBUG` apagado, CORS sin `*`, sin contraseñas de desarrollo.
- `get_settings()` con `@lru_cache`: se construye una vez y se inyecta con `Depends(get_settings)`. Los tests lo sobreescriben con `app.dependency_overrides` o `get_settings.cache_clear()`.
- `frozen=True`: la config es inmutable en runtime.
- Versionar `.env.example` con todas las claves y valores ficticios. `.env*` reales van en `.gitignore` y `.dockerignore`.

**Evitar (anti-patrones)**

| Anti-patrón | Por qué es un problema | En su lugar |
|---|---|---|
| `os.getenv("X")` disperso por el código | config invisible, sin validación, `None` silencioso | campo tipado en `Settings` |
| `X: str = os.getenv("X", "...")` dentro de la clase | se evalúa al importar e ignora `env_file` | default literal; pydantic-settings lee el entorno |
| `if ENV == "prod":` repartido por la app | lógica de entorno acoplada al dominio | flags explícitos en `Settings` (`DOCS_ENABLED`, `OTEL_...`) |
| Default de desarrollo para secretos (`SECRET_KEY="changeme"`) | prod arranca "funcionando" con un secreto público | campo obligatorio + validador de stage |
| `.env.prod` versionado con secretos | filtración permanente en el historial git | gestor de secretos / variables del orquestador |
| `str` para contraseñas | aparecen en logs y en errores de validación | `SecretStr` |
| Leer settings en import-time de módulos de dominio | imposible de sobreescribir en tests | inyectar `Settings` o llamar `get_settings()` en el punto de uso |

## Ejemplos

`app/config.py` (verificado con mypy `--strict` y pytest):

```python
import os
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self

from fastapi import Depends
from pydantic import Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Stage(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class Settings(BaseSettings):
    # Prioridad (mayor a menor): variables de entorno > .env.<stage> > .env > defaults.
    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore", frozen=True)

    APP_ENV: Stage = Stage.DEV
    APP_NAME: str = "orders-api"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    DB_USER: str = "postgres"
    DB_PASSWORD: SecretStr = SecretStr("postgres")
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "app_db"
    DB_POOL_SIZE: int = Field(default=10, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)

    SECRET_KEY: SecretStr = Field(min_length=32)  # obligatoria: sin ella la app no arranca
    CORS_ORIGINS: list[str] = []                   # en el entorno, JSON: '["https://app.example.com"]'

    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None  # None = tracing apagado
    OTEL_TRACES_SAMPLER_RATIO: float = Field(default=1.0, ge=0.0, le=1.0)

    @computed_field  # type: ignore[prop-decorator]
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

    @property
    def is_prod(self) -> bool:
        return self.APP_ENV is Stage.PROD

    @model_validator(mode="after")
    def _guard_production(self) -> Self:
        if self.APP_ENV in (Stage.STAGING, Stage.PROD):
            if self.DEBUG:
                raise ValueError("DEBUG must be false in staging/prod")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS cannot contain '*' in staging/prod")
            if self.DB_PASSWORD.get_secret_value() == "postgres":
                raise ValueError("DB_PASSWORD uses the development default")
        return self


@lru_cache
def get_settings() -> Settings:
    stage = os.getenv("APP_ENV", Stage.DEV.value)  # única lectura directa: decide qué archivo cargar
    return Settings(_env_file=(".env", f".env.{stage}"))  # el último archivo gana


SettingsDep = Annotated[Settings, Depends(get_settings)]
```

Uso en un endpoint y override en tests:

```python
@router.get("/info")
async def info(settings: SettingsDep) -> dict[str, str]:
    return {"service": settings.APP_NAME, "version": settings.APP_VERSION}


# tests/conftest.py: antes de importar la app
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-32b+")
```

Archivos por stage:

```ini
# .env.example (versionado). Copiar a .env y completar.
APP_ENV=dev
SECRET_KEY=generar-con: python -c "import secrets; print(secrets.token_urlsafe(32))"
DB_PASSWORD=cambiar
CORS_ORIGINS=["http://localhost:5173"]

# .env.staging / .env.prod NO se versionan: en esos entornos todo llega por variables del
# orquestador (Kubernetes Secret, ECS task definition, Docker secrets, Vault...).
```

## Checklist de verificación

- [ ] `grep -rn "os.getenv\|os.environ" app/` solo encuentra `get_settings()`.
- [ ] Arrancar con `APP_ENV=prod` sin `SECRET_KEY`, o con `DEBUG=true`, falla con un `ValidationError` legible.
- [ ] Todo secreto es `SecretStr` y `repr(get_settings())` no muestra ningún valor sensible.
- [ ] `.env.example` lista todas las claves. `.env*` reales están en `.gitignore` y `.dockerignore`.
- [ ] Los tests fijan `APP_ENV=test` y no dependen de un `.env` local.
- [ ] Alembic (`env.py`), el seed y la telemetría usan `get_settings()`, no URLs propias.

## Skills relacionadas

- `layering-fastapi-apps`: dónde se inyecta `SettingsDep`.
- `configuring-sqlalchemy-sessions`: cómo `DATABASE_URL` y el pool consumen estos settings.
