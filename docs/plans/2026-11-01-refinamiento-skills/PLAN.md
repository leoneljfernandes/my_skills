# Plan de corrección de inconsistencias en las skills

**Estado:** aplicado (sin commit) el 2026-11-01, con todas las recomendaciones aprobadas. Lo que no se pudo verificar está en DIAGNOSTICO.md §9.
**Base:** commit `54d8c96`, 2026-11-01.
**Evidencia completa** (citas con archivo:línea y cómo se confirmó cada hallazgo): [backend](auditoria/backend.md), [frontend](auditoria/frontend.md), [database](auditoria/database.md), [observability](auditoria/observability.md), [testing](auditoria/testing.md).

## 1. Resumen

Los 5 auditores reportaron **116 hallazgos**. Al quitar 21 duplicados quedan **95 inconsistencias**: 12 altas, 50 medias y 33 bajas.

El grueso del código publicado funciona. Los problemas se concentran en cuatro patrones:

1. **El sello "verificado" no protege nada.** 23 de 27 menciones no tienen test, y por eso un `SyntaxError` en el conftest sobrevivió desde `edd80d7`.
2. **Las piezas no encajan al combinarlas.** `lifespan`, `app/models/__init__.py`, el login y `ordersApi.notify` se usan, pero ninguna skill los publica.
3. **El ejemplo contradice la regla que tiene al lado.** Por ejemplo, `VALIDATE` en la misma transacción que `NOT VALID`, o los mocks de repositorio que la regla prohíbe.
4. **Hay decisiones nuevas sin propagar.** Por ejemplo, cómo clasificar los errores esperables en una action, o el pin de SQLAlchemy.

### Las 12 inconsistencias altas

| ID | Qué pasa |
|---|---|
| TS-01 · DB-01 | El `conftest.py` "verificado" no compila, así que no corre ningún test |
| BE-01 · TS-02 · TS-16 | `uv run pytest` falla con `No module named 'app'`; CI lo tapa con `PYTHONPATH` |
| BE-02 · TS-10 | El bootstrap no instala lo que declara el `pyproject` (`EmailStr` y `coverage` fallan) |
| DB-02 | `VALIDATE` junto a `NOT VALID` bloquea lecturas y escrituras: lo contrario de lo que afirma el ejemplo |
| DB-03 | Tras un `lock_timeout`, reintentar falla o deja un índice inválido con `alembic check` en verde |
| DB-04 | Detrás de PgBouncer, `lock_timeout` se filtra a otros clientes de la conexión compartida |
| OB-01 | Las reglas SLI pierden `job`: la inhibición no funciona y dos servicios colisionan |
| OB-02 | El salto de traza a logs consulta `orders-api`, pero el label de Loki es `backend` |
| FE-01 | Hay dos dueños de la redirección al expirar la sesión, y uno guarda un `next` equivocado |
| FE-02 | La action de ejemplo pierde el formulario en un 409 y no muestra nada en un 422 sin campo |
| FE-03 | `NewProductForm` resetea durante el render: borra lo que se está escribiendo |
| FE-04 | Una contraseña incorrecta o un 429 terminan en la Error Boundary |

## 2. Qué comprobó el orquestador

Además de los 5 auditores, se reprodujo lo siguiente por separado:

| Comprobación | Resultado |
|---|---|
| `SyntaxError` en `testing-fastapi-endpoints:116` | Confirmado; entró en `edd80d7` |
| Evidencia textual de OB-01, DB-02, DB-03, DB-04, FE-01, FE-02, FE-03 y FE-04 | Coincide con las líneas citadas. Son comprobaciones por lectura; la conducta la ejecutaron los auditores |
| `uv init` con uv 0.12.24 | Crea `src/` y `[build-system]`; `--bare` solo crea `pyproject.toml` |
| `uv sync --frozen` con un lock viejo (BE-04) | Sale con 0; `--locked` sale con 1 |
| `AsyncMock(spec=)` frente a `create_autospec` (TS-11) | El primero acepta una firma incorrecta; el segundo da `TypeError` |
| Sesión por request (TS-04) en el proyecto de referencia, SQLite y PostgreSQL 16 | Detecta la mutación `commit→flush`, conserva los datos tras el 409 y pasa junto con el test de tracing adaptado |

Con esa sesión por request, en la suite completa solo falla `test_500.py`. Ese test demuestra TS-15 y se espera que falle hasta corregirlo.

**No se verificó:** la UI de Grafana (los enlaces de OB-02 y OB-05), CircleCI, un navegador real (carrera de FE-01, cookies), los bloques de framework mode de `choosing-ssr-or-spa`, Alloy de punta a punta, PostgreSQL 17 y el catálogo de skills.sh. Tampoco se ejecutó la mayoría de las correcciones propuestas: cada una lleva su prueba para hacerlo al aplicarla.

## 3. Contradicciones entre auditores, ya resueltas

| # | Conflicto | Resolución |
|---|---|---|
| C1 | BE-01 dice que `uv init` no crea build-system; TS-02 dice que sí | **TS-02 tiene razón** (comprobado). El bootstrap pasa a `uv init --bare` |
| C2 | Tras el 409, DB-11 cambia `handling-fastapi-errors` a `begin_nested`; TS-05 dice que el `rollback` está bien y que falla el fixture | **TS-05.** La sesión por request lo resuelve sin tocar el service (comprobado). Sujeto a D15 |
| C3 | BE-18 conserva `create_app(settings)` y acota el texto; TS-08 quita el parámetro | **Se recomienda TS-08:** nadie lo usa y hoy promete algo falso. Sujeto a D11 |
| C4 | FE-11 dice "solo un 401 del refresh termina la sesión"; BE-09 agrega un 401 que no la termina | **Se combinan.** 401 `session_rotated`: esperar y reintentar una vez. Otro 401: sesión terminada. Otro error: propagarlo sin cerrar sesión |
| C5 | OB-11 suma un paquete a `uv add`; BE-02 elimina esa lista | **BE-02.** Una sola lista en el `pyproject`; `opentelemetry-api` entra ahí |
| C6 | Orden del apagado en `lifespan`: BE-07 y OB-10 difieren | **OB-10:** `engine.dispose()` y al final `shutdown_tracing()`, para no perder spans. Sin ejecutar: lo cubre la prueba de BE-07 |
| C7 | "Verificado": DB-12 pide tests, OB-20 y TS-12 aceptan dos niveles, FE-21 mezcla | **Una sola regla** (D01). Severidad unificada en media |
| C8 | TS-20 propone reescribir `DIAGNOSTICO.md` §5 a §7 | **No reescribir el historial.** Es un informe con fecha: se agrega una sección nueva que lo corrige |

