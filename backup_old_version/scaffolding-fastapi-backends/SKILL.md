---
name: scaffolding-fastapi-backends
description: Use when starting a new Python backend/API project (nuevo proyecto backend), or when adding to one any of - FastAPI layers, async SQLAlchemy + PostgreSQL, login/registro/JWT/password hashing, pytest E2E tests with a test database, Docker/docker-compose (backend, frontend, db), Alembic migrations, seed data, Prometheus/Grafana/Loki/Tempo monitoring, CircleCI or Coveralls.
---

# Scaffolding FastAPI backends

Blueprint de las decisiones de arquitectura de `notifications_challenge` (FastAPI + PostgreSQL), para replicarlas en proyectos nuevos. Cada decisión trae su **por qué**; si el proyecto nuevo contradice el por qué, la decisión no aplica y se discute con el usuario.

## Stack fijo

| Área | Decisión |
|---|---|
| Lenguaje / paquetes | Python 3.14+, **uv** (`pyproject.toml` + `uv.lock` versionado) |
| Web | FastAPI, Pydantic v2, pydantic-settings |
| Datos | PostgreSQL 16 + SQLAlchemy 2.0 **async** (`asyncpg`), Alembic |
| Auth | OAuth2 password flow + JWT (PyJWT, HS256), **Argon2** vía `pwdlib` |
| Tests | pytest E2E vía HTTP + SQLite **en memoria** (`aiosqlite` + `StaticPool`) |
| Contenedores | un contenedor por pieza: `db`, `migrate`, `backend`, `frontend`, + observabilidad |
| Observabilidad | Prometheus (métricas), Loki + Alloy (logs), Tempo + OpenTelemetry (trazas), Grafana |
| CI / cobertura | CircleCI + orb de Coveralls (lcov), resultados JUnit |

## Orden de construcción

Cada paso termina en verde antes de pasar al siguiente. Leé la referencia del paso al llegar a él.

1. **Capas y config** → [architecture.md](references/architecture.md). Listo cuando `uv run uvicorn app.main:app` arranca y `GET /` responde.
2. **Base de datos y migraciones** → [database.md](references/database.md). Listo cuando `alembic upgrade head` sobre una base vacía crea todo y `alembic check` no reporta diferencias.
3. **Auth y seguridad** → [security.md](references/security.md). Listo cuando el botón *Authorize* de `/docs` obtiene un token y un endpoint protegido responde 401 sin él.
4. **Tests E2E** → [testing.md](references/testing.md). Listo cuando `uv run pytest` pasa sin Postgres levantado y sin dejar archivos `.db`.
5. **Docker** → [docker.md](references/docker.md). Listo cuando `docker compose up --build` desde cero levanta `db` → `migrate` → `backend` → `frontend` y el seed carga con un comando.
6. **Observabilidad** → [observability.md](references/observability.md). Listo cuando el dashboard provisionado muestra tráfico, un log abre su traza y la traza abre sus logs.
7. **CI y cobertura** → [ci.md](references/ci.md). Listo cuando el pipeline sube cobertura a Coveralls y ambos badges están en el README.

Para agregar una sola pieza a un proyecto existente, saltá directo a su referencia.

## Invariantes (valen en todas las capas)

- **Regla de dependencia**: `api → services → crud → models`. Los routers solo traducen HTTP; el SQL vive en `crud/`; la lógica de negocio en `services/`.
- **Una sola fuente de configuración**: `app/config.py` (`Settings`). Alembic, seed, telemetría y la app la importan; nadie lee `os.environ` por su cuenta.
- **El esquema lo crean las migraciones**, nunca `create_all` en el `lifespan`. `create_all` existe solo en los tests.
- **Los secretos viven en `.env`** (no versionado, excluido de la imagen por `.dockerignore`); CI los inyecta como variables de entorno.
- **Toda la config de infraestructura está versionada** (`monitoring/`, `docker-compose.yml`, `.circleci/`): clonar + `docker compose up` reproduce el entorno completo.
- **README documenta cada decisión con su por qué**, igual que esta skill.

## Errores comunes

| Síntoma | Causa | Arreglo |
|---|---|---|
| `MissingGreenlet` al leer una relación | lazy loading en sesión async | `lazy="selectin"` en la relación, o `selectinload()` en la query |
| Autogenerate genera migración vacía | las tablas ya existían (`create_all`) o el modelo no está importado en `env.py` | base vacía + importar todos los módulos de `app/models` en `env.py`; `alembic stamp head` para adoptar una base existente |
| Tests ven datos de otro test / `no such table` | SQLite `:memory:` sin `StaticPool` (cada conexión es una base nueva) | `poolclass=StaticPool` + recrear esquema por test |
| `AttributeError: module 'app' has no attribute ...` en conftest | `import app.models.x` pisa la variable `app` (FastAPI) | `from app.models import x` |
| Test que espera `500` | error de dominio sin mapear | exception handler global → 400/422; un 500 es siempre un bug |
| CI verde pero local rojo (o al revés) | versión de Python de CI ≠ `requires-python` | misma versión en `cimg/python:X.Y`, Dockerfile y `pyproject.toml` |
| Bind mount sin permisos en Fedora/RHEL | SELinux | sufijo `:z` en volúmenes; `security_opt: [label=disable]` para el socket de Docker |
