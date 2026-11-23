# Informe de diagnóstico y reestructuración

**Fecha:** 2026-10-23 · **Alcance:** auditoría del repositorio `my_skills` y reconstrucción como biblioteca de skills production-ready para 5 dominios (frontend, backend, database, testing, observability).

## 1. Resumen ejecutivo

- **Estado inicial:** 1 skill (`scaffolding-fastapi-backends`), 9 archivos, ~1.600 líneas, sin commits. Cubría bien un stack FastAPI de punta a punta, pero en una sola skill monolítica. No tenía nada de frontend, le faltaban piezas exigidas (mocks, rollback por test, logs JSON, SLOs, naming conventions de Alembic, configuración por stage) y usaba versiones e imágenes desactualizadas.
- **Estado final:** 20 skills + 1 índice (Vercel) en `skills/<dominio>/`, todas con el estándar exigido (frontmatter `name/description/domain/tags/triggers`, *Contexto y reglas* con anti-patrones, *Ejemplos* tipados, *Checklist de verificación*), validadas por `scripts/validate_skills.py`.
- **Respaldo:** los 9 archivos originales están intactos en `backup_old_version/scaffolding-fastapi-backends/` (verificado con `diff -r`).
- **Verificación:** el código de las skills se extrajo de dos proyectos de referencia que se construyeron y probaron (ver §6). Eso destapó **9 errores reales** que de otro modo habrían quedado escritos en las skills (ver §5).

## 2. Inventario inicial (momento 0)

| Archivo | Líneas | Contenido |
|---|---|---|
| `scaffolding-fastapi-backends/SKILL.md` | 56 | stack, orden de construcción, invariantes, errores comunes |
| `references/architecture.md` | 238 | capas, `Settings`, `main.py`, errores de dominio, Strategy, schemas |
| `references/database.md` | 221 | engine async, modelos, repositorios, Alembic, seed |
| `references/testing.md` | 133 | E2E con `TestClient` + SQLite en memoria |
| `references/observability.md` | 311 | Prometheus, Loki/Alloy, Tempo, Grafana (compose + configs) |
| `references/security.md` | 147 | OAuth2 + JWT + Argon2, hardening |
| `references/docker.md` | 212 | Dockerfile, compose, nginx de la SPA |
| `references/ci.md` | 167 | CircleCI + Coveralls + round-trip de migraciones |
| `templates/build_dashboard.py` | 117 | generador del dashboard de Grafana |

## 3. Matriz de diagnóstico de lo existente

| Archivo | Estado | Hallazgos | Destino |
|---|---|---|---|
| `SKILL.md` | **Desactualizada** | Frontmatter sin `domain/tags/triggers`; sin secciones del estándar (reglas/anti-patrones, checklist); SQLAlchemy sin fijar (2.1 rompe la instrumentación OTel) | Reescrita como skill orquestadora: `skills/backend/scaffolding-fastapi-backends` |
| `architecture.md` | **Desactualizada** | `commit` dentro de `crud/` (dos repos = dos transacciones); `crud` como funciones de módulo (difíciles de mockear); `settings` global sin stages; errores como `{"detail": str}` sin 500 global ni formato estable | `layering-fastapi-apps`, `handling-fastapi-errors`, `configuring-fastapi-settings` |
| `database.md` | **Incompleta** | Sin `naming_convention`; sin estrategia de indexación; sin `begin_nested`/`FOR UPDATE`/bloqueo optimista; ENUM nativo (`ALTER TYPE` en cada cambio); sin variante síncrona ni dimensionamiento del pool; `env.py` sin `compare_*` ni `lock_timeout` | `configuring-sqlalchemy-sessions`, `modeling-postgres-with-sqlalchemy`, `migrating-with-alembic` |
| `testing.md` | **Incompleta** | Sin tests unitarios con mocks; recrea el esquema en cada test (lento); sin rollback por test; sin factories; sin opción Postgres real | `testing-fastapi-endpoints`, `unit-testing-fastapi-services` |
| `observability.md` | **Incompleta + desactualizada** | Logs en texto plano (`trace_id` por regex); sin métricas de negocio; sin SLOs, burn-rate ni Alertmanager; imágenes viejas (Tempo 2.8: su config **no arranca** en Tempo 3.x) | `exposing-prometheus-metrics`, `logging-json-to-loki`, `tracing-with-opentelemetry`, `defining-grafana-slos` |
| `security.md` | **Completa** | Ajustes menores: `get_settings()` y login movido a `AuthService` (regla de capas) | se mantiene como referencia del scaffolding |
| `docker.md` | **Completa** | Ajuste de referencia cruzada a la nueva skill de observabilidad | se mantiene como referencia |
| `ci.md` | **Completa** | Agregado: job opcional `TEST_DB=postgres` | se mantiene como referencia |
| `build_dashboard.py` | **Incompleta** | Filtraba por regex sobre texto; sin fila SLO | Actualizado (selector `job`, labels de logs JSON, fila de SLO/burn rate) en `defining-grafana-slos/templates/` |