## 4. Decisiones que necesito de vos

**Si estás de acuerdo con las recomendaciones, alcanza con decir "aprobadas" e indicar las excepciones.** Las marcadas con ★ cambian la arquitectura o afectan a varias skills.

| # | Decisión | Recomendación | Hallazgos |
|---|---|---|---|
| ★ D01 | ¿Qué significa "verificado"? | Dos etiquetas: `verificado (test)` y `verificado a mano (fecha, herramienta)`. Versionar un proyecto de referencia armado desde los bloques | TS-12 y otros |
| ★ D02 | Versión de PostgreSQL de referencia | 16, con tag exacto igual en compose, CI y conftest | TS-20, BE-23 |
| D03 | ¿El arnés frontend usa Vite 8 y plugin-react 6? | Sí, es lo que las skills prescriben | TS-14 |
| D04 | Recurso ajeno: ¿404 o 403? | 404, porque no revela si existe | BE-05 |
| D05 | `APP_ENV` escrito en `.env` | Fallar con un error claro si difiere del entorno real | BE-06 |
| D06 | Ruta de salud | `/health/*`, fuera de `/api/v1` | BE-07 |
| ★ D07 | Refresh dentro de `REUSE_GRACE` | 401 con código `session_rotated` y un reintento del cliente | BE-09 |
| D08 | Job de Postgres en CI | Siempre obligatorio | BE-11 |
| D09 | Puertos y `--reload` en compose | Moverlos a un `docker-compose.override.yml` de desarrollo | BE-13 |
| D10 | `/docs` en cada stage | Flag `DOCS_ENABLED`; se quita `is_prod` | BE-14 |
| D11 | `create_app(settings)` | Quitar el parámetro; la configuración se fija por entorno | BE-18 |
| D12 | Metadatos HTTP en las excepciones de dominio | Aceptarlos y corregir la frase "no saben nada de HTTP" | BE-24 |
| ★ D13 | Modo PgBouncer | Mantenerlo, con `DB_PGBOUNCER` y `DB_MIGRATION_HOST/PORT`; las migraciones van directo a Postgres. Alternativa: quitar el modo | DB-04, DB-06 |
| D14 | Variante síncrona | Mantenerla como camino completo, con `DB_DRIVER` | DB-07 |
| ★ D15 | Fixture de test | Una sesión por request sobre una conexión compartida; `handling-fastapi-errors` no cambia | TS-04, TS-05 |
| ★ D16 | Mocks de repositorio | Prohibidos en casos de uso que escriben; se reescribe el ejemplo central | TS-03 |
| D17 | polyfactory | Mantenerlo, con un bloque ejecutable que resuelve los choques | TS-06 |
| ★ D18 | Redirección al expirar la sesión | Siempre con el router, limpiando el estado de forma explícita | FE-01 |
| ★ D19 | `useActionState` dentro de rutas de datos | Solo si la mutación no cambia datos de ningún loader | FE-05 |
| ★ D20 | Imports del frontend | Alias `@/` en toda la biblioteca; `routes/` también pasa por `index.ts` | FE-06 |
| D21 | ¿Reportar 403 desde el navegador? | No, ya los registra el backend | FE-08 |
| D22 | ¿SSR autenticado? | No por ahora: sitio público en SSR, app privada en SPA | FE-13 |
| D23 | `NotifyButton` | `useTransition` | FE-14 |
| D24 | Default para proyecto nuevo sin preferencia | React Router framework mode | FE-19 |
| D25 | `signal` en `api.ts` | En todas las lecturas; en mutaciones solo si cancelar es seguro | FE-22 |
| D26 | Salto de traza a logs | `customQuery` por `trace_id`, sin renombrar servicios | OB-02 |
| D27 | Retención de Prometheus | 35 días | OB-04 |
| D28 | Exemplars | Solo desde spanmetrics de Tempo | OB-05 |
| D29 | Buckets de latencia | `lowr` para SLO y por endpoint; `highr` para percentiles globales | OB-06 |
| D30 | Ejemplo de SLO | Completo, unas 40 líneas más, sin `… idem` | OB-07 |
| D31 | Apagar `/metrics` sin contenedores propios | Flag `METRICS_ENABLED` con import diferido | OB-11 |
| D32 | Multiproceso | gunicorn + `uvicorn-worker` | OB-12 |
| D33 | `env` como label de Loki | No; queda en el JSON | OB-17 |
| D34 | Trigger de Promtail | Mantenerlo, con la línea "migrar a Alloy" | OB-24 |

## 5. Plan por inconsistencia

El orden sigue las dependencias. Primero va el arnés, para que cada arreglo se pueda probar en rojo y en verde. Después vienen los contratos del backend, de los que dependen los demás dominios.

