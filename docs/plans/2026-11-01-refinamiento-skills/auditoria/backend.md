# Auditoría de la rama BACKEND

**Fecha:** 2026-11-01. **Commit auditado:** `54d8c96`. **Alcance:** `configuring-fastapi-settings`, `handling-fastapi-errors`, `layering-fastapi-apps`, `scaffolding-fastapi-backends` y sus `references/{security,docker,ci}.md`, más los contratos con otros dominios.

## Cómo se comprobó

Se armó un backend de referencia **solo con los bloques publicados**, más el pegamento mínimo marcado `GLUE` donde una skill no publica la pieza. Está en `/tmp/claude-1000/-home-leonel-my-skills/927a91bb-bc0d-4938-a40b-4a8225428464/scratchpad/audit/backend/` (`build.py`, `add_auth.py`, `add_docker.py`, `exp_settings.py`, `exp_runtime.py`, `exp_parse.py`, `proj/`). El repo no se tocó (`git status` limpio).

Versiones resueltas por `uv` el 2026-11-01: Python 3.14, FastAPI 0.162.0, Starlette 1.10.0, pydantic 2.14.2, pydantic-settings 2.16.2, SQLAlchemy 2.0.55, alembic 1.20.1, asyncpg 0.32.0, pwdlib 0.3.1, PyJWT 2.15.1, opentelemetry-sdk 1.45.2, opentelemetry-instrumentation-sqlalchemy 0.66b2, testcontainers 4.15.0, import-linter 2.15, uv 0.12.24.

### Lo que se comprobó y funciona (no son hallazgos)

| Qué | Resultado |
|---|---|
| Tests de `tests/snippets/test_python_snippets.py` y `validate_skills.py` | 7/7 y 0 errores |
| `mypy` (strict por pyproject) sobre la app armada, incluido `config.py` | sin errores |
| `lint-imports` con el bloque de `layering` | 2 contratos KEPT |
| Flujo de órdenes y formato de errores 404/422/regla de negocio, en SQLite y con `TEST_DB=postgres` (testcontainers real) | 4/4 en ambos, una vez corregida la línea rota de `testing:116` |
| Bloques de `security.md`: login, cookie `HttpOnly`/`SameSite=strict`/`Path`, 401 con código estable y desafío, refresh rotado, revocación tras `REUSE_GRACE` | pasan (salvo BE-08) |
| Trazas: `trace_id` en la respuesta 500 y en el log, y el 500 no filtra el mensaje interno | correcto, con `setup_tracing` real |
| Stack `docker-compose.yml` + `Dockerfile` + `env.py`: `db` → `migrate` → `backend` contra Postgres real | levanta; responde problem+json |
| `alembic` desde `backend/` con `.env` en la raíz | encuentra la config |
| `nginx -t`, proxy `/api`, fallback de SPA, `limit_req` | correctos |
| Tags `uv:0.12`, `cimg/python:3.14`, `cimg/postgres:16.4`, `nginx:1.27-alpine`, `postgres:16-alpine`, `python:3.14-slim`, `node:22-alpine` y orb `coveralls@2.2.5` | existen |
| Contrato `Settings` ↔ otras skills | todos los campos leídos existen, también los de `security.md` |
| Endpoints y forma del token ↔ `building-axios-clients` | coinciden (`/auth/token`, `/auth/refresh`, `/auth/me`, `access_token`, `errors[].loc`) |

---

## Hallazgos

### BE-01: `uv run pytest` falla con `ModuleNotFoundError: No module named 'app'`
- **Severidad:** alta
- **Tipo:** c
- **Evidencia:**
  - `skills/backend/scaffolding-fastapi-backends/SKILL.md:86-90`: `[tool.pytest.ini_options]` con `testpaths`, `asyncio_mode` y los dos loop scopes; **sin `pythonpath`**.
  - `skills/backend/scaffolding-fastapi-backends/SKILL.md:39`: "`uv run pytest` verde sin Postgres". También `:109`.
  - `skills/testing/testing-fastapi-endpoints/SKILL.md:51-57` (mismo vacío), `:262` `uv run pytest -q`, `:269`, y `:84` `from app.main import app`.
  - `skills/backend/scaffolding-fastapi-backends/references/ci.md:52`: `PYTHONPATH: "."`. CI tapa el problema; local no.
  - Divergencia adicional: `testing:56` agrega `filterwarnings = ["error::sqlalchemy.exc.SAWarning"]`, que `scaffolding:86-90` no tiene.
- **Confirmación:** ejecutado. Con el pyproject publicado, `uv run pytest` da `tests/conftest.py:22: ModuleNotFoundError: No module named 'app'`. `PYTHONPATH=. uv run pytest` y `uv run coverage run -m pytest` pasan 4/4 (`-m` agrega el cwd). `uv init` no crea build-system, así que el proyecto no se instala.
- **Impacto:** el criterio del paso 6 falla en el primer intento y el agente improvisa (`__init__.py`, instalar el paquete o `PYTHONPATH`), cada vez distinto.
- **Plan de corrección:** canónico: `pythonpath = ["."]` en pyproject, porque vale local y en CI.
  - `scaffolding/SKILL.md:86-90` y `testing/SKILL.md:51-57`: agregar `pythonpath = ["."]`.
  - Dejar los dos bloques idénticos, incluido `filterwarnings` (pasa con la app armada).
  - `ci.md:52`: quitar `PYTHONPATH`.
  - Verificación: test en `tests/snippets/` que compare ambas tablas `[tool.pytest.ini_options]`; `uv run pytest` en un clon limpio.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** testing (mismo bloque).

### BE-02: el bootstrap de `scaffolding` no instala lo que el `pyproject` de la misma skill declara
- **Severidad:** alta
- **Tipo:** a
- **Evidencia:**
  - `scaffolding/SKILL.md:71-77`: `"email-validator"`, `"python-multipart"`, `"pyjwt", "pwdlib[argon2]"`, `"prometheus-client", "prometheus-fastapi-instrumentator"`, `"opentelemetry-sdk"`…; `:83`: `"coverage"`.
  - `scaffolding/SKILL.md:101-102`: `uv add fastapi "uvicorn[standard]" pydantic-settings "sqlalchemy[asyncio]>=2.0.40,<2.1" asyncpg alembic` y `uv add --dev pytest pytest-asyncio pytest-mock pytest-randomly httpx aiosqlite "testcontainers[postgres]" ruff mypy import-linter`.
  - `layering/SKILL.md:77`: `EmailStr`. `ci.md:61` y `testing:264`: `uv run coverage`.
  - `scaffolding/SKILL.md:68-69`: el bloque "`pyproject.toml` base" no tiene `name`.