## 4. Vacíos frente a las directivas obligatorias

| Directiva | Antes | Ahora (skill) |
|---|---|---|
| **A. React 19:** arquitectura modular, custom hooks, composición vs prop drilling | ✗ | `architecting-react-apps` |
| A. `useRef`/`useCallback`/`useMemo` quirúrgicos | ✗ | `optimizing-react-renders` (incluye React Compiler y `useEffectEvent`) |
| A. `useActionState`, `useFormStatus`, `useOptimistic`, `use` | ✗ | `using-react-19-actions` |
| A. Error Boundaries + telemetría | ✗ | `handling-react-errors` |
| A. Axios: instancia, interceptors, refresh, backoff, errores tipados | ✗ | `building-axios-clients` |
| A. React Router: data routers, loaders, actions, layouts, rutas protegidas, code-splitting | ✗ | `routing-with-react-router` (v8) |
| A. SSR vs SPA | ✗ | `choosing-ssr-or-spa` |
| A. Índice Vercel (`skills/frontend/vercel-index.md`) | ✗ | `vercel-index.md` (mapa real de skills.sh, con los vacíos declarados) |
| **B. FastAPI:** capas `api/schemas/crud/services/models` con `Depends` | parcial | `layering-fastapi-apps` |
| B. Excepciones desacopladas + handlers globales | parcial | `handling-fastapi-errors` (RFC 9457) |
| B. `pydantic-settings` por stage | parcial (sin stages) | `configuring-fastapi-settings` |
| **C. SessionMaker async/sync + pooling** | parcial (solo async) | `configuring-sqlalchemy-sessions` |
| C. Alembic: naming conventions, autogenerate, rollback seguro | parcial | `migrating-with-alembic` |
| C. Modelado, indexación, `begin_nested`/unit of work | parcial | `modeling-postgres-with-sqlalchemy` |
| **D. Unit tests con mocks** | ✗ | `unit-testing-fastapi-services` |
| D. Integración: SQLite en memoria o testcontainers | parcial (solo SQLite) | `testing-fastapi-endpoints` (ambos, mismo conftest) |
| D. Fixtures: cliente, sesión con rollback, datos ficticios | parcial | `testing-fastapi-endpoints` |
| **E. Prometheus:** HTTP + negocio | parcial (solo HTTP) | `exposing-prometheus-metrics` |
| E. Loki: JSON + `trace_id` | ✗ (texto plano) | `logging-json-to-loki` |
| E. Tempo: OTel auto + manual (FastAPI, SQLAlchemy) | parcial (sin spans manuales) | `tracing-with-opentelemetry` |
| E. Grafana: dashboards estándar + Alertmanager (SLIs/SLOs) | parcial (sin SLO/alertas) | `defining-grafana-slos` |

## 5. Errores reales detectados al verificar

Todos aparecieron al **ejecutar** el código y ya están corregidos en las skills:

1. **OpenTelemetry + SQLAlchemy 2.1**: `opentelemetry-instrumentation-sqlalchemy` 0.66b1 solo acepta `sqlalchemy < 2.1`. Con 2.1.6 no instrumenta nada y solo deja un log de error, así que los spans SQL desaparecen. → se fija `sqlalchemy>=2.0.40,<2.1` y un test exige los spans SQL.
2. **Alembic + autobegin de SQLAlchemy 2.0**: ejecutar `SET lock_timeout` antes de `context.begin_transaction()` deja una transacción implícita abierta. Alembic no commitea y `upgrade head` se descarta **en silencio** ("Target database is not up to date"). → `connection.commit()` después del `SET`.
3. **Autogenerate no detecta CHECK constraints**, incluido el CHECK de un `Enum(native_enum=False)`, y sin `create_constraint=True` ese CHECK ni siquiera se crea. → regla explícita y migración manual con `NOT VALID` + `VALIDATE`.
4. **polyfactory 3.5**: la opción `__async_persistence__ = "flush"` no existe y se ignora en silencio (se usaba `COMMIT`). Lo correcto es `__persistence_method__ = SQLAlchemyPersistenceMethod.FLUSH`.
5. **`AsyncSession.scalar()` tipado como `Any`** en SQLAlchemy 2.0 (mypy `--strict` falla). → `(await session.scalars(stmt)).one_or_none()`.
6. **Tempo 3.x** (stable actual: 3.1.1) eliminó `compactor:`, y la config de 2.x no arranca. La retención ahora vive en `backend_scheduler`/`backend_worker`.
7. **promtool**: si los tests de reglas quedan dentro de `rules/`, el glob `rules/*.yml` los carga como reglas y Prometheus rechaza la config. → `prometheus/tests/` separado.
8. **`@vitejs/plugin-react` 6** eliminó la opción `babel`, así que la forma clásica de activar React Compiler no compila. → `@rolldown/plugin-babel` + `reactCompilerPreset()`.
9. **React Router v8** eliminó `react-router-dom`: se importa de `react-router` y `react-router/dom`. Además Starlette ya marca `httpx` como deprecado en `TestClient` (sugiere `httpx2`).

## 6. Verificación realizada

| Qué | Cómo | Resultado |
|---|---|---|
| App FastAPI de referencia (config, errores, capas, repos, services, métricas, logs, trazas) | 18 tests de pytest: unitarios con mocks, integración, observabilidad, savepoints | 18/18 en SQLite y en PostgreSQL 17 (testcontainers), también en orden aleatorio (`pytest-randomly`, 5 seeds) |
| Tipado y lint Python | `mypy --strict`, `ruff` (E,F,I,UP,B,SIM,ASYNC) | sin errores |
| Alembic | autogenerate, `upgrade`, `check`, `downgrade base`, re-`upgrade`, migración manual con `CONCURRENTLY` | OK contra PostgreSQL 17; la base rechaza un `status` inválido |
| Sesión síncrona, `SKIP LOCKED`, bloqueo optimista, opciones PgBouncer | script contra PostgreSQL 17 | OK (`StaleDataError` en el conflicto; sin solapamiento con `SKIP LOCKED`) |
| Reglas SLO y alertas | `promtool check config`, `promtool test rules` (Prometheus 3.15.1) | OK: dispara con 5 % de errores, no dispara con 0,05 % |
| Alertmanager | `amtool check-config` (0.34.1) | OK |
| Loki, Alloy | `-verify-config` (3.7.9), `alloy validate` (1.21.2); pipeline de punta a punta | `level` como label, `trace_id` como structured metadata, filtrable |
| Tempo | arranque con la config + traza OTLP enviada y consultada por API (3.1.1) | OK |
| Grafana | provisioning real (13.2.4) | 4 datasources, derived field Loki→Tempo, dashboard de 26 paneles |
| Frontend de referencia (React 19.3, React Router 8.5, Axios 1.20) | `tsc` estricto (`exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`), `vite build`, vitest | tipado OK; build con 1 chunk por ruta lazy y React Compiler aplicado; 7/7 tests del cliente HTTP |
| Bloques de código de las skills | parseo de 38 bloques Python y 13 YAML; `alloy validate` del bloque River | 0 errores |
| Formato de las skills | `scripts/validate_skills.py` | 20 skills + 1 índice, 0 errores |
| Tags de imágenes | `docker manifest inspect` / Docker Hub | todos existen |

## 7. Árbol definitivo