Abreviaturas: `scaffolding`, `layering`, `handling`, `settings` (= `configuring-fastapi-settings`), `sessions`, `modeling`, `migrating`, `endpoints` (= `testing-fastapi-endpoints`), `unit`, `metrics`, `logging`, `tracing`, `slos`, `stack`, `dashboard`, `axios`, `routing`, `actions`, `errors`, `arch`, `renders`, `ssr`.

### Ola 1: arnés y verificación (6)

**TS-01 · DB-01, alta: el conftest "verificado" no compila**
`endpoints:116`: `with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:  # = la versión de producción`.
Prueba: nuevo `test_every_python_block_parses`, que recorre `SKILL.md` y `references/`. Hoy detecta justo este error.

**TS-12 · BE-10 · DB-12 · OB-20 · FE-21, media: 23 de 27 "verificado" sin test** (D01)
`README.md:59,66` pasa a definir dos etiquetas y se reetiqueta cada mención. Se versiona el proyecto de referencia en `tests/snippets/reference/`, armado desde los bloques; `build_ref.py` (unas 170 líneas) sirve de base. Se portan los 5 casos del cliente HTTP y se compilan los bloques React. Para `promtool`, `amtool` y `alloy`, un job opcional.
Prueba: `test_verified_claims_are_registered` falla si aparece una mención sin registrar.

**TS-13, media: `tsc` y `mypy` no corren en ninguna suite**
`tests/snippets/web/tsconfig.json`: agregar `vite/client`, `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess` y `erasableSyntaxOnly`. `package.json`: `tsc --noEmit && vitest run`. En Python, `mypy --strict` sobre el proyecto de referencia.
Prueba: un error de tipo a propósito pone `npm test` en rojo.

**TS-14, baja: el arnés usa versiones no prescritas** (D03)
`README.md:70` y el docstring del test: `'sqlalchemy>=2.0.40,<2.1'`. `package.json`: Vite 8 y plugin-react 6, revisando `vitest.config.ts`.
Prueba: las suites pasan con esas versiones.

**BE-20 · TS-19, baja: el test de contrato no ve `references/` ni `get_settings().X`**
`all_text()` pasa a `rglob("*.md")` más `templates/*.py`; regex `\b(?:get_)?settings(?:\(\))?\.([A-Z][A-Z0-9_]+)\b`; se elimina `CONSTANTS`; `block()` admite `references/`.
Prueba: un campo inexistente inyectado en `security.md` hace fallar el test.

**TS-20, baja: conteos y versiones sin respaldo** (D02)
Quitar los conteos de las skills (`layering:68`, `axios:391`) y unificar la etiqueta de PostgreSQL tras re-correr (`sessions:43,98`, `migrating:50`). `DIAGNOSTICO.md` recibe una sección nueva con los datos corregidos (ver C8) y el árbol con `tests/snippets/`.
Prueba: lectura y grep.

### Ola 2: contratos del backend (25)

#### Proyecto y dependencias

**BE-01 · TS-02 · TS-16, alta: `uv run pytest` no encuentra `app`**
Agregar `pythonpath = ["."]` y `filterwarnings = ["error::sqlalchemy.exc.SAWarning"]` para que `scaffolding:86-90` y `endpoints:51-57` queden idénticos. Quitar `PYTHONPATH` de `ci.md:52`. Agregar imports al bloque "Tests:" (`from tests.factories import create_product`).
Prueba: `uv run pytest` en un clon limpio, y un test que compare ambas tablas.

**BE-02 · TS-10, alta: el bootstrap no instala lo declarado**
`scaffolding:100-102`: `uv init --bare --python 3.14`, usar el bloque `pyproject` como única lista y `uv sync`. Agregar `name` y `version` al bloque. `app/` en la raíz del backend.
Prueba: bootstrap en un directorio temporal, con `EmailStr` y `uv run coverage --version`.

**BE-03 · OB-11, media: el paso 2 importa código de los pasos 3 y 8; el modo mínimo no existe** (D31)
`tracing:49-58`: imports del SDK y las instrumentaciones dentro de `setup_tracing`, así `current_trace_id()` funciona solo con la API. `scaffolding:35,41,75`: paso 2 con modo mínimo y `opentelemetry-api`. `layering:202-223`: `create_app` mínimo, marcando qué suma cada paso. `settings`: `METRICS_ENABLED`.
Prueba: armar la app por pasos e importarla en cada uno; `current_trace_id()` devuelve `None` solo con la API.

**BE-04, media: `--frozen` no falla con un lock viejo**
`ci.md:41`, `docker.md:50`: `--locked`. Corregir el texto en `ci.md:120`, `docker.md:68` y `scaffolding:59`.
Prueba: repetir el experimento (ya comprobado) y hacer `docker build`.

**BE-12, media: nada hace cumplir capas, `mypy` ni `ruff`**
`scaffolding`: `[tool.importlinter]`, `[tool.ruff]` y `lint-imports` en el checklist. `ci.md`: job `lint`.
Prueba: un import `services → api` hace fallar el job.

**BE-23, baja: fijación de versiones desigual** (D02)
Mismo tag exacto de Postgres en `docker.md:157`, `ci.md:71` y `endpoints:116`. `ci.md:34`: uv fijado.
Prueba: un test recorre las skills y compara tags.

**DB-16 · OB-25, baja: tres formas del pin de SQLAlchemy**
Canónico `sqlalchemy[asyncio]>=2.0.40,<2.1` en `scaffolding:21`, `tracing:26` y una línea nueva en `sessions`. `tracing:26`: citar también `0.66b2`.
Prueba: un test falla si aparece otra forma del pin.

#### Settings

**BE-06, media: `APP_ENV` en `.env` no elige el stage** (D05)
`settings:150-153`: error legible si `settings.APP_ENV` difiere de `stage`. `settings:18`: aclarar que sale del entorno real. `settings:183`: dejarlo comentado.
Prueba: los casos A, B y C del informe como tests.