- **Confirmación:** ejecutado. Tras el bootstrap literal faltan `email_validator`, `multipart`, `jwt`, `pwdlib`, `prometheus_client`, `prometheus_fastapi_instrumentator`, `opentelemetry.sdk`, `opentelemetry.instrumentation.fastapi` y `coverage`. El `EmailStr` da `ImportError: email-validator is not installed`. `uv run coverage` da `No such file or directory`. El pyproject copiado tal cual da `the required project.name field is not set` en `uv lock`.
- **Impacto:** quien sigue "Bootstrap" rompe en el primer schema del paso 2; quien copia el pyproject, en el primer `uv lock`.
- **Plan de corrección:** canónico: el bloque `pyproject.toml`, que es el que el texto justifica línea por línea.
  - Reescribir el bootstrap: `uv init --python 3.14 my-api && cd my-api`, reemplazar el pyproject por el bloque y `uv sync`.
  - O bien agregar los paquetes faltantes a los dos `uv add`.
  - Agregar `name` y `version` al bloque.
  - Verificación: test que compare los paquetes de `uv add` con los del pyproject.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** testing y observability (dependencias que asumen instaladas).

### BE-03: el orden de construcción no se puede cumplir, porque el paso 2 importa código de los pasos 3 y 8
- **Severidad:** media
- **Tipo:** a, c
- **Evidencia:**
  - `scaffolding/SKILL.md:30`: "Cada paso termina en verde antes del siguiente."
  - `scaffolding/SKILL.md:35`: paso 2, "`uv run uvicorn app.main:app` arranca".
  - `handling/SKILL.md:66`: `from app.observability.tracing import current_trace_id`.
  - `layering/SKILL.md:205`: `configure_logging(settings)`; `:216`: `setup_metrics(app)`; `:217`: `setup_tracing(app, engine, settings)`.
  - `scaffolding/SKILL.md:36` (engine, paso 3) y `:41` (observabilidad, paso 8).
- **Confirmación:** ejecutado. Sin `app/observability` ni `app/database.py`: `import app.errors` da `ModuleNotFoundError: No module named 'app.observability'`, e `import app.main` da `No module named 'app.database'`.
- **Impacto:** el agente adelanta el paso 8 o inventa stubs distintos en cada proyecto. Además, `main.py` llama a `setup_metrics` sin condición, aunque `exposing-prometheus-metrics:15` aplica solo con contenedores propios y `scaffolding:41` lo saltea en Vercel.
- **Plan de corrección:** canónico: el orden de `scaffolding`.
  - `scaffolding:35`: el paso 2 crea `app/observability/tracing.py` en "modo mínimo" (`tracing:17`, solo `current_trace_id`/`current_span_id`).
  - `layering:202-223`: publicar un `create_app` mínimo (handlers, CORS, routers, health) y marcar qué línea suma cada paso.
  - `setup_metrics` condicionado al despliegue.
  - Verificación: un test arma `app` por pasos e importa `app.main` en cada uno.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** observability (`tracing:17` pasa a ser el punto de entrada del paso 2).

### BE-04: `uv sync --frozen` no falla con un lock desactualizado, al revés de lo que afirman dos referencias
- **Severidad:** media
- **Tipo:** d
- **Evidencia:**
  - `references/docker.md:68`: "`--frozen`: instala exactamente `uv.lock`; si el lock está desactualizado, el build falla."
  - `references/ci.md:120`: "`uv sync --frozen`: CI instala exactamente el lock; un `uv.lock` desactualizado rompe el build en vez de instalar otra cosa."
  - `scaffolding/SKILL.md:59`: "`uv.lock` + `uv sync --frozen`".
- **Confirmación:** ejecutado con uv 0.12.24. Se agregó `certifi` al pyproject sin regenerar el lock. `uv sync --frozen` sale con 0 y `certifi` queda sin instalar. `uv sync --locked` sale con 1 y sugiere `uv lock`.
- **Impacto:** CI y la imagen aceptan en silencio un lock viejo: un PR agrega una dependencia sin lockearla, el build pasa y la app rompe al importar. Es justo lo que el texto dice evitar.
- **Plan de corrección:** canónico: la intención del texto; se cambia el flag.
  - `ci.md:41` y `docker.md:50`: `--locked`.
  - Actualizar `ci.md:120`, `docker.md:68` y `scaffolding:59`.
  - Verificación: repetir el experimento y hacer `docker build` con `--locked`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### BE-05: un recurso ajeno da 404 según una skill y 403 según otra
- **Severidad:** media
- **Tipo:** b
- **Evidencia:**
  - `handling/SKILL.md:41`: "Recurso inexistente o ajeno sin permiso de ver | `NotFoundError` | 404".
  - `references/security.md:235`: "Ownership | 404 si no existe, 403 si no es del usuario".
  - `references/security.md:247`: "recurso ajeno (403)".
- **Confirmación:** por lectura.
- **Impacto:** un agente hace 404 y otro 403. El test obligatorio de `security.md` contradice a la tabla de errores. Con 403, se distingue un id existente de uno inexistente y se pueden enumerar recursos.
- **Plan de corrección:** recomendado como canónico: `handling` (no revela existencia).
  - `security.md:235`: "404 si no existe o el usuario no puede verlo; 403 si puede verlo pero no tiene permiso para esa acción".
  - `security.md:247`: "recurso ajeno (404); acción sin permiso sobre recurso visible (403)".
  - Verificación: tests de auth de la app de referencia.
- **Decisión requerida:** ¿recurso ajeno = 404 (recomendado) o 403?
- **Otros dominios afectados:** frontend (`kind: not_found` en vez de `forbidden`); testing (la matriz de `testing:28` no cambia).