```text
my_skills/
├── README.md                     # índice, instalación y estándar
├── DIAGNOSTICO.md                # este informe
├── backup_old_version/           # los 9 archivos originales, intactos
├── templates/SKILL.template.md   # plantilla del estándar
├── scripts/
│   ├── validate_skills.py        # valida frontmatter, secciones y links
│   └── install.sh                # symlinks a ~/.claude/skills (o --target)
└── skills/
    ├── frontend/
    │   ├── vercel-index/SKILL.md
    │   ├── architecting-react-apps/SKILL.md
    │   ├── optimizing-react-renders/SKILL.md
    │   ├── using-react-19-actions/SKILL.md
    │   ├── handling-react-errors/SKILL.md
    │   ├── building-axios-clients/SKILL.md
    │   ├── routing-with-react-router/SKILL.md
    │   └── choosing-ssr-or-spa/SKILL.md
    ├── backend/
    │   ├── scaffolding-fastapi-backends/{SKILL.md, references/{security,docker,ci}.md}
    │   ├── layering-fastapi-apps/SKILL.md
    │   ├── handling-fastapi-errors/SKILL.md
    │   └── configuring-fastapi-settings/SKILL.md
    ├── database/
    │   ├── configuring-sqlalchemy-sessions/SKILL.md
    │   ├── modeling-postgres-with-sqlalchemy/SKILL.md
    │   └── migrating-with-alembic/SKILL.md
    ├── testing/
    │   ├── testing-fastapi-endpoints/SKILL.md
    │   └── unit-testing-fastapi-services/SKILL.md
    └── observability/
        ├── exposing-prometheus-metrics/SKILL.md
        ├── logging-json-to-loki/SKILL.md
        ├── tracing-with-opentelemetry/SKILL.md
        └── defining-grafana-slos/{SKILL.md, references/stack.md, templates/build_dashboard.py}
```

Decisiones de estructura:

- **`skills/<dominio>/<skill>/SKILL.md`**: cumple la división por dominio exigida. Como los runtimes de agentes descubren skills en un namespace **plano**, `scripts/install.sh` enlaza cada skill por nombre en `~/.claude/skills/`.
- **Nombres en gerundio** (`handling-…`, `configuring-…`): convención de skills orientada a la acción. El `name` coincide con el directorio y el validador lo exige.
- **`domain`, `tags` y `triggers` como claves de primer nivel**, según el estándar pedido. Claude Code ignora las claves que no reconoce. Un validador estricto de la especificación agentskills.io podría exigir moverlas dentro de `metadata:`.
- **Contenido en español y código en inglés**, igual que la skill original.

## 7 bis. Refinamiento contra un proyecto real (2026-11-01)

Las skills se contrastaron con TurnApp (backend y frontend en producción de desarrollo, todo en verde). Se encontraron **73 inconsistencias**; 8 eran bugs del código publicado, comprobados al ejecutarlo:

| Bug | Skill | Antes | Ahora |
|---|---|---|---|
| `repr(settings)` mostraba la contraseña (`computed_field` sin `repr=False`) | `configuring-fastapi-settings` | aparece | no aparece |
| 7 campos que otras skills leen no existían en `Settings` | `configuring-fastapi-settings` | `AttributeError` | test de contrato sobre todas las skills |
| `APP_ENV=test` cargaba el `.env` local | `configuring-fastapi-settings` | `.env` aplicado | `_env_file=None` en test |
| `DateTime(timezone=True)` perdía la zona en SQLite (`12:00-03:00` → `12:00`) | `modeling-postgres-with-sqlalchemy` | otro instante | `UtcDateTime` |
| `onSessionExpired` se llamaba una vez por request en 401 simultáneos | `building-axios-clients` | 3 llamadas | 1 |
| Abortar durante el backoff salía como `CanceledError` crudo | `building-axios-clients` | sin tipar | `ApiRequestError` `canceled` |
| La boundary reportaba 2 veces al navegar a una página rota | `handling-react-errors` | 2 | 1 |
| `<form action>` borraba lo escrito aun con un error devuelto | `using-react-19-actions` | `""` | se conserva |

Los 8 tienen test en `tests/snippets/` (rojo antes del arreglo, verde después). Además: refresh rotado y Argon2 fuera del event loop en `security.md`, 401 como error de dominio, layout monorepo y nginx robusto en `docker.md`, índices de FK condicionales, serialización de invariantes sobre rangos, observabilidad condicionada al alojamiento y `safeNext` contra open redirect.

**No verificado en esta corrida:** las reglas de las skills con agentes bajo presión (los micro-tests de comportamiento del plan no se corrieron); `SLO-1` (burn rate con poco tráfico) es un riesgo previsto sin medir; la combinación SPA + `/api` + cookie `SameSite=strict` en Vercel no se desplegó.

## 8. Pendientes y riesgos

