# Plan de corrección: inconsistencias de orquestación (2026-11-22)

> **Para agentes:** ejecutar por tareas (T-A … T-E) en paralelo; cada tarea es dueña de sus archivos. Los pasos usan `- [ ]`.

**Objetivo:** que un agente que siga el orquestador (`scaffolding-fastapi-backends`) y las skills delegadas produzca un stack que arranca, se despliega y se prueba sin contradicciones.

**Base:** commit `ecbaf13`. **Evidencia:** auditoría de 5 subagentes del 2026-11-22 (frontend, backend, scaffolding, database, observabilidad); los hallazgos de §1 fueron reconfirmados por lectura.

**Enfoque:** cada hallazgo se corrige en la skill dueña del contrato y se propaga a quien lo consume. Donde la skill publica código que los tests extraen (`tests/snippets/extract.py` busca el bloque por marcador), el arreglo se hace en la `SKILL.md` y, si cambia el contrato, también en el test o en `reference/build_ref.py`. El "pegamento" de `build_ref.py` que corresponde a piezas que ahora se publican pasa a extraerse del bloque publicado.

## Restricciones globales

- Las skills están en español; el código y los identificadores, como están.
- No renombrar marcadores que usan los tests (p. ej. `name = "my-api"`, `class UserRepository`, `ALGORITHM = "HS256"`) salvo que se actualice el test en la misma tarea.
- Toda mención nueva de "verificado" se registra en `tests/snippets/verified_claims.py` con su etiqueta (`verificado (test)` / `verificado a mano (AAAA-MM-DD, herramienta)`).
- Sin `:latest`; versiones iguales a las ya fijadas (Postgres `16.15`, Python 3.14, `sqlalchemy[asyncio]>=2.0.40,<2.1`).
- Archivos compartidos entre tareas (`reference/build_ref.py`, `verified_claims.py`): **solo `Edit` puntual**, nunca reescribir el archivo entero.
- `tests/snippets/reference/run.sh` escribe en un directorio compartido: correrlo siempre con `flock /tmp/claude-1000/skills-ref.lock tests/snippets/reference/run.sh`.
- `configuring-fastapi-settings/SKILL.md` es de T-C: las otras tareas le piden a T-C (vía este plan) lo que necesitan; ya está listado abajo.
- No se hace commit (lo decide el usuario).

## Foco de revisión

1. `docker compose -f docker-compose.yml config` con el `.env.example` copiado debe fallar el arranque del backend en prod si `COOKIE_SECURE=false` (guarda) — el texto tiene que decir qué `.env` usa prod.
2. `alembic upgrade head` detrás de un rol con `statement_timeout` corto: la migración no debe heredar el timeout.
3. Un segundo `create_app()` en el mismo proceso (tests) debe seguir generando spans de request.
4. Primera visita sin sesión (refresh → 401): una sola navegación a `/login`, con `next` correcto.
5. Errores `unauthorized` y `canceled` nunca llegan a `reportError`.

---

### T-A · Orquestador y despliegue (`backend/scaffolding-fastapi-backends/**`)

**Archivos:** `SKILL.md`, `references/docker.md`, `references/ci.md`, `references/security.md`; `tests/snippets/reference/build_ref.py` (solo la sección auth, líneas ~163-280); tests de `test_wave2_*` que lean estos archivos.