### BE-06: `APP_ENV` en `.env` no elige el stage, aunque `.env.example` lo pone ahí
- **Severidad:** media
- **Tipo:** a
- **Evidencia:**
  - `configuring/SKILL.md:18`: "Elegir el stage con `APP_ENV`… Los archivos se cargan en cascada: `.env` → `.env.<stage>`".
  - `configuring/SKILL.md:20`: "Si `APP_ENV=test`, `get_settings()` no lee ningún `.env`".
  - `configuring/SKILL.md:150`: `stage = os.getenv("APP_ENV", Stage.DEV.value)`, que solo mira el entorno real.
  - `configuring/SKILL.md:183`: `.env.example` trae `APP_ENV=dev`.
- **Confirmación:** ejecutado (`exp_settings.py`):
  - A: `.env` con `APP_ENV=staging` + `.env.staging` con `LOG_LEVEL=DEBUG` → `APP_ENV=staging`, `LOG_LEVEL=INFO` (no carga `.env.staging`).
  - B: `.env` con `APP_ENV=test` y `LOG_LEVEL=DEBUG` → `APP_ENV=test`, `LOG_LEVEL=DEBUG` (sí lee el `.env`, contra la regla).
  - C: `.env` con `APP_ENV=prod` + `.env.dev` → `APP_ENV=prod` con los valores de `.env.dev` aplicados.
- **Impacto:** el mismo `.env` se comporta distinto en el host y en compose, donde `env_file` lo vuelve entorno real. El agente cambia `APP_ENV` en `.env` y ve un stage que anuncia una cosa y una config que dice otra.
- **Plan de corrección:** recomendado: mantener la lectura real y fallar rápido ante la divergencia.
  - `configuring:150-153`: tras construir, si `settings.APP_ENV.value != stage`, lanzar un error legible ("exportá APP_ENV en el entorno; en `.env` no elige archivo").
  - `configuring:18`: aclarar que el stage sale del entorno real.
  - `configuring:183`: dejar `APP_ENV` comentado.
  - Verificación: casos A, B y C como tests en `test_python_snippets.py`.
- **Decisión requerida:** ¿fallar ante la divergencia (recomendado) o leer `APP_ENV` también desde `.env` con `dotenv_values`?
- **Otros dominios afectados:** testing no (fija `APP_ENV` por entorno).

### BE-07: `lifespan`, `/health/live`, `/health/ready` async, `service.get` y `OrderRepository` se usan o exigen, pero ninguna skill los publica
- **Severidad:** media
- **Tipo:** c, e
- **Evidencia:**
  - `layering/SKILL.md:207`: `lifespan=lifespan`; `:17`: "main.py … lifespan".
  - `database/configuring-sqlalchemy-sessions/SKILL.md:18,153`: "`lifespan` llama a `engine.dispose()`"; `observability/tracing-with-opentelemetry/SKILL.md:23,40`: "`shutdown_tracing()` en el `lifespan`". Un `grep` de `def lifespan` en `skills/` no devuelve nada.
  - `scaffolding/SKILL.md:35-36` exige `/health/live` y `/health/ready`. `layering:202-223` no monta ningún router de salud. El único ejemplo es la variante **síncrona** (`sessions:127-129`).
  - `layering/SKILL.md:68`: "Flujo completo de un caso de uso"; `:197` llama a `service.get(order_id)`, ausente de `OrderService` (`:144-170`). `OrderRepository` no se publica, aunque `unit-testing:60` importa `app.crud.order`.
- **Confirmación:** ejecutado: grep, y armar la app requirió escribir ese pegamento (`GLUE` en `proj/backend/app/main.py`, `services/order.py`, `crud/order.py`).
- **Impacto:** dos skills piden cosas al `lifespan` sin un lugar común: cada agente lo escribe y es fácil olvidar el `dispose` o el `shutdown` (se pierden spans). `/health/live` queda sin ruta definida.
- **Plan de corrección:** canónico: `layering`, dueño de `main.py`.
  - Agregar a `layering` el bloque de `lifespan` con `shutdown_tracing()` y `engine.dispose()`.
  - Agregar el router de salud async y `include_router`.
  - Completar `OrderService.get` y `OrderRepository`.
  - `sessions` y `tracing` remiten a ese bloque.
  - Verificación: test que extraiga `main.py` y lo importe.
- **Decisión requerida:** ¿salud en `/health/*` (recomendado, fuera de `/api/v1`, lo que usa un orquestador) o en `/api/v1/health` (`sessions:25` admite ambos)?
- **Otros dominios afectados:** database y observability (referencias al bloque).

### BE-08: `require_permission` lee `user.role`, que con la regla `lazy="raise"` revienta con 500
- **Severidad:** media
- **Tipo:** c
- **Evidencia:**
  - `references/security.md:197`: `if permission not in user.role.permissions:`.
  - `references/security.md:152`: `user = await self._users.get(user_id) if user_id is not None else None`.
  - `database/modeling-postgres-with-sqlalchemy/SKILL.md:24`: "Relaciones con `lazy="raise"`…"; `:61`: `lazy="select"` en async da `MissingGreenlet`.
  - `layering/SKILL.md:125-126`: patrón de `get` con `session.get` sin opciones de carga.
- **Confirmación:** ejecutado, con `User`, `Role` y `UserRepository` de pegamento (no se publican) que siguen esos patrones. `GET` protegido por permiso: `sqlalchemy.exc.InvalidRequestError: 'User.role' is not available due to lazy='raise'`.
- **Impacto:** todo endpoint con `require_permission` da 500 en vez de 200/403, salvo que el agente descubra que debe cargar el rol.
- **Plan de corrección:** canónico: la regla de `modeling` (`lazy="raise"`).
  - `security.md`: publicar `UserRepository.get_with_role` con `select(User).options(joinedload(User.role))`.
  - Usarlo en `user_from_token`, o guardar los permisos en el access token.
  - Verificación: test "permiso concedido = 200, faltante = 403" con la sesión limpia (`expire_all`).
- **Decisión requerida:** ninguna, salvo que se prefiera llevar los permisos en el JWT (no recomendado: un cambio de rol tardaría hasta 15 min).
- **Otros dominios afectados:** database (sin cambios).