| Ítem | Detalle | Recomendación |
|---|---|---|
| Pruebas de comportamiento con agentes | Se verificó el **código**, no si un agente sigue las skills bajo presión (metodología RED/GREEN de `writing-skills`) | Correr escenarios con subagentes por skill, empezando por las de disciplina (capas, errores, testing) |
| Snippets no compilados | Framework mode de React Router (`choosing-ssr-or-spa`, depende de tipos generados `./+types`), integración con Sentry, `gunicorn.conf.py` multiproceso | Compilarlos en un proyecto framework-mode real antes de la próxima revisión |
| Proyectos de referencia fuera del repo | Viven en el scratchpad de la sesión | Versionarlos en `examples/` y correrlos en CI: así los snippets no se desactualizan |
| `docker.md` / `ci.md` | El nginx se validó con `nginx -t` y el compose con `docker compose config` (2026-11-01). No se re-verificaron el orb de Coveralls ni la imagen de CircleCI | Revisar tags en el próximo proyecto que los use |
| Una corrida con errores en Postgres | Una ejecución de la suite contra testcontainers dio errores de setup; no se reprodujo en 8 corridas posteriores | Si reaparece, revisar el arranque del contenedor Ryuk |
| Catálogo de Vercel | Relevado el 2026-10-23; cambia seguido | Re-relevar trimestralmente |
| Instalación | `install.sh` no se ejecutó sobre `~/.claude/skills`: allí hay una copia real de la skill vieja que requiere `--force` | Ejecutar `bash scripts/install.sh --force` cuando se decida |

## 9. Refinamiento 2026-11-01 (auditoría de consistencia)

Una auditoría de consistencia entre las 20 skills (informes y plan en `docs/plans/2026-11-01-refinamiento-skills/`) corrigió datos de las secciones 5 a 7 sin reescribirlas: esas secciones quedan como el registro de lo que se dijo el 2026-10-23. El detalle de cada hallazgo, su evidencia y su arreglo están en esa carpeta; acá solo van los datos que cambian.

| Dato | Lo que decían §5 a §7 | Dato corregido |
|---|---|---|
| Bloques que parsean (§6, "parseo de 38 bloques Python y 13 YAML [...] 0 errores") | 38 Python, 0 errores | Hay **46** bloques `python` y 13 YAML. Uno de los 46 no parseaba (`testing-fastapi-endpoints`, el `conftest.py` con el comentario dentro del `with`). Corregido; `test_every_python_block_parses` recorre ahora todos los `.md` de `skills/` (Python, YAML, TOML y JSON) |
| Versión de PostgreSQL (§6, "PostgreSQL 17") | 17 | La **referencia es 16** (la serie que publican `docker.md`, `ci.md` y el conftest; el tag exacto está en la fila siguiente). El proyecto de referencia pasa en SQLite y en PostgreSQL 16 por testcontainers. Lo que se verificó a mano contra 17 (`migrating-with-alembic`, variante síncrona de `configuring-sqlalchemy-sessions`) conserva su fecha hasta que se re-corra |
| Tests (§6, "18 tests"; §7 bis, "7/7 tests del cliente HTTP") | 18 y 7 | Esos tests vivían en proyectos fuera del repo. Lo versionado y ejecutable es `tests/snippets/` (ver abajo). Las skills ya no escriben conteos |
| Árbol definitivo (§7) | Sin `tests/snippets/` | Ver el árbol de abajo |
| "Verificado" (README, skills) | Una sola palabra, sin criterio | Dos etiquetas: `verificado (test)` y `verificado a mano (fecha, herramienta)`. Cada mención está registrada en `tests/snippets/verified_claims.py` |
| Job de Postgres en CI (§3, `ci.md`: "job opcional `TEST_DB=postgres`") | Una frase, sin YAML | `ci.md` trae `test-postgres` (executor `machine`, `TEST_DB: postgres`), siempre obligatorio, junto con `lint`; el YAML solo se validó como sintaxis, no en CircleCI |
| Tag de PostgreSQL (fila anterior: `postgres:16-alpine`) | Tag móvil en compose y conftest, `cimg/postgres:16.4` en CI | **`16.15`** exacto y el mismo en `docker.md` (`postgres:16.15-alpine`), `ci.md` (`cimg/postgres:16.15`) y el conftest de `testing-fastapi-endpoints` |
| Compose (§3, `docker.md`) | Publicaba la base y el backend (saltea el límite de login) | Solo `frontend` publica puertos; los de la base y el backend, el volumen y `--reload` van en `docker-compose.override.yml` (desarrollo) |
| `uv sync --frozen` (§3, `ci.md` y `docker.md`: "un lock desactualizado rompe el build") | `--frozen` no falla con un lock viejo | `--locked` |
| Pin de SQLAlchemy en el arnés | Sin pin; resolvía 2.1.6, que las skills excluyen | `sqlalchemy>=2.0.40,<2.1` |
| Frontend del arnés | Vite 7 y `@vitejs/plugin-react` 5; sin `tsc` en la suite | Vite 8, `@vitejs/plugin-react` 6, Vitest 5 y `tsc --noEmit` antes de `vitest run`, con `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess` y `erasableSyntaxOnly` |
| Test de contrato de `Settings` (§7 bis, "test de contrato sobre todas las skills") | Solo leía `SKILL.md` y `settings.X` | Lee todos los `.md` (incluido `references/`) y `templates/*.py`, y también `get_settings().X` |