- [x] **A1 · `APP_ENV` en compose (hallazgo 1.1).** `docker-compose.yml`: `APP_ENV: prod` en `environment` de `migrate` y `backend`. `docker-compose.override.yml`: `APP_ENV: dev` en ambos. Nueva decisión en docker.md: el `.env` de la raíz es solo de desarrollo (el de `.env.example`, con `COOKIE_SECURE=false` y `DOCS_ENABLED=true`); en prod las variables llegan del orquestador/secrets y la guarda de `Settings` rechaza `COOKIE_SECURE=false`. Corregir la línea "El mismo `.env` sirve desde el host" para que no implique prod.
- [x] **A2 · TLS (1.1).** Decisión en docker.md: en prod, TLS termina delante de nginx (balanceador o proxy del host) y nginx reenvía `X-Forwarded-Proto` del terminador (`$http_x_forwarded_proto`), no `$scheme`; sin TLS el navegador descarta la cookie `Secure` del refresh. `listen 80` queda para la red interna.
- [x] **A3 · `httpx` en prod (1.3).** En el `pyproject.toml` publicado, `"httpx"` pasa a `dependencies` junto a `opentelemetry-instrumentation-httpx` (comentario: el instrumentor lo importa; se quitan juntos) y sale de `dev`. Actualizar el test de contrato `test_tracing_block_instruments_httpx_and_scaffolding_lists_the_package` para exigir `httpx` en `dependencies`.
- [x] **A4 · Variante multiproceso en la imagen (1.6).** docker.md, nueva subsección "Varios workers": `COPY gunicorn.conf.py ./` y `CMD ["sh", "-c", "rm -rf \"$PROMETHEUS_MULTIPROC_DIR\" && mkdir -p \"$PROMETHEUS_MULTIPROC_DIR\" && exec gunicorn app.main:app -c gunicorn.conf.py"]`, con `ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus`. Remite a `exposing-prometheus-metrics` para `gunicorn.conf.py` (no lo duplica). Lo que el `CMD` invoca debe coincidir con la receta de esa skill (T-D no cambia la receta).
- [x] **A5 · Paso Frontend en el orquestador (2.1).** Tabla "Orden de construcción": nueva fila **7 · Frontend** (`choosing-ssr-or-spa` → por defecto SPA en data mode, `architecting-react-apps`, `routing-with-react-router`, `building-axios-clients`, `handling-react-errors`; "Listo cuando": `npm run build` genera `dist/` y el login + refresh funcionan contra el backend por el proxy de Vite). Renumerar Docker 8, Observabilidad 9, CI 10. Actualizar "Skills relacionadas". docker.md: nota de que el Dockerfile del frontend vale para SPA (`dist/`); con framework mode y `ssr: false` se copia `build/client`, y con SSR el frontend es un servidor Node (fuera de esta receta).
- [x] **A6 · Paso 2 y paso 3 (2.2, 2.3).** Fila 2: "Listo cuando" pasa a: arranca con `health.py` + `errors.py` + `main.py` sin las líneas `# paso N` (sin `api_router` ni `deps.py`; esos llegan en el paso 4 con el primer recurso). Coordinado con T-C (C3 marca esas líneas). Fila 3: agregar "Postgres local: `docker compose up -d db` (solo el servicio `db` de docker.md)"; aclarar el anti-patrón "Empezar por Docker": la base en contenedor sí se levanta desde el paso 3.
- [x] **A7 · Carpeta y versión de Python (2.4, 2.7).** Bootstrap: `uv init --bare --python 3.14 backend && cd backend` y `uv python pin 3.14` (crea `.python-version`, que usa el job `test-postgres`). `name = "my-api"` en el pyproject se mantiene (marcador de tests). Verificar que `test_wave2_project` sigue armando el clon.
- [x] **A8 · `--scale` (2.6).** docker.md: reemplazar "Un nombre fijo impide `--scale`" por: el stack asume una réplica del backend (varios workers dentro, ver A4); escalar réplicas exige descubrimiento por DNS en Prometheus (`dns_sd_configs`) y alertas con `absent()`, fuera de esta receta.
- [x] **A9 · Puertos de observabilidad (2.5).** docker.md "nada publicado salvo `frontend`": aclarar que con el stack de `stack.md` los puertos de monitoreo se publican solo en `127.0.0.1` (lo cambia T-D en stack.md).
- [x] **A10 · Piezas de auth sin dueño (3.1, 3.3, 3.4).** security.md publica:
  - modelos `Role`, `Permission` (tabla puente `role_permissions`) y `User` (con `role` `lazy="raise"`), tomados del pegamento de `build_ref.py`;
  - `get_auth_service(db: DbSession, settings: SettingsDep) -> AuthService` + `AuthServiceDep` en `api/deps.py`;
  - `POST /api/v1/auth/logout` **sin** `CurrentUser`: lee la cookie, revoca la sesión si existe y hace `response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)`; responde 204 siempre (idempotente).
  - Nota: la migración que siembra roles se escribe con `migrating-with-alembic` (una revisión de datos), con los nombres de rol que usa `security.md`.
  En `build_ref.py`, reemplazar el pegamento por `block(...)` de los bloques nuevos y agregar un test del logout (204 + `Set-Cookie` que borra con el mismo path) donde ya se prueban las rutas de auth (`wave2_tests/test_wave2_auth.py`).
