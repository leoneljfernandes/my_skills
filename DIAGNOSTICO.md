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
    │   ├── vercel-index.md
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

## 8. Pendientes y riesgos

| Ítem | Detalle | Recomendación |
|---|---|---|
| Pruebas de comportamiento con agentes | Se verificó el **código**, no si un agente sigue las skills bajo presión (metodología RED/GREEN de `writing-skills`) | Correr escenarios con subagentes por skill, empezando por las de disciplina (capas, errores, testing) |
| Snippets no compilados | Framework mode de React Router (`choosing-ssr-or-spa`, depende de tipos generados `./+types`), integración con Sentry, `gunicorn.conf.py` multiproceso | Compilarlos en un proyecto framework-mode real antes de la próxima revisión |
| Proyectos de referencia fuera del repo | Viven en el scratchpad de la sesión | Versionarlos en `examples/` y correrlos en CI: así los snippets no se desactualizan |
| `docker.md` / `ci.md` | No se re-verificaron (nginx, orb de Coveralls, imagen de CircleCI) | Revisar tags en el próximo proyecto que los use |
| Una corrida con errores en Postgres | Una ejecución de la suite contra testcontainers dio errores de setup; no se reprodujo en 8 corridas posteriores | Si reaparece, revisar el arranque del contenedor Ryuk |
| Catálogo de Vercel | Relevado el 2026-10-23; cambia seguido | Re-relevar trimestralmente |
| Instalación | `install.sh` no se ejecutó sobre `~/.claude/skills`: allí hay una copia real de la skill vieja que requiere `--force` | Ejecutar `bash scripts/install.sh --force` cuando se decida |