Árbol de lo que se agregó (el resto de §7 no cambia):

```text
tests/snippets/
├── extract.py                     # extrae bloques de SKILL.md y de references/
├── generate.py                    # escribe web/generated/ con el TypeScript de las skills
├── conftest.py                    # reference/ y web/ tienen su propia suite
├── test_python_snippets.py        # bloques que parsean, Settings, UtcDateTime
├── test_verified_claims.py        # toda mención "verificado" está registrada
├── test_wave2_contracts.py        # ola 2: pines, tags, .env.example, tablas de pytest, YAML de compose y CI
├── test_wave2_project.py          # ola 2: clon limpio con uv (bootstrap, lint-imports, app por pasos, compose, Alembic)
├── verified_claims.py             # el registro
├── reference/                     # proyecto FastAPI armado desde los bloques
│   ├── build_ref.py, run.sh, pyproject.toml, uv.lock
│   ├── xfail_plugin.py            # fallos conocidos, con el ID del hallazgo
│   └── wave2_tests/               # tests que build_ref copia al proyecto (auth, lifespan, flags, capas)
└── web/                           # vitest + tsc sobre el código de las skills
    ├── typecheck.mjs, tsconfig.json, package.json
    └── tests/
```

Correcciones de este refinamiento a datos de las secciones anteriores:

- §6, dashboard de Grafana: ahora son **30 paneles en 8 filas** (se agregó la fila de latencia del SLO y el orden sigue lo declarado en la skill); el "26 paneles" de §6 y de la fila de Grafana corresponde a la versión anterior.
- §8, catálogo de Vercel: re-relevado el **2026-11-01** (20 fuentes, 65 skills; los 26 slugs de las tablas existen). `create-a-backend` existe, pero no se pudo confirmar que cubra Python/FastAPI.

Sin verificar en este refinamiento: los enlaces de Grafana (traza→logs y exemplars), CircleCI (`test-postgres` con `machine`), la carrera de redirección al expirar la sesión en un navegador real, el framework mode de `choosing-ssr-or-spa` y PgBouncer anterior a 1.21. Las pruebas de comportamiento con agentes bajo presión (§8) tampoco se corrieron.

El detalle de cada inconsistencia y su corrección está en `docs/plans/2026-11-01-refinamiento-skills/`.

## 10. Auditoría de orquestación (2026-11-22)

Cinco auditores (frontend, backend, scaffolding, bases de datos, observabilidad) revisaron cómo encajan las skills entre sí, no cada una por separado. Informe de evidencia: ~50 inconsistencias, 6 de ellas rompían el código al ejecutarlo. El plan y el estado de cada ítem están en `docs/plans/2026-11-22-orquestacion/PLAN.md`; acá solo lo que cambia respecto de §1 a §9.

