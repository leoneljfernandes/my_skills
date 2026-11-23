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
| Datos | PostgreSQL 16+ con SQLAlchemy **2.0** async (`asyncpg`) + Alembic. Fijar `sqlalchemy[asyncio]>=2.0.40,<2.1` mientras `opentelemetry-instrumentation-sqlalchemy` no soporte 2.1: con 2.1 el instrumentor se desactiva solo y se pierden los spans SQL |
| Auth | OAuth2 password flow + JWT de acceso corto (PyJWT) y, para una SPA, refresh rotado en cookie `httpOnly`; **Argon2** vía `pwdlib` → [security.md](references/security.md) |
| Tests | pytest + pytest-asyncio + httpx `AsyncClient`; SQLite en memoria por defecto, Postgres vía testcontainers en CI; rollback por test |
| Contenedores | un contenedor por pieza: `db`, `migrate`, `backend`, `frontend` (+ observabilidad si va en contenedores propios) → [docker.md](references/docker.md) |
| Observabilidad | Con contenedores propios: Prometheus, Loki (logs JSON vía Alloy), Tempo (OpenTelemetry), Grafana + Alertmanager. En una plataforma que trae su monitoreo: logs JSON a stdout y lo nativo de la plataforma |
| CI / cobertura | CircleCI + Coveralls (lcov), JUnit → [ci.md](references/ci.md). Si no hay CI, `pytest` y `TEST_DB=postgres pytest` son pasos obligatorios antes de integrar |

### Orden de construcción

Cada paso termina en verde antes del siguiente. Para agregar una sola pieza a un proyecto existente, ir directo a su skill.

| # | Paso | Skill / referencia | Listo cuando |
|---|---|---|---|
| 1 | Config por stage | `configuring-fastapi-settings` | arrancar sin `SECRET_KEY` falla con error legible |
| 2 | Capas + errores | `layering-fastapi-apps`, `handling-fastapi-errors`; de `tracing-with-opentelemetry`, solo el módulo `tracing.py` en modo mínimo (`current_trace_id()` necesita solo `opentelemetry-api`) | `uv run uvicorn app.main:app` arranca con `health.py` + `errors.py` + `main.py` **sin** las líneas `# paso N` (sin `api_router` ni `deps.py`: `deps.py` nace en el paso 3 con `HealthRepoDep` y `api_router` llega en el paso 4 con el primer recurso), sin base, sin SDK de OpenTelemetry ni Prometheus; `/health/live` = 200 |
| 3 | Engine y sesiones | `configuring-sqlalchemy-sessions`. Postgres local: `docker compose up -d db` (solo el servicio `db` de [docker.md](references/docker.md)) | `/health/ready` hace `SELECT 1` contra Postgres (las líneas `# paso 3` de `layering-fastapi-apps`) |
| 4 | Modelos + migraciones | `modeling-postgres-with-sqlalchemy`, `migrating-with-alembic` | `alembic upgrade head` + `alembic check` sin diferencias |
| 5 | Auth | [security.md](references/security.md) | *Authorize* de `/docs` obtiene token; endpoint protegido = 401 sin él |
| 6 | Tests | `unit-testing-fastapi-services`, `testing-fastapi-endpoints` | `uv run pytest` verde sin Postgres; `TEST_DB=postgres` verde con Docker |
| 7 | Frontend | `choosing-ssr-or-spa` (por defecto, SPA en data mode), `architecting-react-apps`, `routing-with-react-router`, `building-axios-clients`, `handling-react-errors` | `npm run build` genera `dist/`, y el login + refresh funcionan contra el backend por el proxy de Vite |
| 8 | Docker | [docker.md](references/docker.md) | `docker compose up --build` levanta `db → migrate → backend → frontend` |
| 9 | Observabilidad | **Si el despliegue usa contenedores propios**: las 4 skills de `observability/`. **Si va a Vercel**: logs JSON (`logging-json-to-loki`, sin el envío a Loki; el `tracing.py` mínimo del paso 2 ya alcanza para el `trace_id`) y `vercel-index` | contenedores propios: un log abre su traza, la traza abre sus logs, las alertas pasan `promtool test rules`. Vercel: los logs son JSON por línea y el backend arranca sin colector |
| 10 | CI | [ci.md](references/ci.md) | el pipeline corre `lint` (ruff, mypy, capas), los tests en SQLite y en Postgres (`test-postgres`, siempre), sube cobertura y corre el round-trip de migraciones. **Si todavía no hay CI**: queda como paso posterior declarado en el README, con `TEST_DB=postgres pytest` como paso obligatorio mientras tanto |

### Invariantes

