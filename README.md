# my_skills: biblioteca de skills de desarrollo

Skills y directivas production-ready para agentes de código (Claude Code y compatibles) sobre un stack **React 19 + FastAPI + PostgreSQL + Prometheus/Loki/Tempo/Grafana**. Cada skill trae reglas, anti-patrones, ejemplos tipados verificados y un checklist de cierre.

El diagnóstico de la versión anterior y la verificación realizada están en [DIAGNOSTICO.md](DIAGNOSTICO.md).

## Skills

| Dominio | Skill | Usar cuando |
|---|---|---|
| frontend | [architecting-react-apps](skills/frontend/architecting-react-apps/SKILL.md) | estructura de features, custom hooks, composición vs prop drilling |
| frontend | [optimizing-react-renders](skills/frontend/optimizing-react-renders/SKILL.md) | re-renders, `useMemo`/`useCallback`/`useRef`, React Compiler |
| frontend | [using-react-19-actions](skills/frontend/using-react-19-actions/SKILL.md) | formularios y mutaciones: `useActionState`, `useFormStatus`, `useOptimistic`, `use` |
| frontend | [handling-react-errors](skills/frontend/handling-react-errors/SKILL.md) | Error Boundaries, fallback UI, reporte a telemetría |
| frontend | [building-axios-clients](skills/frontend/building-axios-clients/SKILL.md) | instancia Axios, refresh token, retry con backoff, errores tipados |
| frontend | [routing-with-react-router](skills/frontend/routing-with-react-router/SKILL.md) | loaders, actions, layouts, rutas protegidas, code-splitting (v8) |
| frontend | [choosing-ssr-or-spa](skills/frontend/choosing-ssr-or-spa/SKILL.md) | decidir SPA, pre-render, SSR (React Router framework) o Next.js |
| frontend | [vercel-index](skills/frontend/vercel-index/SKILL.md) | elegir e instalar la skill oficial de Vercel correcta |
| backend | [scaffolding-fastapi-backends](skills/backend/scaffolding-fastapi-backends/SKILL.md) | proyecto FastAPI nuevo de punta a punta (incluye auth, Docker, CI) |
| backend | [layering-fastapi-apps](skills/backend/layering-fastapi-apps/SKILL.md) | dónde va cada pieza: `api`, `schemas`, `services`, `crud`, `models` |
| backend | [handling-fastapi-errors](skills/backend/handling-fastapi-errors/SKILL.md) | excepciones de dominio, handlers globales, problem+json |
| backend | [configuring-fastapi-settings](skills/backend/configuring-fastapi-settings/SKILL.md) | `pydantic-settings` por stage, secretos |
| database | [configuring-sqlalchemy-sessions](skills/database/configuring-sqlalchemy-sessions/SKILL.md) | engine, pool, sesiones async/sync, PgBouncer |
| database | [modeling-postgres-with-sqlalchemy](skills/database/modeling-postgres-with-sqlalchemy/SKILL.md) | modelos, constraints, índices, transacciones y locking |
| database | [migrating-with-alembic](skills/database/migrating-with-alembic/SKILL.md) | migraciones, autogenerate, zero-downtime, rollback |
| testing | [testing-fastapi-endpoints](skills/testing/testing-fastapi-endpoints/SKILL.md) | integración con SQLite en memoria o testcontainers, rollback por test, factories |
| testing | [unit-testing-fastapi-services](skills/testing/unit-testing-fastapi-services/SKILL.md) | lógica de negocio con mocks (`pytest-mock`, autospec) |
| observability | [exposing-prometheus-metrics](skills/observability/exposing-prometheus-metrics/SKILL.md) | métricas HTTP (RED) y de negocio |
| observability | [logging-json-to-loki](skills/observability/logging-json-to-loki/SKILL.md) | logs JSON correlados por `trace_id` |
| observability | [tracing-with-opentelemetry](skills/observability/tracing-with-opentelemetry/SKILL.md) | trazas OTel → Tempo, spans manuales |
| observability | [defining-grafana-slos](skills/observability/defining-grafana-slos/SKILL.md) | SLOs, burn-rate alerts, Alertmanager, dashboards como código, stack completo |

## Instalación