**BE-14, baja: `DOCS_ENABLED` recomendado pero inexistente** (D10)
`settings`: agregar `DOCS_ENABLED: bool = False` y quitar `is_prod`, que solo usa `layering:208`. `.env.example` de desarrollo con `true`. Se puede sumar `openapi_url=None` (ver sección 7).
Prueba: test de contrato.

**BE-15, media: `OWNER_EMAIL` y `OWNER_PASSWORD` fuera de `Settings`**
`settings`: `OWNER_EMAIL: str | None`, `OWNER_PASSWORD: SecretStr | None`. `security.md:209`: leerlos de `get_settings()`.
Prueba: test de contrato y grep de `os.environ`.

**BE-16, baja: dos `.env.example`, ninguno completo**
Un único bloque en `settings`, con las claves opcionales comentadas, más `FRONTEND_API_PROXY_TARGET` y `GRAFANA_*`. `docker.md` remite a él; `docker.md:78`: `.env*`.
Prueba: comparar `Settings.model_fields` con las claves del bloque.

**BE-22 · TS-17, baja: dos entornos de test, uno apunta a `localhost`**
`settings:169-176` remite al conftest de `endpoints` (`test-db.invalid`). `docker.md:165`: quitar "tests" del comentario.
Prueba: lectura.

**BE-18 · TS-08, media: `create_app(settings)` no llega a errores ni al engine** (D11)
`layering:50,203-204`: quitar el parámetro y explicar que la factory evita efectos al importar. `settings:27`: `dependency_overrides` solo afecta a `SettingsDep`; lo demás usa entorno + `cache_clear()`.
Prueba: test con `cache_clear()` y `ERRORS_BASE_URL` distinta.

#### Capas

**BE-07 · OB-10, media: `lifespan`, salud async, `service.get` y `OrderRepository` no se publican** (D06)
`layering` publica `lifespan` (`yield`, `engine.dispose()`, `shutdown_tracing()`), el router de salud, `OrderService.get` y `OrderRepository`. `sessions:18,153` y `tracing:23,40` remiten a ese bloque.
Prueba: extraer `main.py`, importarlo y comprobar el apagado.

**BE-17 · OB-23, baja: la tabla de imports prohíbe lo que hace el ejemplo**
`layering:31`: `crud` y `database` solo en `api/deps.py`. `layering:32`: agregar `observability` y `security`. Contrato `forbidden` `app.api → app.crud`, con excepción para `deps`.
Prueba: `lint-imports`; la forma exacta de `ignore_imports` hay que probarla.

**BE-26, baja: `/health/ready` incumple el grep de capas**
`HealthRepository.ping()` en `crud/`, usado por el router de BE-07 y por `sessions:127-129`.
Prueba: el grep de `layering:248`.

**DB-10, media: nadie define `app/models/__init__.py`**
`modeling`: publicar las re-exportaciones y la regla "modelo nuevo = línea nueva". `layering:25`: `base.py` + `__init__.py`.
Prueba: ejecutar `env.py` con el proyecto de referencia.

#### Errores y seguridad

**BE-05, media: recurso ajeno: 404 o 403** (D04)
`security.md:235,247`: 404 si no existe o no puede verlo; 403 si lo ve pero no puede hacer la acción.
Prueba: tests de auth en el proyecto de referencia.

**BE-19, baja: "siempre `detail`", pero 3 de 4 handlers no lo envían**
`handling:20`: `type`, `title`, `status`, `code`, `instance` siempre; `detail` y `trace_id` si corresponden.
Prueba: lectura.

**BE-24, baja: "no saben nada de HTTP", pero declaran `status_code`** (D12)
`handling:9,11`: los services no tocan `HTTPException` ni `Request`; cada excepción declara su traducción HTTP como metadato.
Prueba: lectura.

**BE-08, media: `require_permission` da 500 con `lazy="raise"`**
`security.md`: publicar `UserRepository.get_with_role` con `joinedload(User.role)` y usarlo en `user_from_token`. Publicar también el esquema de `/auth/me` que necesita FE-17.
Prueba: permiso concedido da 200 y faltante da 403, con la sesión limpia.

**BE-09, media: dentro de `REUSE_GRACE` la segunda pestaña cae en login** (D07, C4)
`handling`: nueva excepción con `code = session_rotated`. `security.md:136-141,249`: usarla. `axios`: esperar y reintentar una vez. Se aplica junto con FE-11.
Prueba: test de backend y test del cliente con adapter falso.

#### Docker y CI

**BE-11 · TS-09, media: Postgres en CI se exige, pero no está en el YAML** (D08)
`ci.md`: job `test-postgres` con executor `machine` y `TEST_DB: postgres`, en `workflows` y en la tabla. Corrección en la sección nueva de `DIAGNOSTICO.md`.
Prueba: `circleci config validate` y una corrida real. No se pudo hacer en esta auditoría.

**BE-13, media: compose publica backend y base, y saltea el rate limit** (D09)
`docker.md`: `ports`, volumen y `--reload` pasan a `docker-compose.override.yml`.
Prueba: `docker compose -f docker-compose.yml config` sin puertos salvo `frontend`.

**BE-21 · OB-21, baja: comentario falso sobre `container_name`**
`docker.md:188`: quitar el comentario. Las queries usan el servicio de compose.
Prueba: grep.

### Ola 3: base de datos (15)

**DB-02, alta: `VALIDATE` junto a `NOT VALID` bloquea todo** y **DB-03, alta: tras un `lock_timeout` no se puede reintentar**
Se corrigen juntos, reemplazando el ejemplo de `migrating:151-188` por tres revisiones: `NOT VALID`, `VALIDATE` e índice solo en la suya, con `drop_index(if_exists=True)` + `create_index`. Reglas en `migrating:30-31`: "una revisión con `autocommit_block` no mezcla DDL transaccional" e "`IF NOT EXISTS` no sirve para reintentar". Checklist: consulta de `indisvalid`.
Prueba: `upgrade --sql` muestra un `COMMIT` entre ambos `ALTER`; reintento tras un `lock_timeout` con `indisvalid = t` (el auditor ya lo probó).