### BE-09: la "gracia" de `REUSE_GRACE` no evita que la segunda pestaña caiga en login
- **Severidad:** media
- **Tipo:** c
- **Evidencia:**
  - `references/security.md:106-107`: "Reusar un token recién rotado es normal con dos pestañas que renuevan a la vez o una respuesta de refresh perdida: dentro de esta ventana no se lo trata como robo."
  - `references/security.md:136-141`: dentro de la gracia igual `raise NotAuthenticatedError("Invalid session")`.
  - `frontend/building-axios-clients/SKILL.md:218-221`: `.catch(… tokens.setAccessToken(null); onSessionExpired(); throw new SessionExpiredError(…))`.
  - `building-axios-clients:325-329`: `onSessionExpired` redirige a `/login`. El single-flight de `:19` es por pestaña.
- **Confirmación:** backend ejecutado: reuso en gracia = 401 `not_authenticated` y las sesiones siguen vivas. El efecto en el frontend es por lectura; no se probó en navegador.
- **Impacto:** un caso que el texto llama "normal" expulsa a la persona, aunque su sesión sigue válida. Con una respuesta perdida, además, queda una sesión huérfana hasta su vencimiento.
- **Plan de corrección:** recomendado: `/auth/refresh` responde 401 con un `code` propio (`session_rotated`) dentro de la gracia; el cliente, ante ese código, espera y reintenta una vez, ya con la cookie nueva.
  - Cambios en `handling` (nueva excepción), `security.md:136-141,249` y `building-axios-clients` (`refreshAccessToken`).
  - Verificación: test del cliente HTTP con adapter falso y test de backend.
- **Decisión requerida:** elegir entre (a) `session_rotated` + reintento (recomendado); (b) emitir tokens nuevos dentro de la gracia, más simple pero amplía la ventana de un token robado; (c) aceptar el comportamiento y corregir el comentario.
- **Otros dominios afectados:** frontend (`building-axios-clients`, canónico de backend: 401 + `code`).

### BE-10: bloques marcados "verificado" sin test en `tests/snippets/`, contra la regla del README; uno de ellos no parsea
- **Severidad:** media
- **Tipo:** d
- **Evidencia:**
  - `README.md:66`: "Un bloque que el texto marca como **verificado** tiene su test en `tests/snippets/`."
  - `handling/SKILL.md:52`: "verificado: tests de integración comprueban 404/409/422/500…". `layering/SKILL.md:68`: "código verificado: 17 tests, mypy `--strict`, ruff". `test_python_snippets.py` solo cubre `Settings` y `UtcDateTime`; `generate.py` solo el frontend.
  - `DIAGNOSTICO.md:84`: "18 tests… 18/18" contra los "17 tests" de `layering:68`.
  - `DIAGNOSTICO.md:84` "PostgreSQL 17" contra `testing:59` "PostgreSQL 16"; `sessions:43` y `migrating:50` dicen 17, `docker.md:157` usa 16, y `testing:30` exige "la misma versión".
  - `DIAGNOSTICO.md:94`: "parseo de 38 bloques Python… 0 errores", contra `testing:116`: `with PostgresContainer("postgres:16-alpine", driver="asyncpg")  # = la versión de producción as pg:`, marcado como verificado en `testing:59`.
  - `DIAGNOSTICO.md:170` (§8) ya reconoce que los proyectos de referencia están fuera del repo. Lo que no coincide es la regla del README, que afirma otra cosa. El pendiente de §8 no resuelve esto.
- **Confirmación:** ejecutado. `exp_parse.py`: 46 bloques Python, 13 YAML y 3 TOML, con 1 error: `testing-fastapi-endpoints/SKILL.md` línea 116, `SyntaxError: expected ':'`. Introducido en `edd80d7`. Fuera de esa línea, `errors.py` y `layering` funcionan: el problema es la afirmación, no el código.
- **Impacto:** "verificado" pierde valor como señal. Justo el `conftest` que la skill presenta como verificado no se puede copiar.
- **Plan de corrección:** canónico: la regla del README.
  - Corto plazo: test `test_all_python_blocks_parse` sobre todos los `.md` (`exp_parse.py` sirve de base).
  - Versionar `build.py` como `tests/snippets/` para armar la app y correr sus tests, con lo que `errors.py` y `layering` quedan cubiertos.
  - Unificar el conteo y la versión de Postgres en los textos, reverificando con la versión de `docker.md`.
- **Decisión requerida:** ¿cubrir con tests todo lo "verificado" (recomendado) o relajar `README.md:66` a "verificado en un proyecto de referencia, sin test versionado" donde corresponda?
- **Otros dominios afectados:** todos los que marcan "verificado"; testing debe corregir `testing:116`.

### BE-11: "Postgres en CI" lo exigen `scaffolding` y `testing`, pero `ci.md` no trae ese job
- **Severidad:** media
- **Tipo:** b
- **Evidencia:**
  - `scaffolding/SKILL.md:23`: "SQLite en memoria por defecto, Postgres vía testcontainers en CI".
  - `testing/SKILL.md:271`: "`TEST_DB=postgres uv run pytest` pasa con Docker (en CI, al menos en un job)".
  - `references/ci.md:5-9,112-115`: solo `test-python` (SQLite) y `migrations`.
  - `references/ci.md:11`: "agregar un job con `TEST_DB=postgres`… **obligatorio si hay tests de concurrencia**", sin YAML.
  - `DIAGNOSTICO.md:37`: "job opcional".
- **Confirmación:** por lectura. `TEST_DB=postgres uv run pytest` sí se ejecutó y pasó en local. CircleCI no se pudo ejecutar.
- **Impacto:** el pipeline publicado ejecuta `FOR UPDATE` e índices parciales solo sobre SQLite, que los ignora; el ejemplo central (`get_for_update`) nunca se ejerce en CI.
- **Plan de corrección:** canónico: `testing:271` y `scaffolding:23`.
  - `ci.md`: agregar el job `test-postgres` (executor `machine`) al YAML y al workflow.
  - Actualizar la tabla de `ci.md:5-9` y `DIAGNOSTICO.md:37`.
  - Verificación: validar con `circleci config validate` y correrlo en un proyecto real.