- **Regla de dependencia**: `api → services → crud → models`. El SQL vive en `crud/`, las reglas y el `commit` en `services/`, HTTP solo en `api/`.
- **Una sola fuente de configuración**: `get_settings()`. Nadie más lee `os.environ`.
- **El esquema lo crean las migraciones**. `create_all` existe solo en los tests.
- **Secretos fuera del repo y de la imagen**: `.env` en `.gitignore` y `.dockerignore`; CI y orquestador los inyectan.
- **Infraestructura como código**: `docker-compose.yml` versionado; `monitoring/` y `.circleci/` también, cuando existen. Clonar + `docker compose up` reproduce todo lo que el proyecto declaró.
- **README documenta cada decisión con su por qué.**

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| Empezar por Docker/CI antes de tener la app verde local | se depuran tres capas a la vez | seguir el orden de la tabla. La base en contenedor (`docker compose up -d db`) sí se levanta desde el paso 3: lo que espera al paso 8 es la imagen de la app y el stack completo |
| `Base.metadata.create_all()` en el `lifespan` | migraciones y esquema real divergen; autogenerate vacío | Alembic desde el día 1 |
| `requirements.txt` sin lock | builds no reproducibles | `uv.lock` + `uv sync --locked` (con `--frozen`, un lock viejo no falla) |
| Versiones distintas de Python en CI, Dockerfile y `requires-python` | "en CI pasa, en prod no" | la misma versión en los tres |
| Imágenes `:latest` en compose | el stack cambia solo entre deploys | tags fijos, actualizados a propósito |

## Ejemplos

`pyproject.toml` base: **la única lista de dependencias** (solo lo que se importa). `name` y `version` son obligatorios para `uv lock`:

```toml
[project]
name = "my-api"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
  "fastapi", "uvicorn[standard]", "pydantic", "pydantic-settings", "email-validator",
  "python-multipart",                                  # OAuth2PasswordRequestForm
  "sqlalchemy[asyncio]>=2.0.40,<2.1", "asyncpg", "alembic",
  "pyjwt", "pwdlib[argon2]",                           # + bcrypt solo si hay hashes heredados
  "prometheus-client", "prometheus-fastapi-instrumentator",
  "opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-grpc",
  "opentelemetry-instrumentation-fastapi", "opentelemetry-instrumentation-sqlalchemy",
  # Solo si hay llamadas salientes (HTTPXClientInstrumentor). El instrumentor importa httpx, así que van
  # juntos en prod; si no hay llamadas salientes, se quitan los dos de acá y de setup_tracing.
  "httpx", "opentelemetry-instrumentation-httpx",
  # "gunicorn", "uvicorn-worker",                        # solo con varios workers: descomentar (ver exposing-prometheus-metrics)
]

[dependency-groups]
dev = [
  "pytest", "pytest-asyncio", "pytest-mock", "aiosqlite",  # httpx (AsyncClient de los tests) ya está en dependencies
  "pytest-randomly", "testcontainers[postgres]", "coverage", "ruff", "mypy", "import-linter",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]  # `app` y `tests` importables con `uv run pytest`, sin PYTHONPATH ni instalar el paquete
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
filterwarnings = ["error::sqlalchemy.exc.SAWarning"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
mypy_path = "."                # `tests.factories` se resuelve igual que con `pythonpath` de pytest
explicit_package_bases = true  # `tests/` sin __init__.py: el módulo es `tests.x`, no `x` (mypy app tests)

[tool.ruff]
line-length = 110
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "ASYNC"]

# Las capas se hacen cumplir (la explicación está en layering-fastapi-apps).
[tool.importlinter]
root_package = "app"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Capas: api -> services -> crud -> models"
type = "layers"
layers = ["app.api", "app.services", "app.crud", "app.models"]

[[tool.importlinter.contracts]]
name = "Services y crud no conocen HTTP"
type = "forbidden"
source_modules = ["app.services", "app.crud"]
forbidden_modules = ["fastapi"]
allow_indirect_imports = true  # errors.py y config.py usan FastAPI; lo que se prohíbe es el import directo

[[tool.importlinter.contracts]]
name = "Solo api/deps.py compone repositorios y sesión"
type = "forbidden"
source_modules = ["app.api"]
forbidden_modules = ["app.crud", "app.database"]
allow_indirect_imports = true
ignore_imports = ["app.api.deps -> app.crud.*", "app.api.deps -> app.database"]
```

Bootstrap:

```bash
uv init --bare --python 3.14 backend && cd backend   # --bare: solo pyproject.toml, sin src/ ni build-system
uv python pin 3.14   # crea .python-version: el intérprete que usan uv local y el job test-postgres (machine)
# Reemplazar pyproject.toml por el bloque de arriba (una sola lista: sin `uv add`) y resolver todo:
uv sync
mkdir -p app tests && touch app/__init__.py   # `app/` en la raíz del backend; `tests/` sin __init__.py: lo importa `pythonpath`
uv run alembic init -t async alembic
```

## Checklist de verificación

- [ ] Cada fila de la tabla "Orden de construcción" cumple su criterio "Listo cuando".
- [ ] `uv run pytest`, `uv run mypy app tests`, `uv run ruff check` y `uv run lint-imports` pasan (en CI, el job `lint`).
- [ ] En desarrollo, `docker compose up --build` desde un clon limpio levanta el stack declarado sin pasos manuales (salvo crear `.env` desde `.env.example` y correr el bootstrap del primer usuario). En producción el `.env` no sale de `.env.example` (ver [docker.md](references/docker.md)).
- [ ] El README documenta stack, comandos, usuarios del seed y el por qué de cada decisión.

## Skills relacionadas

Todas las skills de `backend/`, `database/`, `testing/` y `observability/` de esta biblioteca. Para el frontend que consume esta API (paso 7): `choosing-ssr-or-spa`, `architecting-react-apps`, `routing-with-react-router`, `building-axios-clients` y `handling-react-errors`.