**DB-04, alta: `env.py` comparte URL con la app detrás de PgBouncer** (D13)
`settings`: `DB_MIGRATION_HOST`, `DB_MIGRATION_PORT`, computed `MIGRATION_DATABASE_URL` con `repr=False`, que cae en `DATABASE_URL`. `migrating:73,225` y `sessions:24,159`: usarla.
Prueba: test del fallback y test de contrato ampliado (BE-20).

**DB-05, media: "autogenerate no detecta CHECK" es falso en `create_table`**
`migrating:25,149,164,216`: lo que no detecta es agregar o cambiar un CHECK en una tabla existente.
Prueba: autogenerate sobre `Order` contiene `create_constraint=True`.

**DB-06, media: `statement_timeout` y `build_engine` no se combinan con PgBouncer** (D13)
`settings`: `DB_PGBOUNCER: bool = False`. `build_engine` ramifica. `sessions:24`: el timeout se fija con `ALTER ROLE`.
Prueba: con la bandera, construye con `NullPool` y sin `server_settings`.

**DB-07, media: la variante sync lleva credenciales escritas y no aplica el timeout** (D14)
`settings`: `DB_DRIVER: Literal["asyncpg", "psycopg"]`. `sessions:108-115`: `connect_args` con `options`. `sessions:22`: las dos formas por driver.
Prueba: `DATABASE_URL` por driver y `SHOW statement_timeout`.

**DB-08, media: el renombre directo contradice expand/contract**
`migrating:190`: encabezar como "con ventana de mantenimiento" y explicar el camino sin ventana. `migrating:39`: agregar esa salida.
Prueba: lectura.

**DB-09, media: `upgrade --sql` no lleva `lock_timeout`**
`run_migrations_offline()`: `context.execute("SET lock_timeout = '5s'")`.
Prueba: el SQL lo muestra antes del primer `ALTER`.

**DB-13, baja: imports duplicados en `base.py` y sin orden en `env.py`**
Borrar `modeling:69-71` y ordenar `env.py`.
Prueba: `ruff check --select F,I` sobre los bloques.

**DB-14, baja: `result.rowcount` no pasa `mypy --strict`**
`sessions:135-143`: `cast("CursorResult[Any]", ...)`.
Prueba: `mypy --strict` sobre el bloque.

**DB-15, baja: la regla pide `joinedload` y el ejemplo usa `selectinload`**
`modeling:209`: `joinedload(Order.product)`. `sessions:36`: "carga explícita".
Prueba: lectura.

**DB-17, baja: "`ALTER TYPE ADD VALUE` no corre en transacción" es falso en PG 16**
`modeling:57`: "no se puede quitar un valor, y el valor nuevo no se usa en la misma transacción". La decisión de no usar ENUM nativo se mantiene.
Prueba: ya ejecutada por el auditor.

**DB-18 · TS-18, baja: dice que SQLite no tiene índices parciales ni CHECK**
`endpoints:20`: "`FOR UPDATE`, JSONB, tipos estrictos, concurrencia real".
Prueba: ya ejecutada por los dos auditores.

**DB-19, baja: `render_item` advierte del síntoma equivocado**
`migrating:19`: sin él, la migración referencia `app.models.base.UtcDateTime` sin importarlo y falla con `NameError`.
Prueba: ya ejecutada por el auditor.

**DB-20, baja: la description promete síntomas que el cuerpo no trata**
Fila de `DetachedInstanceError` en `sessions`; `migrating:23` cita "Target database is not up to date" y suma la otra causa.
Prueba: grep.

### Ola 4: testing (7)

**TS-04, media: la sesión compartida no detecta un service sin `commit`** y **TS-05 · DB-11, media: el `rollback` borra lo que creó la factory** (D15, C2)
`endpoints:133-158`: fixture `db_conn` y una sesión por request. Ajustar `:22,24`. Agregar el test "`flush` sin `commit` no persiste" y, al test del 409, la aserción de que el original sigue existiendo. `handling` no cambia.
Prueba: ya ejecutada en SQLite y PostgreSQL 16, incluida la mutación y el test de tracing.

**TS-03, media: prohíbe mockear repositorios y su ejemplo los mockea** (D16)
`unit`: las reglas de `place_order` pasan a `db_session`. Se conserva un ejemplo con gateway y otro con `commit` que explota. Corregir `:3,26,27`. `layering:39`: "colaboradores externos".
Prueba: `grep create_autospec(.*Repository` vacío y bloques corriendo.

**TS-06, media: polyfactory choca con `UtcDateTime` y los CHECK** (D17)
`endpoints`: bloque con `created_at = Ignore()`, `updated_at = Ignore()`, `__set_primary_key__ = False` y columnas con CHECK fijadas.
Prueba: 30 instancias en PostgreSQL.

**TS-07 · OB-09, media: el test de tracing usa `ProductFactory`, que no existe**
`tracing:145-148`: `db_session` en la firma y `create_product(db_session, stock=5)`.
Prueba: ya pasa en SQLite y PostgreSQL 16; se agrega a `tests/snippets`.

**TS-11, media: la regla pide autospec y el ejemplo usa `AsyncMock(spec=)`**
`unit:157`: `mocker.create_autospec(PaymentGateway, instance=True)`.
Prueba: test que afirma `TypeError` con una firma incorrecta.

**TS-15, baja: la matriz exige un 500 que `client` no puede probar**
`endpoints`: fixture `client_no_raise` con `raise_app_exceptions=False`. `:274` se iguala a `:28`.
Prueba: 500, `internal_error` y sin filtrar el mensaje interno.