- [x] **A11 · ci.md (5).** Tabla: round-trip completo `upgrade head → check → downgrade base → upgrade head`. Texto de SQLite en `ci.md:9-13`: SQLite **sí** tiene índices parciales (`sqlite_where`) y CHECK; lo que no tiene es `FOR UPDATE`, JSONB, `NOT VALID`/`CONCURRENTLY` y la semántica exacta de tipos. Mismo texto que usa T-C en `testing-fastapi-endpoints:20`.
- [x] **A12 · mypy de la referencia (5, backend #11).** Publicar en el `[tool.mypy]` del scaffolding lo que la referencia necesita para `mypy --strict tests/` (`mypy_path = "."` y `explicit_package_bases = true`) y quitar el `tests/__init__.py` de `build_ref.py`, o lo contrario si no pasa; el criterio es que la referencia use la config publicada.
- [x] **Verificación:** `pytest tests/snippets/test_wave2_contracts.py tests/snippets/test_wave2_project.py tests/snippets/test_wave5_contracts.py -q` (comando completo de `--with` del README) + `flock … run.sh` en verde.

### T-B · Base de datos (`database/**`)

**Archivos:** las 3 `SKILL.md` de `database/`, `tests/snippets/test_wave3_database.py`, entradas de database en `verified_claims.py`.

- [x] **B1 · `statement_timeout` en migraciones (1.2).** `env.py` publicado: junto a `SET lock_timeout`, `SET statement_timeout = 0` (online y offline). Regla en `configuring-sqlalchemy-sessions:23`: el `ALTER ROLE … statement_timeout` también alcanza a Alembic, por eso `env.py` lo anula. Test en W3: con `ALTER ROLE` a `1s`, una migración con `pg_sleep(2)` (o `SHOW statement_timeout` = `0`) corre sin cancelarse.
- [x] **B2 · Sync + PgBouncer (1.4).** `build_engine` síncrono: rama `DB_PGBOUNCER` igual a la async (`NullPool`, sin `options`, `connect_args={"application_name": …, "prepare_threshold": None}`). Si W3 ya levanta PgBouncer, agregar el caso sync.
- [x] **B3 · Sync + tracing/lifespan (1.5, parte database).** En la sección de la variante síncrona, listar las dos líneas que cambian: `engine.dispose()` sin `await` en el `lifespan`, y que `setup_tracing` acepta `Engine` (lo implementa T-D en D2). Nombrar `tracing-with-opentelemetry` en la línea 17.
- [x] **B4 · SQL fuera de `crud/` (4.5).** Los ejemplos de worker (`configuring-sqlalchemy-sessions:171-183`, `modeling-postgres-with-sqlalchemy:225-251`): el `update`/`select` pasa a un método de repositorio (`OrderRepository.expire_pending(cutoff)`) y el `commit` a un service o al worker que abre el caso de uso, citando la regla de `layering-fastapi-apps`. Si algún test extrae esos bloques, ajustarlo.
- [x] **B5 · Métricas del pool (3.8).** Reemplazar "+ métricas del pool" por lo que el stack sí tiene: `pg_stat_activity` agrupado por `application_name` y `engine.pool.status()` en logs de diagnóstico.
- [x] **B6 · Etiquetas (5).** `migrating-with-alembic:54` y `:155`, `configuring-sqlalchemy-sessions:99`: pasar a `verificado (test)` y registrar evidencia en W3 (`verified_claims.py`).
- [x] **B7 · PgBouncer fijo (5).** `test_wave3_database.py:474`: tag fijo `1.26.x` existente en Docker Hub (verificar con `docker pull`).
- [x] **Verificación:** `pytest tests/snippets/test_wave3_database.py tests/snippets/test_verified_claims.py tests/snippets/test_python_snippets.py -q`.

### T-C · Backend y testing (`backend/{layering,handling,configuring-fastapi-settings}`, `testing/**`)

**Archivos:** esas 5 `SKILL.md`; `reference/build_ref.py` (sección productos/órdenes, ~90-160); `reference/wave2_tests/*`; `test_wave2_contracts.py`.

- [x] **C1 · Recurso `products` publicado (3.2).** `layering-fastapi-apps` publica el recurso producto completo que hoy es pegamento: `ProductCreate`/`ProductRead`, `ProductRepository` (`add`, `list(offset, limit)`), `ProductService.create` (con el bloque `IntegrityError → ConflictError` de `handling-fastapi-errors`) y el router `GET/POST /api/v1/products` (listado `{"items": [...], "total": n}` o lo que ya esperan los tests). `build_ref.py` lo extrae.
- [x] **C2 · `InsufficientStockError` (3.5).** Vive en `app/services/order.py` (error específico del caso de uso; `app/errors.py` tiene las bases y los handlers). Decirlo en `handling-fastapi-errors` (aclarar el "único módulo" de la línea 11: único para las bases) y agregar el import en el bloque de layering que la lanza.
- [x] **C3 · Paso 2 (2.2).** Marcar con `# paso 4` (primer recurso) `api_router` en `main.py`, `deps.py` y `router.py`; el texto de `:273/:294` describe qué entra en cada paso. Coordinado con A6.
- [x] **C4 · Config leída al importar (4.6, 4.7 doc).** `layering:51` y `configuring-fastapi-settings:22`: los errores llaman a `get_settings()` en cada request; el engine se crea al importar `app.database` (otra config exige fijar el entorno antes del primer import); el tracing recibe `settings` de `create_app`. `lifespan`: además, `engine.dispose()` sin `await` con la variante sync (B3).
- [x] **C5 · Mapeo de errores en el front (4.8).** `handling:249`: el frontend conserva `code` en `problem.code` y mapea por `status`.
- [x] **C6 · Settings (pedidos de otras tareas + 5).**
  - Fixture `env` publicado (el de `wave2_tests/test_wave2_app.py:24-29`: `cache_clear()` antes y después) en lugar del snippet de `monkeypatch` suelto.
  - Campo `APP_INSTALLATION: str | None = None` (para D3) y su línea comentada en `.env.example`.
  - `.env.example`: `FRONTEND_API_PROXY_TARGET=http://localhost:8000` descomentado (para E7); `OTEL_EXPORTER_OTLP_ENDPOINT` comentado con nota "dentro de compose va en `environment` del backend (docker.md), desde el host `http://localhost:4317`".
- [x] **C7 · Contradicciones de testing (5).** `unit-testing:174-184`: el caso que commitea usa `new_session()` y relee. `unit-testing:19`: quitar la frase que habilita mockear repos. `testing-fastapi-endpoints:20`: texto de SQLite igual a A11.
- [x] **C8 · Detalles (5).** Checklist de `handling:242`: `grep -rn "HTTPException" app/ --exclude=errors.py`. `layering:21` y `handling:104`: `scaffolding-fastapi-backends/references/security.md`.
- [x] **Verificación:** `pytest tests/snippets/test_wave2_contracts.py tests/snippets/test_python_snippets.py tests/snippets/test_verified_claims.py -q` + `flock … run.sh` en verde (SQLite y `TEST_DB=postgres`).

### T-D · Observabilidad (`observability/**`)

**Archivos:** las 4 `SKILL.md`, `defining-grafana-slos/references/stack.md`, `templates/build_dashboard.py`, `test_wave5_*`.

- [x] **D1 · Una app nueva sigue trazada (4.7).** `setup_tracing`: el provider, SQLAlchemy y httpx se configuran una vez por proceso; `FastAPIInstrumentor.instrument_app(app, …)` se llama para **cada** app. Test en W5: dos `create_app()` seguidos, ambos producen span de request.
- [x] **D2 · Engine sync (1.5).** `setup_tracing(app, engine: AsyncEngine | Engine, settings)`: usa `engine.sync_engine` solo si es `AsyncEngine`.
- [x] **D3 · `installation` (3.7).** `JsonFormatter(service, environment, installation: str | None = None)` agrega `installation` solo si viene; `configure_logging` pasa `settings.APP_INSTALLATION` (campo de C6); `Resource` agrega `"installation"` si está definido. Checklist ajustado.
- [x] **D4 · Puertos del stack (2.5).** `stack.md`: todos los `ports` de monitoreo como `127.0.0.1:<p>:<p>`; texto alineado con docker.md (A9).
- [x] **D5 · Test de reglas (5).** `instance="backend:8000"` en el test de `promtool` y la anotación esperada.
- [x] **D6 · Parámetros de latencia (5).** Listar `LATENCY_TARGET`/`LATENCY_LE` junto a `SLO_TARGET` en `SKILL.md:484` y el docstring de `build_dashboard.py`, y anotar en el YAML de reglas que `le="0.5"` debe coincidir con `LATENCY_LE`.
- [x] **D7 · Errores del navegador (3.9).** `handling-react-errors` (lo edita T-E) declara el alcance; acá, en `tracing-with-opentelemetry` o `stack.md`, una línea: el stack no recibe telemetría del navegador (Tempo no publica OTLP/HTTP ni CORS); remitir a T-E.
- [x] **D8 · Docstring de `test_wave5_python.py:3` (5).** Actualizar (servidor local, no `MockTransport`).
- [x] **Verificación:** `pytest tests/snippets/test_wave5_contracts.py tests/snippets/test_wave5_python.py tests/snippets/test_wave5_monitoring.py tests/snippets/test_python_snippets.py -q`.

### T-E · Frontend (`frontend/**`, `tests/snippets/web/**`, `tests/snippets/generate.py`)

- [x] **E1 · Default de render (2.1).** `choosing-ssr-or-spa:35`: el default de este stack es SPA con data mode (lo que asumen routing, architecting y docker.md); framework mode cuando hay contenido público indexable. `ssr:98`: el alias `@/` apunta a `src/` (o declarar `app/` como raíz en framework mode).
- [x] **E2 · `useActionState` en una ruta (4.1).** `routing:393` adopta la regla de `actions:49` (D19 del plan anterior).
- [x] **E3 · Buscador (4.2).** Quitar "un buscador" de `actions:49`.
- [x] **E4 · Doble redirect (4.3).** `redirectToLogin` no navega si `!router.state.initialized` (el middleware/loader ya lanza `redirect`). Test web: refresh → 401 en la primera visita produce una sola navegación a `/login?next=…`.
- [x] **E5 · Telemetría (4.4).** `reportError` (o `onRouterError`/`onExport`) ignora `unauthorized` y `canceled`; `actions:30` dice qué hacer fuera de una action (no relanzar: mostrar estado o dejar que el interceptor redirija). Test web: un `unauthorized` en un handler no llama al reporter.
- [x] **E6 · `assertNever` (3.6).** Publicar `export function assertNever(value: never): never` en `src/lib/http/errors.ts` (o donde lo use `axios:26`).
- [x] **E7 · Config de Vite (5).** Un solo `vite.config.ts` combinado (plugins + alias + proxy con `FRONTEND_API_PROXY_TARGET`) en `building-axios-clients`; `architecting` y `optimizing` remiten a él.
- [x] **E8 · Errores del navegador (3.9).** `handling-react-errors`: el stack de este repo no recibe telemetría del navegador; la receta lista es el reporter propio/Sentry, y OTel web necesita un colector OTLP/HTTP con CORS que esta biblioteca no publica.
- [x] **E9 · Detalles (5).** Comentario de contraseña en `routing:225`; `index.ts` con nombres explícitos (`routing:112` y el stub de `generate.py:92`); `ProductStock` con `signal` o declarado como excepción, y dónde vive; `lint.mjs` aplica la config de arquitectura también a `generated/`; `good-imports.ts` de `routes/` importa desde una feature, no `@/lib/http`; `vercel-index` → `vercel-index/SKILL.md` (actualizar README, `install.sh` y `validate_skills.py` si lo tratan aparte).
- [x] **Verificación:** `cd tests/snippets/web && npm test` + `uv run --with pyyaml python scripts/validate_skills.py`.

---

## Cierre (orquestador)

- [x] Suite Python completa (comando del README), `run.sh` (SQLite y `TEST_DB=postgres`), `npm test`, `validate_skills.py`.
- [x] `git diff --stat` revisado; un revisor independiente sobre el diff completo (el subagente revisor se cortó por el límite de uso; en su lugar, comprobaciones cruzadas del orquestador: ver DIAGNOSTICO §10).
- [x] `DIAGNOSTICO.md`: sección nueva con este plan y lo que quedó sin verificar.