- **Decisión requerida:** ¿job siempre obligatorio (recomendado) u obligatorio solo con tests de concurrencia, ajustando `scaffolding:23` y `testing:271`?
- **Otros dominios afectados:** testing (sin cambios si se acepta la recomendación).

### BE-12: nada en CI ni en el pyproject base hace cumplir las capas, `mypy` o `ruff`
- **Severidad:** media
- **Tipo:** e
- **Evidencia:**
  - `layering/SKILL.md:225`: "Las capas se hacen cumplir con `import-linter`… falla el CI o el paso previo a integrar".
  - `layering/SKILL.md:247,254`: checklist con `uv run lint-imports` y `mypy --strict app`.
  - `references/ci.md`: `grep -n "lint-imports\|mypy\|ruff"` no devuelve ninguno.
  - `scaffolding/SKILL.md:109`: "`uv run pytest`, `uv run mypy app` y `uv run ruff check` pasan" (sin `lint-imports`).
  - `scaffolding/SKILL.md:65-95`: sin `[tool.importlinter]` ni `[tool.ruff]`, aunque `:102` instala ambas herramientas. `DIAGNOSTICO.md:85`: `ruff` con `E,F,I,UP,B,SIM,ASYNC`, sin bloque publicado.
- **Confirmación:** ejecutado. Con el pyproject de `scaffolding`, `uv run lint-imports` da `Could not read any configuration.`. Con el bloque de `layering` agregado, pasa.
- **Impacto:** una violación de capas, justo lo que la skill dice evitar, se integra sin que nada falle.
- **Plan de corrección:** canónico: `layering:225`.
  - `scaffolding`: sumar `[tool.importlinter]` y `[tool.ruff]` al pyproject, y `lint-imports` al checklist.
  - `ci.md`: job `lint` con `ruff check`, `mypy app` y `lint-imports`.
  - Verificación: una importación `services → api` hace fallar el job.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### BE-13: compose publica backend y base en todas las interfaces, y eso saltea el límite de login y expone `/metrics`
- **Severidad:** media
- **Tipo:** e
- **Evidencia:**
  - `references/docker.md:197`: `"8000:8000"`; `:165`: `"${DB_PORT:-5432}:5432"`.
  - `references/docker.md:230`: "en producción, la imagen tal cual (sin volumen de código, sin `--reload`)". No menciona los puertos.
  - `references/security.md:236`: "Límite de intentos de login | `limit_req` en nginx".
  - `observability/exposing-prometheus-metrics/SKILL.md:39`: "`/metrics` público en internet" es anti-patrón.
- **Confirmación:** ejecutado en parte: a través de nginx la ráfaga de 9 logins dio 6 × 401 y 3 × 429; directo a `:8000` el login respondió sin pasar por nginx. Que `/metrics` queda accesible por `:8000` es por lectura.
- **Impacto:** quien despliega siguiendo `:230` deja la base y el backend públicos, y el rate limit es esquivable.
- **Plan de corrección:** canónico: `security.md:236` y `metrics:39`.
  - `docker.md:230`: agregar "sin `ports` en `db` y `backend`".
  - Mejor aún: mover `ports`, volumen y `--reload` a un `docker-compose.override.yml` solo de desarrollo.
  - Verificación: `docker compose -f docker-compose.yml config` sin puertos salvo `frontend`.
- **Decisión requerida:** ¿override de desarrollo (recomendado) o solo la nota?
- **Otros dominios afectados:** observability (Prometheus sigue llegando por la red interna, `backend:8000`).

### BE-14: `configuring` manda usar `DOCS_ENABLED` en vez de `if prod`, pero `Settings` y `layering` usan `is_prod`
- **Severidad:** baja
- **Tipo:** a, b
- **Evidencia:**
  - `configuring/SKILL.md:37`: "`if ENV == "prod":` repartido por la app … flags explícitos en `Settings` (`DOCS_ENABLED`, `OTEL_...`)".
  - `configuring/SKILL.md:132-134`: `def is_prod`.
  - `layering/SKILL.md:208`: `docs_url=None if settings.is_prod else "/docs"`.
- **Confirmación:** ejecutado: `is_prod` existe y `DOCS_ENABLED` no está en `model_fields`.
- **Impacto:** el ejemplo central contradice el anti-patrón; staging publica `/docs` sin que nadie lo haya decidido.
- **Plan de corrección:** canónico: la regla.
  - `configuring`: agregar `DOCS_ENABLED: bool = False` y quitar `is_prod`.
  - `layering:208`: `docs_url="/docs" if settings.DOCS_ENABLED else None`.
  - `.env.example` de desarrollo con `DOCS_ENABLED=true`; `conftest` no lo necesita.
  - El test de contrato pasa a cubrirlo.
- **Decisión requerida:** ¿flag (recomendado) o quitar el anti-patrón y aceptar `is_prod`?
- **Otros dominios afectados:** ninguno. `scaffolding:38` necesita `/docs` en el paso 5: en dev queda encendido.

### BE-15: `OWNER_EMAIL` y `OWNER_PASSWORD` se leen del entorno sin estar en `Settings`
- **Severidad:** media
- **Tipo:** e
- **Evidencia:**
  - `references/security.md:209`: "un comando que lee `OWNER_EMAIL` y `OWNER_PASSWORD` del entorno".
  - `configuring/SKILL.md:17`: "App, Alembic, seeds, workers y telemetría importan `get_settings()`. Nadie más lee `os.environ`."
  - `configuring/SKILL.md:199`: el grep de `os.getenv|os.environ` solo debe encontrar `get_settings()`. `scaffolding:47`: mismo invariante.
  - `grep -rn OWNER_EMAIL skills`: solo `security.md:209`. No están en `Settings` ni en ningún `.env.example`.
- **Confirmación:** por lectura más grep.
- **Impacto:** el agente lee `os.environ` en `app/bootstrap.py` (rompe el checklist) o inventa campos, y guarda la contraseña como `str`.
- **Plan de corrección:** canónico: `configuring`.
  - Agregar `OWNER_EMAIL: str | None = None` y `OWNER_PASSWORD: SecretStr | None = None`.
  - `security.md:209`: "lee de `get_settings()`; sin ellos, `SystemExit`".
  - Comentados en los dos `.env.example`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### BE-16: dos `.env.example` distintos, y ninguno "lista todas las claves"