### Ola 5: observabilidad (18)

**OB-01, alta: las reglas SLI pierden `job`**
`slos:65-76`: `sum by (job)`. `slos:83-85,97-99`: filtrar. `slos:147`: `job` en `exp_labels`. `dashboard:125-126`: selector.
Prueba: casos de dos servicios y de inhibición (la variante ya pasó `promtool`).

**OB-02, alta: el salto de traza a logs no encuentra nada** (D26)
`stack:244-248`: `customQuery: true`, `query: '{service=~".+"} | trace_id="${__span.traceId}"'`. `logging:21`: aclarar los dos sentidos de `service`.
Prueba: **en la UI de Grafana**. La sintaxis no se probó ahí.

**OB-03, media: sin ningún 5xx, los SLI quedan sin datos**
`slos:67` y variantes: `or 0 * sum by (job) (...)`. Lo mismo en `dashboard:53,113-114`.
Prueba: caso solo con 2xx (la variante ya se probó).

**OB-04, media: retención de 15 días con SLO de 30** (D27)
`stack:36`: `35d`. `slos`: ítem de checklist "retención ≥ ventana".
Prueba: lectura.

**OB-05, media: exemplars imposibles** (D28)
`stack:223`: `name: traceID`. `slos:38`, `stack:38`: salen de `traces_spanmetrics_*`.
Prueba: enlace en la UI de Grafana.

**OB-06, media: 3 buckets y p99 saturado en 1 s** (D29)
`metrics:62-66`: `metrics.default(latency_lowr_buckets=(...))`. `dashboard:59,74-77`: `highr` para percentiles globales.
Prueba: bucket `0.3` en `/metrics` (ya comprobado).

**OB-07, media: SLO de latencia sin alertas, sin panel y sin `ticket` 3d** (D30)
`slos:61-125`: alertas de latencia, `rate3d`, y reglas completas sin `… idem`. `dashboard`: fila de latencia.
Prueba: un caso que dispara y otro que no, por alerta.

**OB-08, media: `slow_ratio` vale 1 con cero tráfico**
`slos:72-75`: `(count - bucket) / clamp_min(count, 1e-9)`.
Prueba: 0 en reposo (la variante ya se probó).

**OB-12, media: multiproceso no arranca y usa un worker deprecado** (D32)
`metrics:121`: `rm -rf "$D" && mkdir -p "$D"` y `-k uvicorn_worker.UvicornWorker`. `scaffolding`: dependencias condicionales. `metrics:25`, `dashboard:82`: `process_*` no existe en multiproceso.
Prueba: 2 workers y `/metrics` suma bien.

**OB-13, media: `HTTPXClientInstrumentor` prometido y no implementado**
`tracing:89`: agregarlo. `scaffolding:77`: el paquete, "si hay llamadas salientes".
Prueba: span CLIENT con `traceparent` contra `httpx.MockTransport`.

**OB-14, media: `promtool check config` no valida las reglas**
`slos:209`, `stack:283`: montar en `/etc/prometheus`.
Prueba: una regla rota da rc=1 (ya comprobado).

**BE-25 · OB-15, baja: "solo líneas JSON" es falso con reloader y gunicorn**
`logging:175`: "salvo las del proceso supervisor, que corren antes de `create_app()`".
Prueba: lectura.

**OB-16, baja: la prueba de punta a punta usa `/docs`, que no loguea**
`stack:289`: usar `POST /api/v1/orders` o un 404 de dominio.
Prueba: esa request deja un log con `trace_id`.

**OB-17, baja: los labels de la regla no coinciden con Alloy** (D33)
`logging:30`: `service`, `level`, `container`; `env` queda en el JSON.
Prueba: `/labels` de Loki.

**OB-18, baja: consultas sin `job`**
`dashboard:83-85`, `metrics:106-107`, `slos:17`: agregar el filtro.
Prueba: inspeccionar el dashboard generado.

**OB-19, baja: orden del dashboard y `mkdir`**
Mover la fila de SLO según `slos:37`. `dashboard:140`: `mkdir(parents=True, exist_ok=True)`. Unificar `dashboard:3` y `slos:205`.
Prueba: generar en un directorio limpio.

**OB-22, baja: alertas sin `description`**
Agregarla a `slos:108-124`, alinear `slos:219` y usar `OrdersApiDown` en `slos:35`.
Prueba: `promtool` y lectura.

**OB-24, baja: promete Promtail sin contenido** (D34)
`logging`: línea "Promtail: migrar a Alloy".
Prueba: lectura.

### Ola 6: frontend (24)

Se aplica en este orden porque varios hallazgos reescriben los mismos bloques: cliente HTTP, luego sesión y datos, luego actions y rutas, luego boundaries, y al final arquitectura y SSR.

#### Cliente HTTP

**FE-07, media: `errors.ts` rompe el build en la plantilla de Vite**
`axios:74-79`: declarar `readonly error` y asignarlo en el constructor. `arch:236`: `erasableSyntaxOnly`.
Prueba: `npm run build` en la plantilla oficial.

**FE-11, media: un fallo de red en el refresh cierra la sesión** (C4)
`axios:218-222`: solo un 401 sin `session_rotated` termina la sesión; el resto propaga el error tipado. Actualizar `axios:19,169,177,422`.
Prueba: `refresh_network_error_keeps_session`.

**FE-12, media: `toApiError` pierde `code` y `trace_id`**
`axios:70,72,129-130`: `problem` en `rate_limited` y `unknown`.
Prueba: tabla por status (400, 405, 413, 415, 429).

**FE-22, baja: "todas aceptan `signal`", salvo las publicadas** (D25)
`axios:22`: todas las de lectura; en mutaciones, solo si cancelar es seguro.
Prueba: lectura.