| Dato | Antes | Ahora |
|---|---|---|
| Stage del compose desplegado | Sin `APP_ENV`: arrancaba en `dev` (cookie sin `Secure`, `/docs` público, guardas de producción sin correr) | `APP_ENV: prod` en `docker-compose.yml`, `dev` en el override; TLS declarado delante de nginx (que reenvía el `X-Forwarded-Proto` del terminador) |
| Migraciones tras PgBouncer | El `ALTER ROLE … statement_timeout` también cortaba `CREATE INDEX CONCURRENTLY` | `env.py` fija `SET statement_timeout = 0` junto a `lock_timeout` (online y offline); test en W3 contra Postgres |
| Variante síncrona | Ignoraba `DB_PGBOUNCER`; `engine.sync_engine` y `await engine.dispose()` fallaban | Rama PgBouncer síncrona (`NullPool`, `prepare_threshold=None`); `setup_tracing` acepta `AsyncEngine \| Engine` |
| `httpx` | Solo en `dev`, pero lo importa el instrumentor de tracing (la imagen usa `--no-dev`) | En `dependencies`; lo exige un test de contrato |
| Multiproceso en la imagen | La receta de métricas no entraba en el Dockerfile | Subsección "Varios workers" en `docker.md` (`COPY gunicorn.conf.py`, vaciado de `PROMETHEUS_MULTIPROC_DIR`, `-b 0.0.0.0:8000`) |
| Orden de construcción | 9 pasos; el frontend no figuraba; `uv init my-api` vs `backend/` | **10 pasos**, con "7 · Frontend" (SPA con data mode por defecto); `uv init --bare backend` + `uv python pin 3.14`; Postgres en contenedor desde el paso 3 |
| Piezas usadas pero sin dueño | `User/Role/Permission`, `AuthServiceDep`, logout, recurso `products`, `InsufficientStockError`, `assertNever`, `installation` | Publicadas (`security.md`, `layering-fastapi-apps`, `handling-fastapi-errors`, `building-axios-clients`, `APP_INSTALLATION` en `Settings`) y extraídas por `build_ref.py` en vez de pegamento |
| Primera visita sin sesión | Doble redirección al login | `redirectToLogin` no navega si `!router.state.initialized`; test que falla sin el arreglo |
| Telemetría del front | `unauthorized` y `canceled` llegaban a `reportError` | `isNotAFailure` los descarta; el stack declara que no recibe telemetría del navegador |
| `vercel-index` | `skills/frontend/vercel-index.md` (fuera de la convención) | `skills/frontend/vercel-index/SKILL.md`; `install.sh` migra el enlace viejo |
| Pines en tests | PgBouncer `:latest` | `edoburu/pgbouncer:v1.26.1-p0` |

**Resultado de la verificación (2026-11-23):** pytest sobre `tests/snippets` 136 passed (antes 123); proyecto de referencia 31 passed + 2 skipped en SQLite y 33 passed con `TEST_DB=postgres`, con `mypy --strict` sin errores en 47 archivos; frontend 72 passed (antes 67), con `tsc` y ESLint de arquitectura, ahora también sobre `generated/`; `validate_skills.py` 21 skills, 0 errores. Los tests nuevos de B1, B2, D1, E4 y E5 se comprobaron en rojo contra las skills anteriores.

**Cerrado en una segunda pasada (2026-11-23):**

- Un revisor independiente leyó el diff completo: sin contradicciones graves; sus hallazgos menores (import faltante en el ejemplo de `onExport`, fragmento de `vite.config.ts` sin marcar, método `expire_pending` sin aclarar dónde va) están corregidos.
- `appDirectory: "src"` de `choosing-ssr-or-spa` se verificó con `react-router build` (`@react-router/dev` 8.5.2): las rutas salen de `src/`, el build va a `build/client` y las rutas de `prerender` generan su `index.html`.
- `tracing.py` pasó a `verificado (test)`: un test levanta Tempo 3.1.1 con la config de `stack.md`, envía por OTLP con el código publicado y recupera la traza por `/api/v2/traces/<id>`.
- La redirección al login del middleware usa `replace` (como antes con `router.navigate`), no `redirect`.

**Decisiones y límites que quedan:**

- Permisos como `StrEnum` + lista JSON, no la tabla puente `role_permissions` que pedía el plan: es lo que usan los tests y `/me`.
- `expire_pending` se publica como fragmento aparte y `build_ref.py` lo une a `OrderRepository` con pegamento; moverlo a layering acoplaría esa skill al worker.
- FastAPI 0.165 trae telemetría OpenTelemetry nativa (`fastapi.telemetry`) que emite spans aunque no se instrumente la app, ignorando `excluded_urls`; las skills lo documentan, no se probó con otras versiones.
- Siguen sin verificarse CircleCI, la UI de Grafana y un navegador real.