- **Severidad:** baja
- **Tipo:** a, b
- **Evidencia:**
  - `configuring/SKILL.md:29,202`: "`.env.example` con todas las claves"; "`.env.example` lista todas las claves".
  - `configuring/SKILL.md:21`: "una clave vacía copiada de `.env.example` (`DB_PORT=`)". El ejemplo `:183-191` no tiene claves vacías ni `DB_PORT`.
  - `references/docker.md:12,235-243`: otro `.env.example` para la raíz.
  - `frontend/building-axios-clients/SKILL.md:361-363`: `throw new Error("Falta FRONTEND_API_PROXY_TARGET en .env …")`, ausente de ambos.
  - `configuring:29,202`: "`.env*` … en `.dockerignore`", contra `docker.md:78`: `.env` en `backend/.dockerignore`.
- **Confirmación:** ejecutado. Faltan en el de `configuring` 17 campos de `Settings` (`DB_PORT`, `LOG_LEVEL`, `OTEL_*`, `DB_POOL_*`…). `configuring` tiene `APP_ENV` y `CORS_ORIGINS` que `docker.md` no; `docker.md` tiene `DB_PORT` que `configuring` no.
- **Impacto:** cada agente produce un archivo distinto, y `npm run dev` falla porque falta `FRONTEND_API_PROXY_TARGET`.
- **Plan de corrección:** canónico: un único `.env.example` en `configuring`.
  - `docker.md` remite a ese bloque y solo aclara los overrides.
  - Agregar comentadas las claves opcionales, `FRONTEND_API_PROXY_TARGET` y `GRAFANA_*`.
  - Cambiar `docker.md:78` a `.env*`.
  - Verificación: test que compare `Settings.model_fields` con las claves del bloque.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** frontend (`FRONTEND_API_PROXY_TARGET`), observability (`GRAFANA_*`).

### BE-17: la tabla de imports de `layering` prohíbe lo que su propio ejemplo y otras skills hacen
- **Severidad:** baja
- **Tipo:** a, b
- **Evidencia:**
  - `layering/SKILL.md:31`: `api/` "Puede importar `services`, `schemas`, `api.deps`, `errors`, `config`, `models`". Sin `crud` ni `database`.
  - `layering/SKILL.md:177-178`: `def get_order_service(db: DbSession)… OrderService(db, ProductRepository(db), OrderRepository(db))`, en `api/deps.py`.
  - `layering/SKILL.md:32`: `services/` puede importar `crud, models, schemas, errors, config, otros services`, contra `:23` "métricas de negocio", `exposing-prometheus-metrics:20` ("importadas por los services") y `security.md:120-122` (`AuthService` usa `app.security`).
- **Confirmación:** ejecutado: `lint-imports` da KEPT con esos imports, porque el contrato de capas permite saltear niveles. La contradicción con la tabla es por lectura.
- **Impacto:** el agente que respeta la tabla no sabe dónde componer; el que la ignora importa repositorios en cualquier router sin que el linter lo detecte.
- **Plan de corrección:** canónico: el ejemplo.
  - `layering:31`: agregar "`crud` y `database` solo en `api/deps.py` (raíz de composición)".
  - `layering:32`: agregar `observability.metrics` y `security`.
  - Agregar el contrato `forbidden` `app.api → app.crud` con `ignore_imports = ["app.api.deps -> app.crud.*"]` (o la forma que acepte import-linter; hay que comprobarlo).
  - Sumar `security.py` al árbol de `:15-27`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### BE-18: `create_app(settings)` y `dependency_overrides[get_settings]` no gobiernan todo lo que parecen
- **Severidad:** baja
- **Tipo:** c
- **Evidencia:**
  - `layering/SKILL.md:50`: "`create_app()` como factory: tests y workers pueden construir apps con otros settings."
  - `configuring/SKILL.md:27`: "Los tests lo sobreescriben con `app.dependency_overrides` o `get_settings.cache_clear()`."
  - `handling/SKILL.md:130`: `get_settings().ERRORS_BASE_URL`.
  - `database/configuring-sqlalchemy-sessions/SKILL.md:73`: `engine = build_engine(get_settings())`, a nivel de módulo.
- **Confirmación:** ejecutado (`exp_runtime.py`). `create_app(Settings(ERRORS_BASE_URL="https://errors.otra.invalid"))` responde `type = https://errors.default.invalid/http_404`. Con `dependency_overrides[get_settings]`, el mismo resultado. El engine y `setup_tracing` también se quedan con el primero.
- **Impacto:** un test que confía en esas dos frases ve valores viejos sin error. `get_settings.cache_clear()` sí funciona.
- **Plan de corrección:** recomendado: acotar el texto.
  - `layering:50`: "lo que `create_app` recibe llega a título, CORS y docs; engine y errores usan `get_settings()`: para cambiarlos, entorno + `cache_clear()` antes de importar".
  - `configuring:27`: "`dependency_overrides` solo afecta a lo inyectado con `SettingsDep`".
  - Alternativa: `app.state.settings` en `problem()`.
- **Decisión requerida:** ¿acotar el texto (recomendado) o hacer que `problem()` lea `request.app.state.settings`?
- **Otros dominios afectados:** database (si se elige `app.state`, el engine sigue global).

### BE-19: "siempre la misma forma… `detail`", pero 3 de los 4 handlers no lo envían
- **Severidad:** baja
- **Tipo:** a
- **Evidencia:**
  - `handling/SKILL.md:20`: "El cuerpo siempre tiene la misma forma: `type`, `title`, `status`, `code`, `detail`, `instance`".
  - `handling/SKILL.md:133-134`: `if detail:`; `:152-153`, `:158-159`, `:165`: llamadas sin `detail`.