#### Sesión y datos

**FE-01, alta: dos dueños de la redirección** (D18)
`onSessionExpired` se inyecta desde `main.tsx` y usa `router.navigate`, con destino `router.state.navigation.location ?? router.state.location`; `lib/http` no importa `router`. `rethrowAsRouteError`: `case "unauthorized"` lanza `redirect`. `actions:30`: quitar `unauthorized`.
Prueba: `session_expiry_next_keeps_target`. Probar además en un navegador, porque jsdom no reproduce la carrera.

**FE-17, media: sesión con dos implementaciones, fuera del árbol**
Crear `features/auth/{api,session,index}`: tipo único `User`, `authApi.me` y `logout`, `requireUser`, `usePrivateData`. Depende de BE-08 para el esquema de `/auth/me`.
Prueba: `tsc` sobre los bloques.

**FE-15, media: `ordersApi` usa métodos inexistentes**
`productsApi` en `features/products/api.ts`; `ordersApi` queda con `placeOrder` y `notify`. Renombrar en `arch`, `routing`, `actions` y `ssr`. `searchProducts` necesita un endpoint en `layering` o una aclaración de que es ilustrativo.
Prueba: compilar los bloques contra los `api.ts` publicados.

#### Actions y rutas

**FE-18, media: cuatro formas para el resultado de una action**
Un único `ActionResult<T>` en `lib/`; reescribir `actions:65-79`, `routing:219-239,274,287`. Va primero en este grupo.
Prueba: `tsc` y `actions.test.tsx`.

**FE-05, media: criterios incompatibles entre action, `useActionState` y API directa** (D19)
`actions:43`: tabla de decisión. `actions:119-124`, `:218-229`: aclarar el caso o rehacer el ejemplo.
Prueba: lectura.

**FE-02, alta: la action pierde el form en un 409 y no muestra el 422 sin campo**
`routing:230-243`: `case "conflict"` y `message`. `routing:262`: pintar el mensaje. `routing:223`: helper que lanza si no hay `user`. `routing:22`: remitir a `:31`.
Prueba: generar el bloque y probar 409 y 422 sin campo.

**FE-03, alta: `NewProductForm` resetea durante el render**
`routing:286-298`: un `useEffect` que depende de `fetcher.data`, o `key` por alta. Botón con `disabled` y `aria-busy`.
Prueba: escribir, re-renderizar y conservar; `react-hooks/refs` sin errores.

**FE-04, alta: contraseña incorrecta y 429 van a la boundary**
`routing:31`, `actions:29-30`: excepción de login (`invalid_credentials`, `rate_limited`). `routing`: publicar `routes/login.tsx` con `safeNext`.
Prueba: el 401 conserva el email; el 429 muestra un aviso.

**FE-09, media: 403/404 en una action se ve como "Error inesperado"**
`routing:31,244`: `rethrowAsRouteError`. `actions:30`: quitar `forbidden`.
Prueba: action con `forbidden` y `not_found`.

**FE-14, media: `NotifyButton` no reporta ni muestra el error** (D23)
`routing:303-325`: `useTransition`. `actions:233`: alinear la excepción.
Prueba: rechazo llega a la boundary.

**FE-16, media: una compra exitosa lleva a un 404**
`routing:64-96`: `orders/:orderId`, `products/search` antes de `:productId`, y `*` dentro del layout. `routing:353`: texto fijo para el 404 del router.
Prueba: navegar a esas rutas con `router.tsx` generado.

**FE-20, baja: `RouteError` manda a recargar**
`routing:357-362`: botón con `useRevalidator().revalidate()` o enlace al inicio.
Prueba: comprobar que `revalidate` limpia el error.

#### Boundaries y renders

**FE-08, media: `onError` reporta 404/403 esperables** (D21)
`errors:173-175`: `if (isRouteErrorResponse(error)) return;`. `errors:227`: ítem en el checklist.
Prueba: 404, 403 y error inesperado.

**FE-10, media: `use(promise)` se contradice y "Reintentar" no recupera**
`actions:202-215`: promesa en estado con contador, u origen en loader, y `onReset`. `actions:20,52` y `renders:154`: reescribir.
Prueba: reintento con recuperación.

**FE-23, baja: linter y Compiler no hacen lo que dice el texto**
`renders:32`: quitarlos a mano y comprobar con el Profiler; mostrar `sources`. `renders:151`: toda la configuración `recommended`. `arch:106-112`: derivar `idle` en render.
Prueba: ESLint sobre los bloques.

#### Arquitectura y SSR

**FE-06, media: el ESLint no detecta los imports que usan los ejemplos** (D20)
`arch:213-227`: `import-x/no-restricted-paths` con zonas o `eslint-plugin-boundaries`. Publicar `paths` y alias de Vite. Usar `@/` en todos los ejemplos, incluido `routing:196`.
Prueba: fixture con imports buenos y malos, y ESLint en `npm test`.

**FE-13, media: el BFF "reenvía la cookie", pero no llega ni autentica** (D22)
`ssr:62,74,106,114`: el loader de SSR es solo para contenido público; la app privada sigue en SPA.
Prueba: lectura; los bloques de framework mode siguen sin compilar (§8 de `DIAGNOSTICO.md`).

**FE-19, media: el diagrama de SSR contradice su matriz** (D24)
`ssr:38-55`: agregar los nodos "¿Pueden operar Node?" y "¿Quieren RSC?".
Prueba: lectura.

**FE-24, baja: "sin reescribir rutas" y ADR con métricas obligatorias**
`ssr:24,11,127`: ajustar el texto.
Prueba: lectura.

**FE-25, baja: `vercel-index` no coincide en conteos, fechas ni `create-a-backend`**
Al re-relevar, una sola cifra y una sola fecha; aclarar `vercel:49`.
Prueba: consultar skills.sh. No se hizo en esta auditoría.

