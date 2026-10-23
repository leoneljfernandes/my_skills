---
name: scaffolding-fastapi-backends
description: Use when starting a new Python backend/API project (nuevo proyecto backend) or bootstrapping a full FastAPI + PostgreSQL stack end to end - project layout, auth/JWT/password hashing, Docker/docker-compose (backend, frontend, db), CircleCI/Coveralls - or when unsure in which order to build the pieces of a FastAPI service.
domain: backend
tags: [python, fastapi, postgresql, scaffolding, docker, ci, jwt, uv]
triggers: ["nuevo proyecto backend", "new FastAPI project", scaffold, bootstrap, "docker-compose", CircleCI, Coveralls, JWT, login, "registro de usuarios", "password hashing", Argon2, uv]
---

# Scaffolding de backends FastAPI

Skill orquestadora: fija el stack, el orden de construcción y los invariantes de un proyecto FastAPI + PostgreSQL nuevo. Cada paso delega en una skill especializada. Cada decisión tiene su **por qué**: si el proyecto lo contradice, la decisión no aplica y se discute con el usuario.

## Contexto y reglas

### Stack fijo

| Área | Decisión |
|---|---|
| Lenguaje / paquetes | Python 3.14+, **uv** (`pyproject.toml` + `uv.lock` versionado) |
| Web | FastAPI, Pydantic v2, pydantic-settings |
| Datos | PostgreSQL 16+ con SQLAlchemy **2.0** async (`asyncpg`) + Alembic. Fijar `sqlalchemy>=2.0,<2.1` mientras `opentelemetry-instrumentation-sqlalchemy` no soporte 2.1: con 2.1 el instrumentor se desactiva solo y se pierden los spans SQL |
| Auth | OAuth2 password flow + JWT (PyJWT), **Argon2** vía `pwdlib` → [security.md](references/security.md) |
| Tests | pytest + pytest-asyncio + httpx `AsyncClient`; SQLite en memoria por defecto, Postgres vía testcontainers en CI; rollback por test |
| Contenedores | un contenedor por pieza: `db`, `migrate`, `backend`, `frontend` + observabilidad → [docker.md](references/docker.md) |
| Observabilidad | Prometheus, Loki (logs JSON vía Alloy), Tempo (OpenTelemetry), Grafana + Alertmanager |
| CI / cobertura | CircleCI + Coveralls (lcov), JUnit → [ci.md](references/ci.md) |

### Orden de construcción

Cada paso termina en verde antes del siguiente. Para agregar una sola pieza a un proyecto existente, ir directo a su skill.

| # | Paso | Skill / referencia | Listo cuando |
|---|---|---|---|
| 1 | Config por stage | `configuring-fastapi-settings` | arrancar sin `SECRET_KEY` falla con error legible |
| 2 | Capas + errores | `layering-fastapi-apps`, `handling-fastapi-errors` | `uv run uvicorn app.main:app` arranca; `/health/live` = 200 |
| 3 | Engine y sesiones | `configuring-sqlalchemy-sessions` | `/health/ready` hace `SELECT 1` contra Postgres |
| 4 | Modelos + migraciones | `modeling-postgres-with-sqlalchemy`, `migrating-with-alembic` | `alembic upgrade head` + `alembic check` sin diferencias |
| 5 | Auth | [security.md](references/security.md) | *Authorize* de `/docs` obtiene token; endpoint protegido = 401 sin él |
| 6 | Tests | `unit-testing-fastapi-services`, `testing-fastapi-endpoints` | `uv run pytest` verde sin Postgres; `TEST_DB=postgres` verde con Docker |
| 7 | Docker | [docker.md](references/docker.md) | `docker compose up --build` levanta `db → migrate → backend → frontend` |
| 8 | Observabilidad | `exposing-prometheus-metrics`, `logging-json-to-loki`, `tracing-with-opentelemetry`, `defining-grafana-slos` | un log abre su traza, la traza abre sus logs, las alertas pasan `promtool test rules` |
| 9 | CI | [ci.md](references/ci.md) | pipeline sube cobertura y corre el round-trip de migraciones |

### Invariantes

- **Regla de dependencia**: `api → services → crud → models`. El SQL vive en `crud/`, las reglas y el `commit` en `services/`, HTTP solo en `api/`.
- **Una sola fuente de configuración**: `get_settings()`. Nadie más lee `os.environ`.
- **El esquema lo crean las migraciones**. `create_all` existe solo en los tests.
- **Secretos fuera del repo y de la imagen**: `.env` en `.gitignore` y `.dockerignore`; CI y orquestador los inyectan.
- **Infraestructura como código**: `monitoring/`, `docker-compose.yml`, `.circleci/` versionados. Clonar + `docker compose up` reproduce todo.
- **README documenta cada decisión con su por qué.**

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| Empezar por Docker/CI antes de tener la app verde local | se depuran tres capas a la vez | seguir el orden de la tabla |
| `Base.metadata.create_all()` en el `lifespan` | migraciones y esquema real divergen; autogenerate vacío | Alembic desde el día 1 |
| `requirements.txt` sin lock | builds no reproducibles | `uv.lock` + `uv sync --frozen` |
| Versiones distintas de Python en CI, Dockerfile y `requires-python` | "en CI pasa, en prod no" | la misma versión en los tres |
| Imágenes `:latest` en compose | el stack cambia solo entre deploys | tags fijos, actualizados a propósito |

## Ejemplos

`pyproject.toml` base (solo lo que se importa):

```toml
[project]
requires-python = ">=3.14"
dependencies = [
  "fastapi", "uvicorn[standard]", "pydantic", "pydantic-settings", "email-validator",
  "python-multipart",                                  # OAuth2PasswordRequestForm
  "sqlalchemy[asyncio]>=2.0.40,<2.1", "asyncpg", "alembic",
  "pyjwt", "pwdlib[argon2,bcrypt]",
  "prometheus-client", "prometheus-fastapi-instrumentator",
  "opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-grpc",
  "opentelemetry-instrumentation-fastapi", "opentelemetry-instrumentation-sqlalchemy",
]

[dependency-groups]
dev = [
  "pytest", "pytest-asyncio", "pytest-mock", "httpx", "aiosqlite",
  "polyfactory", "faker", "testcontainers[postgres]", "coverage", "ruff", "mypy",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
```

Bootstrap:

```bash
uv init --python 3.14 my-api && cd my-api
uv add fastapi "uvicorn[standard]" pydantic-settings "sqlalchemy[asyncio]>=2.0.40,<2.1" asyncpg alembic
uv add --dev pytest pytest-asyncio pytest-mock httpx aiosqlite polyfactory faker "testcontainers[postgres]" ruff mypy
uv run alembic init -t async alembic
```

## Checklist de verificación

- [ ] Cada fila de la tabla "Orden de construcción" cumple su criterio "Listo cuando".
- [ ] `uv run pytest`, `uv run mypy app` y `uv run ruff check` pasan.
- [ ] `docker compose up --build` desde un clon limpio levanta el stack completo sin pasos manuales (salvo crear `.env` desde `.env.example`).
- [ ] El README documenta stack, comandos, usuarios del seed y el por qué de cada decisión.

## Skills relacionadas

Todas las skills de `backend/`, `database/`, `testing/` y `observability/` de esta biblioteca. Para el frontend que consume esta API: `architecting-react-apps` y `building-axios-clients`.