- **Confirmación:** ejecutado: las respuestas 500, 404 y 422 no traen `detail`.
- **Impacto:** el backend de un agente que "corrige" el código divergiría; un tipo que declare `detail` obligatorio sería falso.
- **Plan de corrección:** canónico: el código (RFC 9457 lo hace opcional y `building-axios-clients:54` ya tiene `detail?: string`). `handling:20`: "`type`, `title`, `status`, `code`, `instance` siempre; `detail` si hay mensaje específico; `trace_id` si hay traza".
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### BE-20: el test de contrato no cubre `references/` ni `get_settings().X`, y conserva una excepción obsoleta
- **Severidad:** baja
- **Tipo:** d
- **Evidencia:**
  - `DIAGNOSTICO.md:152`: "test de contrato sobre todas las skills".
  - `tests/snippets/extract.py:32`: `SKILLS.glob("*/*/SKILL.md")`, que excluye `security.md`, `docker.md` y `stack.md`.
  - `tests/snippets/test_python_snippets.py:60`: `r"\bsettings\.([A-Z][A-Z0-9_]+)\b"`.
  - `tests/snippets/test_python_snippets.py:51-52`: `# settings.ALGORITHM es una constante… CONSTANTS = {"ALGORITHM"}`; `settings.ALGORITHM` ya no aparece en ninguna skill.
  - `README.md:70`: `--with sqlalchemy` sin fijar, contra `scaffolding:73` `<2.1`.
- **Confirmación:** ejecutado: `all_text()` no incluye `security.md` ni `stack.md`; la regex no detecta `get_settings().ERRORS_BASE_URL`; el grep de `settings.ALGORITHM` da vacío; `--with sqlalchemy` resuelve 2.1.6. Hoy no falta ningún campo: es una falla de cobertura, no un bug activo.
- **Impacto:** un campo nuevo leído solo desde `security.md` o con `get_settings().X` rompe sin que el test avise.
- **Plan de corrección:** ampliar el glob a `**/*.md` (más `is_prod`/minúsculas si queda), ampliar la regex, borrar `CONSTANTS` y fijar `"sqlalchemy<2.1"` en `README.md:70` y en el docstring del test. Verificación: mutación que quite un campo leído solo en `security.md`; el test debe fallar.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### BE-21: comentario falso sobre `container_name`
- **Severidad:** baja
- **Tipo:** d
- **Evidencia:** `references/docker.md:188`: `container_name: backend_app       # nombre fijo: las queries de Loki lo usan`. Las queries reales usan el servicio de compose: `logging-json-to-loki:166-169` `{service="backend"…}` y `:118` `com_docker_compose_service`.
- **Confirmación:** ejecutado: `grep -rln backend_app skills` solo devuelve `docker.md`.
- **Impacto:** se conserva un nombre fijo (que además impide escalar con `--scale`) por una razón inexistente.
- **Plan de corrección:** canónico: `logging`. Quitar el comentario de `docker.md:188` y, de paso, los `container_name` que nada usa.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### BE-22: dos `conftest` con valores distintos; uno apunta `DB_HOST` a `localhost`
- **Severidad:** baja
- **Tipo:** b
- **Evidencia:**
  - `configuring/SKILL.md:173`: `os.environ.setdefault("DB_HOST", "localhost")`; `:174` `"test_db"`; `:175` `"https://errors.example.com"`.
  - `testing/SKILL.md:69`: `os.environ.setdefault("DB_HOST", "test-db.invalid")  # no se usa: SQLite o testcontainers`; `:70` `"test"`; `:71` `"https://errors.test.invalid"`.
- **Confirmación:** por lectura.
- **Impacto:** con `localhost`, un test que olvide el override puede tocar una base local real, justo el anti-patrón de `testing:38`.
- **Plan de corrección:** canónico: `testing`. `configuring:167-176` copia sus valores o remite a ese bloque.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno (cambia solo `configuring`).

### BE-23: fijación de versiones desigual
- **Severidad:** baja
- **Tipo:** a, e
- **Evidencia:**
  - `scaffolding/SKILL.md:21`: "Fijar `sqlalchemy>=2.0,<2.1`", contra `:73` y `:101`: `>=2.0.40,<2.1`.
  - `references/docker.md:38-39`: uv fijado (`uv:0.12`, "nunca :latest"), contra `references/ci.md:34`: `pip install uv`, sin fijar.
  - `scaffolding/SKILL.md:61`: "tags fijos", contra `docker.md:157` `postgres:16-alpine` (móvil) y `ci.md:71` `cimg/postgres:16.4`; `testing:30` pide "la misma versión".
- **Confirmación:** ejecutado para los tags (todos existen). Lo demás, por lectura.
- **Impacto:** Postgres y uv pueden diferir entre local, imagen y CI, justo lo que `scaffolding:60` dice evitar para Python.
- **Plan de corrección:** usar un mismo minor exacto en compose, CI y `conftest` (recomendado `postgres:16.x-alpine` + `cimg/postgres:16.x`); `ci.md:34`: `pip install uv==0.12.*`; `scaffolding:21`: `>=2.0.40,<2.1`.
- **Decisión requerida:** ¿tag exacto (recomendado) o aceptar el mayor de Postgres aclarándolo en `scaffolding:61`?
- **Otros dominios afectados:** testing (`testing:116`).

### BE-24: "excepciones que no saben nada de HTTP" que declaran `status_code` y `headers`
- **Severidad:** baja
- **Tipo:** a
- **Evidencia:**
  - `handling/SKILL.md:9,11`: "Errores de dominio desacoplados de HTTP"; "excepciones de dominio que no saben nada de HTTP".
  - `handling/SKILL.md:17`: "Cada subclase declara `status_code`"; `:59`: `from fastapi import FastAPI, Request, status`; `:92`: `headers = {"WWW-Authenticate": "Bearer"}`.
  - `layering/SKILL.md:242` admite que `errors.py` y `config.py` usan FastAPI.
- **Confirmación:** por lectura.
- **Impacto:** un agente que toma la frase al pie intenta separar `errors.py` y se aparta del ejemplo; un worker que importa los errores arrastra FastAPI.
- **Plan de corrección:** canónico: el código, ya integrado en toda la biblioteca. `handling:11`: "los services lanzan excepciones de dominio y no tocan `HTTPException` ni `Request`; cada una declara su traducción HTTP como metadato, en un único módulo".
- **Decisión requerida:** ¿aceptar el metadato HTTP (recomendado) o separar dominio y traducción, lo que obliga a un mapa aparte?
- **Otros dominios afectados:** ninguno si se acepta.