## 6. Cómo se ejecutaría

| Ola | Items | Cierre |
|---|---|---|
| 1. Arnés | 6 | Ambas suites y `tsc` en verde; todo bloque Python parsea |
| 2. Backend | 25 | El proyecto de referencia se arma y pasa desde un clon limpio |
| 3. Base de datos | 15 | Round-trip y reintento contra PostgreSQL 16 |
| 4. Testing | 7 | Suite en SQLite y Postgres; las mutaciones se detectan |
| 5. Observabilidad | 18 | `promtool`, `amtool`, y enlaces en la UI de Grafana |
| 6. Frontend | 24 | `tsc`, ESLint, `vitest`, build de Vite 8 y una pasada en navegador |

Cada arreglo con conducta sigue rojo → verde. Propongo un commit por ola, o más chico si conviene, y solo cuando lo pidas. Al final: `validate_skills.py`, ambas suites y una sección nueva en `DIAGNOSTICO.md`.

Las olas 3, 5 y 6 son independientes una vez cerrada la 2, así que se pueden paralelizar con un agente por rama. Las olas 1 y 2 conviene hacerlas en secuencia, porque muchos hallazgos tocan `settings`, `layering` y `scaffolding`.

## 7. Dudosos que conviene mirar

Los auditores dejaron 43 dudosos fuera del conteo; están al final de cada informe. Estos 5 parecen problemas reales y propongo sumarlos si estás de acuerdo:

| Origen | Tema | Propuesta |
|---|---|---|
| database, dudoso 1 | `SET NOT NULL` en tablas grandes escanea con `ACCESS EXCLUSIVE` | Agregar el CHECK `NOT VALID` + `VALIDATE` previo. Sin ejecutar |
| backend, D6 | Refresh sin bloqueo de fila: dos refresh simultáneos podrían rotar ambos | `get_by_hash_for_update` y test en Postgres. Sin probar |
| backend, D7 | `/openapi.json` sigue público con `docs_url=None` | `openapi_url=None` junto con BE-14 |
| backend, D2 | El placeholder de `SECRET_KEY` pasa la validación | Dejar la clave vacía en el ejemplo, para que falle |
| testing, D1 | `setdefault("APP_ENV", "test")` lee el `.env` si el shell tiene otro valor | Asignación directa solo para `APP_ENV` |

## 8. Índice por skill

| Skill | Inconsistencias |
|---|---|
| backend/configuring-fastapi-settings | BE-03, BE-06, BE-14, BE-15, BE-16, BE-18, BE-22, DB-04, DB-06, DB-07 |
| backend/handling-fastapi-errors | BE-09, BE-19, BE-24 |
| backend/layering-fastapi-apps | BE-03, BE-07, BE-14, BE-17, BE-18, BE-26, DB-10, TS-03, TS-20, FE-15 |
| backend/scaffolding-fastapi-backends | BE-01, BE-02, BE-03, BE-04, BE-12, DB-16, OB-12, OB-13 |
| · references/security.md | BE-05, BE-08, BE-09, BE-15 |
| · references/docker.md | BE-04, BE-13, BE-16, BE-21, BE-22, BE-23 |
| · references/ci.md | BE-01, BE-04, BE-11, BE-12, BE-23 |
| database/configuring-sqlalchemy-sessions | BE-07, BE-26, DB-04, DB-06, DB-07, DB-14, DB-15, DB-16, DB-20, TS-20 |
| database/modeling-postgres-with-sqlalchemy | DB-10, DB-13, DB-15, DB-17 |
| database/migrating-with-alembic | DB-02, DB-03, DB-04, DB-05, DB-08, DB-09, DB-13, DB-19, DB-20, TS-20 |
| frontend/architecting-react-apps | FE-06, FE-07, FE-15, FE-17, FE-23 |
| frontend/building-axios-clients | BE-09, FE-01, FE-07, FE-11, FE-12, FE-15, FE-17, FE-22, TS-20 |
| frontend/choosing-ssr-or-spa | FE-13, FE-15, FE-19, FE-24 |
| frontend/handling-react-errors | FE-08 |
| frontend/optimizing-react-renders | FE-10, FE-23 |
| frontend/routing-with-react-router | FE-01, FE-02, FE-03, FE-04, FE-05, FE-06, FE-09, FE-14, FE-15, FE-16, FE-17, FE-18, FE-20 |
| frontend/using-react-19-actions | FE-01, FE-03, FE-04, FE-05, FE-09, FE-10, FE-14, FE-15, FE-18 |
| frontend/vercel-index | FE-25 |
| testing/testing-fastapi-endpoints | BE-01, BE-11, BE-22, BE-23, DB-18, TS-01, TS-04, TS-05, TS-06, TS-15 |
| testing/unit-testing-fastapi-services | TS-03, TS-11 |
| observability/exposing-prometheus-metrics | OB-06, OB-12, OB-18 |
| observability/logging-json-to-loki | BE-25, OB-02, OB-17, OB-24 |
| observability/tracing-with-opentelemetry | BE-03, BE-07, DB-16, OB-13, TS-07 |
| observability/defining-grafana-slos | OB-01, OB-03, OB-04, OB-05, OB-07, OB-08, OB-14, OB-18, OB-19, OB-22 |
| · references/stack.md | OB-02, OB-04, OB-05, OB-14, OB-16 |
| · templates/build_dashboard.py | OB-01, OB-03, OB-06, OB-07, OB-12, OB-18, OB-19 |
| Repo: README, DIAGNOSTICO, tests/snippets | TS-01, TS-12, TS-13, TS-14, TS-20, BE-11, BE-20 |

TS-12 (el sello "verificado") afecta a casi todas las skills; su tabla está en [auditoria/testing.md](auditoria/testing.md).