Los agentes descubren skills en un directorio plano. El instalador crea un symlink por skill, así que editar el repo actualiza las skills instaladas.

```bash
bash scripts/install.sh --dry-run                    # ver qué haría
bash scripts/install.sh                              # ~/.claude/skills
bash scripts/install.sh --target ~/.agents/skills    # Codex / Gemini CLI / Copilot CLI
```

Si en el destino ya existe un directorio real con el mismo nombre (por ejemplo, una copia vieja de `scaffolding-fastapi-backends`), se omite. `--force` lo respalda en `<destino>/.backup-<fecha>/` y lo reemplaza por el symlink.

## Estándar de una skill

Cada `skills/<dominio>/<nombre>/SKILL.md` sigue [templates/SKILL.template.md](templates/SKILL.template.md):

1. **Frontmatter YAML**: `name` (= directorio, minúsculas y guiones), `description` (empieza con "Use when…", solo describe cuándo usarla, máx. 1024 caracteres), `domain` (= directorio padre), `tags`, `triggers`.
2. **`## Contexto y reglas`**: qué hacer (con el porqué) y tabla de anti-patrones.
3. **`## Ejemplos`**: código production-ready tipado (TypeScript estricto / type hints), **ejecutado** antes de publicarse y con su etiqueta de verificación (ver Contribuir).
4. **`## Checklist de verificación`**: criterios observables para dar la tarea por terminada.

Archivos de apoyo solo si hacen falta: `references/` para material extenso y `templates/` para código reutilizable.

## Contribuir

1. Copiar la plantilla a `skills/<dominio>/<nombre-en-gerundio>/SKILL.md`.
2. Verificar cada ejemplo en un proyecto real (tests, `mypy --strict` / `tsc --strict`, linters, o la herramienta de validación del producto: `promtool`, `amtool`, `alloy validate`…).
3. Validar el formato:

   ```bash
   uv run --with pyyaml python scripts/validate_skills.py
   ```

4. Decir en el texto qué se verificó, con una de dos etiquetas:

   - **`verificado (test)`**: hay un test en `tests/snippets/` que ejecuta el bloque. Los tests extraen el código de las `SKILL.md` (no una copia), así que un arreglo en la skill los ejerce.
   - **`verificado a mano (AAAA-MM-DD, herramienta)`**: corrida única, sin test en el repo (`promtool`, `amtool`, `alloy validate`, `vite build`, un stack levantado…). Vale por su fecha.

   Toda mención de "verificado" en `skills/` se registra en `tests/snippets/verified_claims.py`; `test_verified_claims_are_registered` falla si falta, si la etiqueta no coincide o si el test citado dejó de existir. No se escriben conteos de tests en las skills: envejecen.

   ```bash
   # Python: toda la suite de tests/snippets (bloques, contratos, proyecto de referencia, migraciones, observabilidad).
   # Las pruebas de Docker (Postgres, Alertmanager, promtool, compose) se saltean si no hay Docker.
   uv run --with pytest --with pytest-asyncio --with pytest-mock --with pydantic-settings --with fastapi \
     --with 'sqlalchemy>=2.0.40,<2.1' --with pyyaml --with aiosqlite --with httpx --with ruff --with mypy \
     --with polyfactory --with asyncpg --with 'psycopg[binary]' --with testcontainers --with alembic \
     --with import-linter --with opentelemetry-sdk pytest tests/snippets -q
   # Proyecto de referencia armado desde las SKILL.md: pytest en SQLite + mypy --strict
   tests/snippets/reference/run.sh                  # TEST_DB=postgres con Docker: PostgreSQL 16 por testcontainers
   # SKILLS_DIR=<copia de skills/> corre cualquiera de los anteriores contra una copia (p. ej. con un arreglo revertido)
   # Frontend: tsc --noEmit + ESLint (lint.mjs) + vitest sobre el código de las skills
   cd tests/snippets/web && npm install && npm test
   ```

   Si una prueba falla por un hallazgo conocido de una skill, se marca `xfail` estricto (`reference/xfail_plugin.py`, `web/typecheck.mjs`) con el ID del hallazgo; al corregir la skill pasa a verde y se borra la entrada. Hoy no hay ninguna.
5. Actualizar la tabla de este README.