### BE-25: el compose publicado no cumple "solo líneas JSON"
- **Severidad:** baja
- **Tipo:** c
- **Evidencia:**
  - `observability/logging-json-to-loki/SKILL.md:175`: "`docker compose logs backend` … muestra solo líneas JSON válidas, incluidas las de uvicorn".
  - `references/docker.md:200`: `"--reload"` en el `command`.
- **Confirmación:** ejecutado. `docker logs backend_app` muestra `INFO:     Will watch for changes…`, `INFO:     Uvicorn running on…` e `INFO:     Started reloader process…` en texto plano antes de las líneas JSON (el reloader corre antes de `create_app`). Sin `--reload` no se probó.
- **Impacto:** el checklist falla con el compose publicado y un agente puede perder tiempo persiguiéndolo.
- **Plan de corrección:** canónico: mantener `--reload` en desarrollo. `logging:175`: "salvo las líneas del reloader con `--reload`". BE-13 (override de desarrollo) lo ordena solo.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** observability (texto del checklist).

### BE-26: `/health/ready` con `.execute(` en la capa `api` incumple el grep de `layering`
- **Severidad:** baja
- **Tipo:** b
- **Evidencia:**
  - `layering/SKILL.md:248`: "`grep -rn "select(\|\.execute(" app/api app/services` no devuelve nada: todo el SQL vive en `crud/`".
  - `database/configuring-sqlalchemy-sessions/SKILL.md:127-129`: `db.execute(text("SELECT 1"))` en un endpoint.
  - `scaffolding/SKILL.md:36`: "`/health/ready` hace `SELECT 1`".
- **Confirmación:** por lectura.
- **Impacto:** el endpoint obligatorio del paso 3 hace fallar el checklist del paso 2 si se escribe como lo muestra el ejemplo.
- **Plan de corrección:** canónico: `layering`. Publicar `HealthRepository.ping()` en `crud/` junto al router de BE-07 y usarlo en `sessions`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** database.

---

## Dudosos

No se cuentan como hallazgos: quedan a criterio del dueño.

| ID | Tema | Evidencia | Confirmación | Recomendación |
|---|---|---|---|---|
| D1 | Errores de nginx no son problem+json | `handling:237` "Todas las respuestas de error tienen `Content-Type: application/problem+json`" contra los 429 y 413 reales de `docker.md:120,128` | ejecutado: `429 text/html`, `413 text/html`. `toApiError` tolera `problem: null` (`axios:90-95,129`) | Acotar el checklist a "las que emite la app", o definir `error_page` JSON en nginx |
| D2 | El placeholder de `SECRET_KEY` pasa la validación | `configuring:184` y `docker.md:240` tienen 36+ caracteres; `configuring:38` critica "valor público" | ejecutado: la app arranca con ese valor | Guarda en staging/prod contra los valores de ejemplo, o dejar la clave vacía en el ejemplo para que falle |
| D3 | La cookie restringida a `/api/v1/auth` no llega a un loader SSR | `security.md:164` contra `choosing-ssr-or-spa:106,114` ("reenvía la cookie") | por lectura | Aclarar en `choosing-ssr-or-spa` que SSR autenticado exige otra estrategia |
| D4 | `code` no se mapea a tipos; 400/413/415 pierden `problem` | `handling:240` "que los mapea a tipos" contra `axios:123-130` (switch por status; `unknown` sin `problem`) | por lectura | Corregir la frase; sumar `problem` a `unknown` |
| D5 | CORS en el ejemplo pese a que el cliente evita CORS | `configuring:189` `localhost:5173` contra `axios:26`, `docker.md:101` | por lectura | Dejar `CORS_ORIGINS` vacío en el ejemplo |
| D6 | Refresh sin bloqueo de fila | `security.md:133,145` contra `modeling:46` (leer-modificar-escribir con `with_for_update`): dos refresh simultáneos con el mismo token podrían rotar ambos | por lectura; no se probó con concurrencia real | `get_by_hash_for_update` y test con `TEST_DB=postgres` |
| D7 | `/openapi.json` sigue público con `docs_url=None` | `layering:208` | por lectura para prod; en stage test responde 200 | `openapi_url=None` junto con el flag de BE-14 |
| D8 | `HTTPXClientInstrumentor` sin paquete declarado | `tracing:25` contra `scaffolding:71-78` ("solo lo que se importa") | por lectura. El bloque de `tracing` tampoco lo llama | Lo evalúa observability |
| D9 | `uv init my-api` crea layout en raíz, pero `ROOT_DIR` usa por defecto `parents[2]` | `scaffolding:100` contra `configuring:59-62` (el comentario sí lo aclara) | por lectura | Mencionarlo en el bootstrap |
| D10 | `frontend/Dockerfile` hace `COPY . .` sin `.dockerignore` publicado | `docker.md:92` | por lectura; el build no se ejecutó | Publicar `frontend/.dockerignore` |

## Observaciones para otros auditores

- **testing:** `skills/testing/testing-fastapi-endpoints/SKILL.md:116` es un `SyntaxError` (ejecutado, ver BE-10). Una vez corregida, `TEST_DB=postgres` pasa con `testcontainers.community.postgres`.
- **observability:** `tracing-with-opentelemetry:148` usa `ProductFactory.create_async`, pero `testing:25-26` define helpers por defecto y `polyfactory` no está en `scaffolding:80-84`. El JSON de uvicorn trae también el campo `color_message` (visto en `docker logs`).

## Lo que no se pudo verificar

- **CircleCI:** `ci.md` no se ejecutó; solo se comprobó que imágenes y orb existen y que el YAML parsea.
- **Frontend en navegador:** el efecto final de BE-09 y el envío real de `SameSite=strict` no se probaron.
- **Build de `frontend/Dockerfile`:** no hay proyecto frontend en el armado. Sí se probaron el `nginx.conf` y el proxy.
- **`app.bootstrap` y `app.seed`:** ninguna skill los publica.
- **Concurrencia real en `refresh`:** D6 no se probó.
- **`ignore_imports` de BE-17:** la forma exacta del contrato propuesto no se ejecutó.
- **Pegamento:** BE-07 y BE-08 dependen de piezas escritas por el auditor siguiendo los patrones publicados, porque las skills no las publican.
