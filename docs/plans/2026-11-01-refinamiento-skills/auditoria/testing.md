# Auditoría de la rama TESTING y de la verificación del repo

**Fecha:** 2026-11-01 · **Commit auditado:** `54d8c96` · **Repo:** no se modificó (ver "Lo que no se pudo verificar").

## Cómo se ejecutó

Todo corrió sobre una copia en `/tmp/claude-1000/-home-leonel-my-skills/927a91bb-bc0d-4938-a40b-4a8225428464/scratchpad/audit/testing/`:

- **`ref/`:** proyecto armado **con los bloques textuales de las skills**. Lo genera `build_ref.py`, que usa el propio `extract.block()`. Solo se escribió a mano lo que las skills no publican: `OrderRepository`, `ProductService`, schemas de producto, `api_router` y lifespan.
- **Versiones resueltas:** Python 3.14, SQLAlchemy 2.0.55, FastAPI 0.162, Starlette 1.10, pytest 9.2, pytest-asyncio 1.4.1, pytest-mock 3.17, aiosqlite 0.22, asyncpg 0.32, testcontainers 4.15, polyfactory 3.5, mypy 2.4.
- **Postgres:** PostgreSQL 16-alpine por testcontainers. Los contenedores se autolimpiaron: quedaron 0 con la etiqueta `org.testcontainers`.

### Resultado de las suites

| Suite | Comando | Resultado |
|---|---|---|
| Python | el de `README.md:70` | **7 passed** (resolvió SQLAlchemy **2.1.6**, ver TS-14) |
| Frontend | `npm install && npm test` | **13 passed** en 3 archivos |
| Validador | `scripts/validate_skills.py` | 20 skills + 1 índice, 0 errores (no parsea código, ver TS-01) |

### Lo que funciona (corregido solo TS-01 y TS-02)

Queda como base para los planes y evita repetir verificaciones:

- El conftest, las factories y los 4 tests de endpoints pasan en SQLite y en PostgreSQL 16.
- Los 5 tests unitarios pasan, y `mypy --strict tests/unit` y `mypy app` no dan errores.
- La receta de concurrencia pasa en PostgreSQL. Si se quita `with_for_update()`, falla, así que su comentario "sin FOR UPDATE, ambos ganarían" es cierto.
- `filterwarnings = error::SAWarning` no rompe nada, y la suite pasa con 3 semillas de `pytest-randomly`.
- `/metrics` expone `http_requests_total{handler="/api/v1/orders",method="POST",status="2xx"}` como dice `exposing-prometheus-metrics`.
- `UtcDateTime` devuelve UTC con zona en ambos motores.

### Contratos cruzados sin hallazgo

- Firmas de repositorio y service (`get_for_update`, `add`, `OrderService(session, products, orders)`).
- `commit` en el service.
- `extra`, `code` y `status` de `InsufficientStockError`, `NotFoundError` y `ConflictError`.
- `get_db` / `DbSession`, `Base` en `app.models`, variables obligatorias de `Settings`.
- `/api/v1/orders`, `Page.items`, `problem+json`.
- `testing-fastapi-endpoints:25` ↔ `migrating-with-alembic:20` (siembra).
- Nombres de fixtures (`client`, `db_session`, `engine`) entre testing, tracing y errores.

---

## Hallazgos

### TS-01: el `conftest.py` "verificado" tiene un error de sintaxis

- **Severidad:** alta
- **Tipo:** a, d
- **Evidencia:**
  - `skills/testing/testing-fastapi-endpoints/SKILL.md:59`: "`tests/conftest.py` (verificado: la misma suite pasa en SQLite y en PostgreSQL 16 vía testcontainers)"
  - `skills/testing/testing-fastapi-endpoints/SKILL.md:116`: `with PostgresContainer("postgres:16-alpine", driver="asyncpg")  # = la versión de producción as pg:`
  - `README.md:51`: "**ejecutado** antes de publicarse"
  - `DIAGNOSTICO.md:94`: "parseo de 38 bloques Python y 13 YAML [...] 0 errores"
  - Origen: `git show edd80d7` reemplazó `...driver="asyncpg") as pg:` (versión 17) por la línea actual. El comentario quedó en medio del `with`.
- **Confirmación:** ejecutado. `uv run pytest` da `SyntaxError: expected ':'` al cargar el conftest. `ast.parse` sobre todos los bloques da un único error en este bloque. `validate_skills.py` da 0 errores porque no parsea código.
- **Impacto:** un agente que copie el conftest no puede correr **ningún** test, tampoco en SQLite, porque el error es de carga del módulo.
- **Plan de corrección:** es un bug, sin lado canónico que elegir.
  1. `testing-fastapi-endpoints/SKILL.md:116` → `with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:  # = la versión de producción`.
  2. `tests/snippets/test_python_snippets.py`: agregar `test_every_python_block_parses`, que recorra `SKILL.md` y `references/*.md` con `ast.parse`. Se comprobó que hoy detecta exactamente este error.
  3. Verificación: esa prueba, roja antes y verde después.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### TS-02: `uv run pytest` no encuentra `app` con el `pyproject` publicado

- **Severidad:** alta
- **Tipo:** c, e
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:262`: `uv run pytest -q  # SQLite en memoria, sin Docker`, y `:269`: "`uv run pytest` pasa sin Postgres ni Docker".
  - `testing-fastapi-endpoints/SKILL.md:50-57` y `scaffolding-fastapi-backends/SKILL.md:86-90`: ninguno tiene `pythonpath`.
  - `scaffolding-fastapi-backends/references/ci.md:52`: `PYTHONPATH: "."`. La decisión existe solo en CI.
  - `scaffolding-fastapi-backends/SKILL.md:100`: `uv init --python 3.14 my-api`. Con uv 0.12.24 crea `src/my_api` y `[build-system]`, así que el paquete instalado no es `app`.
  - `grep -rn "pythonpath\|__init__.py" skills`: la única coincidencia es `ci.md:52`.
- **Confirmación:** ejecutado, tanto con el `pyproject` de la skill como con el bootstrap real de `uv init`.

  | Variante | Resultado |
  |---|---|
  | `uv run pytest` | `ModuleNotFoundError: No module named 'app'` |
  | `uv run coverage run -m pytest` | 4 passed (`-m` agrega el cwd al path) |
  | `PYTHONPATH=. uv run pytest` | 4 passed |
  | `pythonpath = ["."]` en `pyproject` | 9 passed, sin `tests/__init__.py` |
  | con `tests/__init__.py` | 9 passed |

- **Impacto:** el primer comando de la skill falla en local, y el mismo código pasa en CI. Además, el bloque "Tests:" no dice cómo importar `tests/factories.py`.
- **Plan de corrección:** canónico `pythonpath = ["."]`, porque es declarativo y sirve igual para local y CI.
  1. Agregarlo en `testing-fastapi-endpoints/SKILL.md:51` y `scaffolding-fastapi-backends/SKILL.md:86`.
  2. Quitar `PYTHONPATH` de `ci.md:52`.
  3. Agregar imports al bloque "Tests:" (`from tests.factories import create_product`). Con `pythonpath` funciona como paquete de espacio de nombres (ejecutado).
  4. En `scaffolding-fastapi-backends/SKILL.md:100` usar `uv init --bare` (ejecutado: solo crea `pyproject.toml`). `--app` también crea `src/` y `[build-system]`.
  5. Verificación: un proyecto temporal con los bloques (`build_ref.py`) y `uv run pytest` sin variables de entorno.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend (`scaffolding`, `ci.md`). Dato canónico: `pythonpath = ["."]` en `[tool.pytest.ini_options]`; `app/` en la raíz del backend.

### TS-03: `unit-testing` prohíbe mockear repositorios y su ejemplo central los mockea

- **Severidad:** media
- **Tipo:** a
- **Evidencia:**
  - `unit-testing-fastapi-services/SKILL.md:18`: "**El caso de uso toca la base** (valida, escribe, commitea): testearlo contra la base de test [...] sin mocks de repositorios."
  - `:19`: "**Mocks**, solo para: clientes externos [...], el reloj y fallos de infraestructura".
  - `:27`: "**`create_autospec(Clase, instance=True)`** para repositorios y clientes".
  - `:26`: "el test construye `OrderService(session_mock, products_mock, orders_mock)`".
  - `:50-146`: el ejemplo "verificado" prueba `place_order` (valida, escribe, commitea) con repositorios mockeados. Solo `test_place_order_propagates_commit_failure` entra en el estilo 3.
  - `:3` (description): "without a database or network - mocking repositories, AsyncSession", frente a `:25` ("`tests/unit/` aloja los tres estilos") y `:170` ("SQLite en memoria alcanza").
  - Del otro lado, `layering-fastapi-apps/SKILL.md:253`: "casos de uso contra la base de test, mocks solo para colaboradores externos".
- **Confirmación:** por lectura. Los tests del ejemplo pasan, así que la contradicción es de regla, no de código.
- **Impacto:** el agente copia el ejemplo porque es lo concreto, y escribe los tests que la regla prohíbe. O sigue la regla y queda sin ejemplo del estilo que debe usar.
- **Plan de corrección:** canónico el orden de estilos (`:17-19`), porque es la decisión más nueva (refinamiento §7 bis) y coincide con `layering:253`.
  1. Reemplazar el ejemplo: reglas de `place_order` con `db_session`, que necesita TS-04 para ver el commit.
  2. Conservar un ejemplo de estilo 3 con el gateway de pagos y el `commit` que explota.
  3. Cambiar `:27` a "para clientes externos" y `:26` a un service con gateway.
  4. Reescribir `description` sin "mocking repositories" y aclarar en `:3` que los estilos 1 y 2 entran.
  5. Verificación: `grep -n "create_autospec(.*Repository" unit-testing-fastapi-services/SKILL.md` vacío, y los bloques corriendo en el proyecto de referencia.
- **Decisión requerida:** ¿los mocks de repositorio quedan prohibidos o se aceptan como excepción? Recomiendo prohibirlos para casos de uso que escriben. Los fallos de infraestructura se prueban con `mocker.patch.object(db_session, "commit", side_effect=...)`.
- **Otros dominios afectados:** backend. `layering:39` ("los tests reemplazan colaboradores") se ajusta a "colaboradores externos".

### TS-04: la sesión compartida del `client` no detecta un service que olvidó el `commit`

- **Severidad:** media
- **Tipo:** c, e
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:24`: "**`dependency_overrides[get_db]`** devuelve la sesión del test".
  - `:152-153`: `async def _override_get_db() ...: yield db_session` (no cierra nada entre requests).
  - `configuring-sqlalchemy-sessions/SKILL.md:20`: "Al cerrar, lo no commiteado se descarta".
  - `layering-fastapi-apps/SKILL.md:42`: "Si el caso de uso falla antes del commit, la sesión se cierra y todo se descarta".
  - `unit-testing-fastapi-services/SKILL.md:18`: envía el caso de uso que "commitea" a esta base de test.
- **Confirmación:** ejecutado. Mutación: en `place_order`, `commit()` → `flush()`. **4 passed en SQLite y 4 passed en PostgreSQL 16.** En producción esa orden se pierde. Con el conftest alternativo de abajo, `test_place_order_decrements_stock` falla (`assert 5 == 3`), que es lo correcto.
- **Impacto:** el error central de la regla "un commit por caso de uso" pasa en verde. Con TS-03 resuelto, nada más lo comprueba. A la inversa (por lectura), una mutación sin commit de un caso que falla sigue visible para el test, aunque en producción se descartaría.
- **Plan de corrección:** canónico el comportamiento de `get_db` (sesión por request, se descarta al cerrar). Cambiar `:133-158` a una conexión compartida y **una sesión por request**:

  ```python
  @pytest.fixture
  async def db_conn(engine):
      async with engine.connect() as conn:
          outer = await conn.begin()
          try:
              yield conn
          finally:
              await outer.rollback()

  @pytest.fixture
  async def db_session(db_conn):
      async with AsyncSession(bind=db_conn, expire_on_commit=False,
                              join_transaction_mode="create_savepoint") as session:
          yield session

  # en `client`:
  async def _override_get_db():
      async with AsyncSession(bind=db_conn, expire_on_commit=False,
                              join_transaction_mode="create_savepoint") as s:
          yield s
  ```

  Ejecutado: 12 passed en SQLite y 13 passed en PostgreSQL 16, con receta de concurrencia, unitarios y los tests de TS-05, y con `filterwarnings=error::SAWarning`. Lo que el helper hace `flush` sigue visible para la request porque comparten conexión. Ajustar `:22` y `:24`. Agregar a la skill un test de contrato: "un service que hace `flush` sin `commit` no persiste".
- **Decisión requerida:** ¿adoptar la sesión por request? Recomiendo sí: resuelve TS-04 y TS-05 con un solo cambio, y el costo es un fixture más.
- **Otros dominios afectados:** observabilidad. El test de tracing sigue funcionando: se ejecutó con el conftest actual, pero no con este alternativo. Hay que re-correrlo al adoptarlo.

### TS-05: el `rollback` que exige `handling-fastapi-errors` borra lo que creó la factory

- **Severidad:** media
- **Tipo:** c
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:25` y `:276`: "hacen `flush`, no `commit`".
  - `handling-fastapi-errors/SKILL.md:197`: `await self._session.rollback()  # tras el fallo la sesión no sirve hasta el rollback`.
  - `testing-fastapi-endpoints/SKILL.md:206-214`: el test del 409 pasa solo porque no mira nada después.
- **Confirmación:** ejecutado en SQLite y PostgreSQL 16. Tras el 409, `select count(Product)` devuelve **0**; en producción sería 1. Con el conftest de TS-04 pasa.
- **Impacto:** un test legítimo ("el 409 no toca el producto original") falla por el fixture. El agente termina debilitando el test o agregando `commit` en la factory, cosa que el checklist prohíbe.
- **Plan de corrección:** adoptar TS-04. Si el dueño lo rechaza, documentar en `:25` que el arrange debe terminar con `await db_session.commit()` (libera el savepoint) cuando el caso de uso hace `rollback`. Verificación: agregar la aserción de conteo a `test_duplicate_sku_is_409_problem_json`.
- **Decisión requerida:** depende de TS-04.
- **Otros dominios afectados:** ninguno. El patrón de `handling-fastapi-errors` es correcto y no cambia.

### TS-06: el camino `polyfactory` choca con `UtcDateTime` y con los CHECK

- **Severidad:** media
- **Tipo:** c
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:26`: "generar esos valores con `polyfactory` (`SQLAlchemyFactory` con `__persistence_method__ = FLUSH`)". No hay ejemplo.
  - `modeling-postgres-with-sqlalchemy/SKILL.md:100-101`: `raise ValueError("naive datetime: use a timezone-aware datetime (UTC)")`.
  - `:126`: `created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())`.
  - `:138-139`: `CheckConstraint("stock >= 0")`, `CheckConstraint("price >= 0")`.
- **Confirmación:** ejecutado con polyfactory 3.5 sobre `Product` y `TimestampMixin`:
  - Factory mínima: `StatementError: naive datetime: use a timezone-aware datetime (UTC)`, porque rellena `created_at` y `updated_at` con fechas sin zona.
  - Con `created_at = Ignore()`, `updated_at = Ignore()` y `__set_primary_key__ = False`: funciona.
  - En 30 `build()`, **13 tenían `stock` o `price` negativos**, que violan los CHECK; un ejemplo de `price` fue `1829359294.55`, fuera de `Numeric(12, 2)`.
- **Impacto:** quien siga la regla obtiene error siempre y, una vez resuelto, fallos intermitentes por valores aleatorios. El caso de uso de la regla (muchas columnas) es justo el que más lo sufre.
- **Plan de corrección:** agregar a `testing-fastapi-endpoints` un bloque ejecutable:

  ```python
  class ProductFactory(SQLAlchemyFactory[Product]):
      __persistence_method__ = SQLAlchemyPersistenceMethod.FLUSH
      __set_primary_key__ = False
      created_at = Ignore()
      updated_at = Ignore()
      # Columnas con CHECK: fijarlas con Use(...) o pasarlas siempre.
  ```

  más cómo enlazar `__async_session__ = db_session` por fixture. Verificación: un test con 30 instancias en PostgreSQL.
- **Decisión requerida:** ¿mantener polyfactory? Recomiendo mantenerlo con el bloque, porque ya está decidido en `:26` y en `DIAGNOSTICO.md:73`.
- **Otros dominios afectados:** database, solo como consumidor; `UtcDateTime` no cambia.

### TS-07: el test de tracing usa un `ProductFactory` que no existe y que la skill de testing no permite aquí

- **Severidad:** media
- **Tipo:** b, c
- **Evidencia:**
  - `tracing-with-opentelemetry/SKILL.md:148`: `product = await ProductFactory.create_async(stock=5)`.
  - `testing-fastapi-endpoints/SKILL.md:25`: "helpers async en `tests/factories.py` (`create_product(session, **overrides)`)".
  - `:26`: polyfactory solo "si un modelo tiene más de 10 columnas obligatorias [...] Si no, helpers". `Product` tiene 5.
  - `grep -rn ProductFactory skills`: solo esa línea.
- **Confirmación:** ejecutado.
  - Textual: `NameError: name 'ProductFactory' is not defined`.
  - Definida sin sesión: `ConfigurationException: An '__async_persistence__' handler must be defined`.
  - Adaptado (`create_product(db_session, stock=5)` y `db_session` en la firma): **passed**, junto con el resto de la suite.
- **Impacto:** `tracing:174` exige que este test pase ("El test con `InMemorySpanExporter` pasa"), y como está no corre.
- **Plan de corrección:** canónico `testing-fastapi-endpoints`. En `tracing:145-148`, agregar `db_session: AsyncSession` a la firma y usar `create_product`. Agregar el test a `tests/snippets` o al proyecto de referencia.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** observabilidad. Dato canónico: `create_product(db_session, **overrides)` desde `tests/factories.py`.

### TS-08: `create_app(settings)` promete otros settings que no llegan a errores ni a la base

- **Severidad:** media
- **Tipo:** c
- **Evidencia:**
  - `layering-fastapi-apps/SKILL.md:50`: "`create_app()` como factory: tests y workers pueden construir apps con otros settings".
  - `:203-204`: `def create_app(settings: Settings | None = None)`.
  - `handling-fastapi-errors/SKILL.md:130`: `get_settings().ERRORS_BASE_URL` (no usa el parámetro).
  - `configuring-sqlalchemy-sessions/SKILL.md:73`: `engine = build_engine(get_settings())`.
  - `tracing-with-opentelemetry/SKILL.md:67`: `or _provider is not None: return` (una segunda app queda sin instrumentar).
  - `testing-fastapi-endpoints/SKILL.md:84`: importa el singleton `app`; nunca usa la factory.
  - `configuring-fastapi-settings/SKILL.md:27`: `dependency_overrides` tampoco alcanza a `problem()`, que llama directo a `get_settings()`.
- **Confirmación:** ejecutado. `create_app(Settings(_env_file=None, ERRORS_BASE_URL="https://other.invalid"))` responde a un 404 con `type = https://a.invalid/http_404`, el valor global. La segunda `create_app` no rompe. La parte de `dependency_overrides` es por lectura.
- **Impacto:** un test construye una app con otra `ERRORS_BASE_URL` o base, cree que la aplicó y sigue con la global.
- **Plan de corrección:** dos salidas (ver decisión). En cualquier caso, agregar un test con `create_app(otros_settings)` que afirme lo elegido.
- **Decisión requerida:** ¿la factory acepta settings de verdad?
  - (A) Recomendada: quitar el parámetro y corregir `layering:50` a "la factory evita efectos al importar; en tests la config se fija por entorno antes de importar (`APP_ENV=test`), y `get_settings.cache_clear()` si cambia". Coincide con lo que ya hace el conftest.
  - (B) Inyectar por `app.state.settings` en `errors.py` y engine por app: más invasivo y sin consumidor actual.
- **Otros dominios afectados:** backend (`layering`, `configuring-fastapi-settings`). Dato canónico de este dominio: los tests importan `from app.main import app` y fijan la configuración por entorno antes de importar.

### TS-09: el job `TEST_DB=postgres` se exige o se da por agregado, pero no está en el YAML

- **Severidad:** media
- **Tipo:** d, e
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:271`: "`TEST_DB=postgres uv run pytest` pasa con Docker (en CI, al menos en un job)" (sin condición).
  - `scaffolding-fastapi-backends/SKILL.md:23`: "Postgres vía testcontainers en CI".
  - `references/ci.md:11`: "agregar un job con `TEST_DB=postgres` [...] **Ese job es obligatorio si hay tests de concurrencia**" (condicional).
  - `references/ci.md:111-115`: el workflow tiene solo `test-python` y `migrations`.
  - `DIAGNOSTICO.md:37`: "Agregado: job opcional `TEST_DB=postgres`" (es una frase, no un job).
  - `modeling-postgres-with-sqlalchemy/SKILL.md:286`: "Hay test de concurrencia o de integridad para cada regla crítica", lo que vuelve la condición casi universal.
- **Confirmación:** por lectura. No hay CircleCI para ejecutar el pipeline; que la suite pase con `TEST_DB=postgres` sí está ejecutado.
- **Impacto:** quien copie el YAML cumple `ci.md`, incumple el checklist de testing, y sus tests de concurrencia quedan saltados en todas las corridas automáticas, que es el riesgo que `:277` intenta evitar.
- **Plan de corrección:** canónico `testing:271`, por ser la versión más estricta y la que protege los invariantes.
  1. Agregar a `ci.md` el job `test-postgres` con executor `machine` (Testcontainers necesita Docker real) y `TEST_DB: postgres`.
  2. Agregarlo a `workflows` y a la tabla `ci.md:5-9`.
  3. Corregir `DIAGNOSTICO.md:37`.
  4. El YAML hay que validarlo con `circleci config validate` y una corrida real; aquí no se probó.
- **Decisión requerida:** ¿job siempre, o solo con tests de concurrencia? Recomiendo siempre, porque los modos SQLite y Postgres divergen justo en lo crítico.
- **Otros dominios afectados:** backend (`ci.md`). Dato canónico: `TEST_DB=postgres` en al menos un job, con Docker real.

### TS-10: el bootstrap no instala `coverage` y los comandos publicados lo usan

- **Severidad:** media
- **Tipo:** b
- **Evidencia:**
  - `scaffolding-fastapi-backends/SKILL.md:83`: el grupo `dev` incluye `"coverage"`.
  - `:102`: `uv add --dev pytest pytest-asyncio pytest-mock pytest-randomly httpx aiosqlite "testcontainers[postgres]" ruff mypy import-linter` (sin `coverage`).
  - `testing-fastapi-endpoints/SKILL.md:264`: `uv run coverage run --source=app -m pytest`.
  - `references/ci.md:61-62`: `uv run coverage ...`.
- **Confirmación:** ejecutado. Tras el bootstrap, `uv run coverage --version` falla con `No such file or directory`. El mismo bootstrap tampoco instala `email-validator`, con lo que `EmailStr` falla al importar (`ModuleNotFoundError: No module named 'email_validator'` al probar el import).
- **Impacto:** el job `test-python` de CI y el comando de cobertura fallan en un proyecto creado con el bootstrap.
- **Plan de corrección:** canónico el `pyproject` base (`:67-84`), que es el más completo. Sincronizar `:101-102` con él, o reemplazar el bootstrap por "copiar el `pyproject` y `uv sync`", que evita tener dos listas. Verificación: bootstrap en un directorio temporal y `uv run coverage --version`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend. El resto de la lista del bootstrap (runtime) es del auditor de backend.

### TS-11: para clientes externos, la regla pide autospec y el ejemplo usa `AsyncMock(spec=...)`, que no valida firmas

- **Severidad:** media
- **Tipo:** a
- **Evidencia:**
  - `unit-testing-fastapi-services/SKILL.md:11`: "dobles con la **misma firma** que los reales".
  - `:27`: "**`create_autospec(Clase, instance=True)`** para repositorios y clientes: [...] las firmas se validan".
  - `:169`: "cliente externo → mock con autospec".
  - `:157`: `gateway = mocker.AsyncMock(spec=PaymentGateway)`.
- **Confirmación:** ejecutado.
  - `await AsyncMock(spec=PaymentGateway).charge(amout=1, wrong=2)` se **acepta**.
  - `create_autospec(PaymentGateway, instance=True).charge(amout=1, wrong=2)` da `TypeError: missing a required keyword-only argument: 'amount'`, y `.charge` es `AsyncMock`.
- **Impacto:** el único ejemplo de estilo 3 que sobrevive a TS-03 pierde justo la protección que la skill promete.
- **Plan de corrección:** canónico `:27`. `:157` → `gateway = mocker.create_autospec(PaymentGateway, instance=True)`. La excepción de `:28` para `AsyncSession` puede quedar, porque ya está explícita. Verificación: agregar al snippet un test que afirme `TypeError` con una firma incorrecta.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### TS-12: 23 de 27 menciones "verificado" no tienen test, contra lo que promete el README

- **Severidad:** media
- **Tipo:** d
- **Evidencia:**
  - `README.md:66`: "Un bloque que el texto marca como **verificado** tiene su test en `tests/snippets/`".
  - `README.md:59`: admite verificar "en un proyecto real" o con "`promtool`, `amtool`, `alloy validate`", y esas herramientas no corren en `tests/snippets/`. El README se contradice entre los pasos 2 y 4.
  - `DIAGNOSTICO.md:170`: "Proyectos de referencia fuera del repo | Viven en el scratchpad de la sesión" (admite que no son reproducibles).
- **Confirmación:** ejecutado. Script `verif_map.py` más grep de `verificad|validado con|probado de punta`, con marcadores tomados de `generate.py` y `test_python_snippets.py`. Tabla abajo.
- **Impacto:** el sello "verificado" no distingue lo protegido de lo que solo se probó una vez. TS-01 es la prueba: el sello sobrevivió a una edición que rompió el bloque.
- **Plan de corrección:** ver decisión. En cualquier caso, un test `test_verified_claims_are_registered` en `tests/snippets` que falle si aparece una mención sin entrada en un registro explícito.
- **Decisión requerida:** ¿qué significa "verificado"? Recomiendo dos etiquetas:
  - **`verificado (test)`:** con test en el repo.
  - **`verificado a mano (fecha, herramienta)`:** corrida única.

  Además, versionar el proyecto de referencia en `tests/snippets/reference/` armándolo desde los bloques, lo que resuelve en una sola suite casi todas las filas Python. Se probó que es factible: `build_ref.py` tiene ~170 líneas y corre en menos de 1 s en SQLite. `DIAGNOSTICO.md:170` ya lo recomendaba. Para `promtool`, `amtool` y `alloy`, un job opcional si están instalados.
- **Otros dominios afectados:** todos. Cambia la etiqueta de cada mención.

#### Bloques "verificado" y su test

| Skill:línea | Qué afirma | ¿Test? | Observación |
|---|---|---|---|
| `configuring-fastapi-settings:45` | mypy `--strict` + pytest | **sí** (`test_settings_*`) | mypy no corre en la suite (TS-13) |
| `modeling-postgres-with-sqlalchemy:66` | PostgreSQL 16 y SQLite | **parcial** (`test_datetime_keeps_instant_on_sqlite`) | solo `UtcDateTime` en SQLite; nada de PostgreSQL |
| `building-axios-clients:43` | `tsc --strict` + `exactOptionalPropertyTypes` | **sí** (se importa en `skill.test.tsx`) | `tsc` no corre (TS-13) |
| `handling-react-errors:50` | `tsc --strict` | **sí** (`reporter_receives_backend_trace_id`) | `tsc` no corre (TS-13) |
| `handling-fastapi-errors:52` | integración 404/409/422/500 | no | |
| `layering-fastapi-apps:68` | 17 tests, mypy, ruff | no | ver TS-20 |
| `configuring-sqlalchemy-sessions:25` | exclusión `/api/v1/health/live` | no | |
| `configuring-sqlalchemy-sessions:43` | PostgreSQL 17 con testcontainers | no | |
| `configuring-sqlalchemy-sessions:98` | `psycopg` 3 y PostgreSQL 17 | no | |
| `migrating-with-alembic:50` | autogenerate, check, round-trip | no | |
| `migrating-with-alembic:149` | migración manual | no | |
| `modeling-postgres-with-sqlalchemy:213` | savepoint por fila | no | |
| `testing-fastapi-endpoints:59` | SQLite y PostgreSQL 16 | no | **no parsea** (TS-01) |
| `unit-testing-fastapi-services:50` | pytest + mypy | no | se reprodujo aquí (pasa) |
| `exposing-prometheus-metrics:43` | test de integración `/metrics` | no | se reprodujo aquí (pasa) |
| `logging-json-to-loki:48` | línea JSON con `trace_id` | no | |
| `logging-json-to-loki:108` | `alloy validate`, punta a punta | no | herramienta externa |
| `tracing-with-opentelemetry:46` | `InMemorySpanExporter` + Tempo | no | el test publicado no corre (TS-07) |
| `defining-grafana-slos:55` | `promtool` | no | herramienta externa |
| `defining-grafana-slos:168` | `amtool` | no | herramienta externa |
| `defining-grafana-slos/references/stack.md:3` | versiones del stack | no | `extract.py` no alcanza `references/` |
| `architecting-react-apps:83` | `tsc --strict` | no | |
| `building-axios-clients:391` | "7 casos verificados" | no | publica 2 casos; `skill.test.tsx` prueba otros 2 |
| `optimizing-react-renders:48` | `tsc --strict` | no | |
| `optimizing-react-renders:131` | `vite build` (Vite 8) | no | el arnés usa Vite 7 (TS-14) |
| `routing-with-react-router:52` | `tsc` y `vite build` | no | |
| `using-react-19-actions:93` | `tsc --strict` | no | |

A la inversa, tienen test sin estar marcados como verificados: `createHttpClient` (`building-axios-clients:197`), `ErrorBoundary` (`handling-react-errors:119`), `NameForm` (`using-react-19-actions:71`), `safeNext` (`routing-with-react-router:137`).

### TS-13: las herramientas que los sellos nombran no corren en ninguna suite

- **Severidad:** media
- **Tipo:** d
- **Evidencia:**
  - `tests/snippets/web/package.json:5-8`: solo `pretest` y `vitest run`, sin `tsc`.
  - `tests/snippets/web/tsconfig.json:3-4`: sin `exactOptionalPropertyTypes`, frente a `building-axios-clients:43` y `using-react-19-actions:93`, que lo afirman.
  - `README.md:66`: "lo ejecutan".
- **Confirmación:** ejecutado. `npx tsc --noEmit -p .` da `generated/components/ErrorBoundary.tsx(63,20): error TS2339: Property 'env' does not exist on type 'ImportMeta'`. Es un error del arnés, porque falta `vite/client` en `types`, y nadie lo ve porque nadie corre `tsc`. Con `--exactOptionalPropertyTypes --noUncheckedIndexedAccess` el único error es el mismo: el código publicado está bien. `mypy` tampoco corre en la suite Python; aquí se corrió aparte y pasó.
- **Impacto:** vitest quita tipos sin chequearlos, así que un error de tipos publicado no pone nada en rojo.
- **Plan de corrección:**
  1. `tsconfig.json`: `"types": ["vitest/globals", "vite/client"]` y `"exactOptionalPropertyTypes": true`.
  2. `package.json`: `"test": "tsc --noEmit && vitest run"`.
  3. En Python, agregar `mypy --strict` sobre el módulo generado, junto con el proyecto de TS-12.
  4. Verificación: un error de tipo introducido adrede pone en rojo `npm test`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** frontend (`tsconfig` del arnés; el código no cambia).

### TS-14: el arnés prueba con versiones que las skills excluyen o que no son las prescritas

- **Severidad:** baja
- **Tipo:** d
- **Evidencia:**
  - `README.md:70`: `uv run --with pytest --with pydantic-settings --with fastapi --with sqlalchemy ...` (sin pin). Frente a `scaffolding-fastapi-backends/SKILL.md:73`: `"sqlalchemy[asyncio]>=2.0.40,<2.1"`, y `tracing-with-opentelemetry:26`.
  - `tests/snippets/web/package.json:14`: `"@vitejs/plugin-react": "^5.0.0"`. Frente a `optimizing-react-renders:131`: "Vite 8 + `@vitejs/plugin-react` 6".
- **Confirmación:** ejecutado. El comando del README resolvió **SQLAlchemy 2.1.6**, y `node_modules` tiene plugin-react 5.2.0 y Vite 7.3.7. Con el pin propuesto también da 7 passed (ejecutado), pero el comando publicado corre `test_datetime_keeps_instant_on_sqlite` sobre una versión prohibida.
- **Impacto:** el test certifica `UtcDateTime` en una versión que el stack no usa, y una regresión específica de 2.0 no se vería.
- **Plan de corrección:** `README.md:70` y el docstring de `test_python_snippets.py:4`: `--with 'sqlalchemy>=2.0.40,<2.1'`. En `package.json`, alinear con Vite 8 y plugin-react 6 si el dueño lo confirma. Cambiar de mayor implica revisar `vitest.config.ts`. No se probó.
- **Decisión requerida:** ¿el arnés debe usar la versión mayor prescrita para frontend? Recomiendo sí.
- **Otros dominios afectados:** frontend; backend solo por el pin.

### TS-15: la matriz exige un 500 forzado que el `client` publicado no puede probar

- **Severidad:** baja
- **Tipo:** a, c
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:28`: "cubrir la matriz: happy path, 422 de validación (parametrizado), regla de negocio, 401, 403, 404, 409, y un 500 forzado".
  - `:156`: `AsyncClient(transport=ASGITransport(app=app), ...)`.
  - `:274`: el checklist baja a "happy path + 422 + casos de negocio + 404/403 según aplique".
  - `handling-fastapi-errors/SKILL.md:213`: `ASGITransport(app=app, raise_app_exceptions=False)`.
- **Confirmación:** ejecutado. Con `client`, `RuntimeError` se propaga al test. Con `raise_app_exceptions=False`, 500, `internal_error` y sin `hunter2`.
- **Impacto:** el 500 no se puede escribir con el fixture publicado, y el checklist permite omitir 401, 409 y 500.
- **Plan de corrección:** agregar al conftest un fixture `client_no_raise` que comparta el override, citar `handling-fastapi-errors` en `:28`, e igualar `:274` a `:28`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### TS-16: los dos `pyproject` publicados difieren en `filterwarnings`

- **Severidad:** baja
- **Tipo:** b
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:56`: `filterwarnings = ["error::sqlalchemy.exc.SAWarning"]`.
  - `scaffolding-fastapi-backends/SKILL.md:86-90`: la misma sección sin esa línea.
- **Confirmación:** por lectura. Se ejecutó con ambos y la suite pasa con los dos, así que no hay rotura, solo divergencia.
- **Impacto:** un proyecto creado con el scaffolding no convierte en error los `SAWarning` que la skill de testing quiere ver.
- **Plan de corrección:** canónico testing, por ser el dueño del tema: agregar la línea en `scaffolding:90`. Conviene incluir también `pythonpath` (TS-02).
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend.

### TS-17: dos bloques de entorno para el mismo conftest, y un comentario que invita a testear contra la base de desarrollo

- **Severidad:** baja
- **Tipo:** b
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:69`: `os.environ.setdefault("DB_HOST", "test-db.invalid")  # no se usa: SQLite o testcontainers`; `:70`: `"test"`; `:71`: `https://errors.test.invalid`.
  - `configuring-fastapi-settings/SKILL.md:173-175`: `"localhost"`, `"test_db"`, `https://errors.example.com`.
  - `references/docker.md:165`: `# expuesto para correr alembic/seed/tests desde el host`, frente a `testing-fastapi-endpoints:38` ("Tests contra la base de desarrollo | borran datos reales").
- **Confirmación:** por lectura.
- **Impacto:** con `localhost`, un test que se salte el override llega a la base de desarrollo expuesta; con `.invalid`, falla al resolver. El comentario de `docker.md` legitima ese camino.
- **Plan de corrección:** canónico testing, porque `.invalid` no se puede resolver.
  1. En `configuring-fastapi-settings:169-176`, referenciar el conftest o usar los mismos valores.
  2. `docker.md:165` → `# expuesto para correr alembic y seed desde el host`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend. Datos canónicos: `DB_HOST=test-db.invalid`, `DB_NAME=test`, `ERRORS_BASE_URL=https://errors.test.invalid`.

### TS-18: la skill dice que SQLite no tiene índices parciales ni CHECK

- **Severidad:** baja
- **Tipo:** b, d
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:20`: "para lo que SQLite no tiene (`FOR UPDATE`, índices parciales, JSONB, CHECK reales, tipos)".
  - `modeling-postgres-with-sqlalchemy/SKILL.md:164-167`: declara `sqlite_where` porque SQLite sí los crea.
- **Confirmación:** ejecutado. `create_product(stock=-1)` en SQLite da `IntegrityError ... stock_non_negative`; `sqlite_master` contiene `WHERE status = 'pending'`.
- **Impacto:** el agente puede creer que un test de CHECK necesita Docker, u omitirlo en el modo por defecto.
- **Plan de corrección:** `:20` → "lo que SQLite no tiene (`FOR UPDATE`, JSONB, tipos estrictos, concurrencia real)". Canónico `modeling`, comprobado.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### TS-19: el "test de contrato sobre todas las skills" no lee `references/` ni `get_settings().X`

- **Severidad:** baja
- **Tipo:** d
- **Evidencia:**
  - `DIAGNOSTICO.md:152`: "test de contrato sobre todas las skills".
  - `tests/snippets/extract.py:32`: `SKILLS.glob("*/*/SKILL.md")`.
  - `tests/snippets/test_python_snippets.py:60`: `re.findall(r"\bsettings\.([A-Z][A-Z0-9_]+)\b", text)`.
  - `:51-52`: `settings.ALGORITHM` en `CONSTANTS`, con comentario "(ver security.md)". Pero `security.md` no se escanea, y allí `ALGORITHM` no se lee de `settings`, por lo que la entrada es código muerto.
- **Confirmación:** ejecutado por inyección sobre la copia.
  - `settings.CAMPO_QUE_NO_EXISTE` en `references/security.md` y `get_settings().OTRO_CAMPO_QUE_NO_EXISTE` en un `SKILL.md`: el test **pasa**.
  - Testigo: `settings.CAMPO_QUE_NO_EXISTE` en un `SKILL.md`: el test **falla**.
  - Hoy no falta ningún campo real: las lecturas de `security.md` existen en `Settings`.
- **Impacto:** puede reaparecer uno de los 8 bugs de §7 bis sin que el test lo vea.
- **Plan de corrección:**
  1. `all_text()` → `SKILLS.rglob("*.md")` más `templates/*.py`.
  2. Regex `\b(?:get_)?settings(?:\(\))?\.([A-Z][A-Z0-9_]+)\b`.
  3. Vaciar `CONSTANTS`.
  4. Permitir en `skill_path`/`block` rutas de `references/`, para que TS-12 pueda cubrirlas.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### TS-20: conteos y versiones que el repo no respalda

- **Severidad:** baja
- **Tipo:** d
- **Evidencia y confirmación:**

  | Afirmación | Realidad | Confirmación |
  |---|---|---|
  | `DIAGNOSTICO.md:94` "38 bloques Python [...] 0 errores" | **46** bloques `python`, **1** con error (13 YAML sí coincide) | ejecutado |
  | `layering-fastapi-apps:68` "17 tests" | `DIAGNOSTICO.md:84` dice 18; ninguno está en el repo | por lectura |
  | `testing-fastapi-endpoints:59` "PostgreSQL 16" | `DIAGNOSTICO.md:84` y `configuring-sqlalchemy-sessions:43` dicen PostgreSQL 17; el commit `edd80d7` cambió la imagen de 17 a 16 con un bloque que no parsea | ejecutado (`git show`) |
  | `building-axios-clients:391` "7 casos" | publica 2 casos | ejecutado (`grep`) |
  | `DIAGNOSTICO.md:100-136` árbol "definitivo" | no incluye `tests/snippets/` | por lectura |

  Sí coinciden: 20 skills + 1 índice, y "26 paneles" (ejecutado: 26, de los cuales 7 son filas).

- **Impacto:** quien lea el diagnóstico sobreestima la cobertura; la versión de PostgreSQL verificada es ambigua.
- **Plan de corrección:** actualizar `DIAGNOSTICO.md:94` y añadir `tests/snippets/` a `:100-136`. Unificar versión: 16 ya pasa aquí con el conftest corregido, así que corregir `:84`, `:86`, `:87` y las de `configuring-sqlalchemy-sessions` tras re-correr, o indicar la fecha de cada corrida. Quitar los conteos en las skills: envejecen.
- **Decisión requerida:** ¿la versión de PostgreSQL de referencia es 16? Todo lo publicado para desplegar (`docker.md:157`, `ci.md:71`, conftest) dice 16. Recomiendo 16, y re-verificar lo que dice 17.
- **Otros dominios afectados:** database (versión en `configuring-sqlalchemy-sessions` y `migrating-with-alembic`), backend (`layering:68`), frontend (`building-axios-clients:391`).

---

## Dudosos

No los cuento como inconsistencias, pero el dueño puede querer decidir.

- **D1. `setdefault` para `APP_ENV`.** `testing-fastapi-endpoints:65` usa `os.environ.setdefault("APP_ENV", "test")`. Si el shell tiene `APP_ENV=dev`, se lee el `.env` local, lo que `:29` y `configuring-fastapi-settings:20` buscan evitar. Es defendible para que CI pueda inyectar valores. Sugerencia: asignación directa solo para `APP_ENV`. Por lectura.
- **D2. Fallo intermitente de testcontainers.** 1 corrida de unas 13 dio `TimeoutError: container did not become running` en 0,73 s. Coincide con `DIAGNOSTICO.md:172`, aunque en esta sesión otros auditores usaban Docker a la vez. No lo atribuyo a la skill.
- **D3. `unit-testing` no nombra `pytest-asyncio` ni `asyncio_mode`.** Sin esa configuración, sus 5 tests fallan (ejecutado). Depende de leer la otra skill o el scaffolding. Una línea en `unit-testing` lo resuelve.
- **D4. Las métricas no se revierten con el rollback.** `exposing-prometheus-metrics:27` sugiere `REGISTRY.get_sample_value(...)`. En una suite con rollback por test, el contador sigue acumulado, así que hay que afirmar diferencias. No contradice nada; falta aclararlo.
- **D5. `TestClient` sin receta.** La `description` y `:17` lo admiten para apps síncronas, y `configuring-sqlalchemy-sessions:98` publica la variante síncrona, pero no hay conftest síncrono. La advertencia httpx → httpx2 es real (ejecutado: `Using httpx with starlette.testclient is deprecated`), solo aplica a `TestClient`, y el `AsyncClient` del conftest no la emite.
- **D6. `dependency_overrides.clear()`.** `testing-fastapi-endpoints:158` borra también overrides de otros fixtures (por ejemplo `get_settings`, `configuring-fastapi-settings:27`). `pop(get_db)` es más preciso. Sin caso roto publicado.
- **D7. Ubicación de los tests de integración.** El bloque "Tests:" no tiene ruta, y solo `tests/unit/` está fijada. `unit-testing:25` manda el estilo 2 ahí. Si hubiera `tests/integration/`, faltaría definir `__init__.py` (basenames repetidos).
- **D8. Imports duplicados en `modeling-postgres-with-sqlalchemy:69-73`.** Inocuo, ejecuta bien. Es del dominio database.

## Lo que no se pudo verificar

- **Pipeline de CircleCI** (TS-09): no se ejecutó ni se validó con `circleci config validate`.
- **Afirmaciones "rojo antes del arreglo" de `DIAGNOSTICO.md:160`:** se comprobó que los 8 tests existen y pasan, no que fallaran antes.
- **Alternativa de sesión por request (TS-04) con el test de tracing:** no se corrió esa combinación.
- **Bloques de autenticación de `security.md`:** no se montaron en el proyecto de referencia. Tampoco se ejecutaron los tests de auth obligatorios, que no tienen código publicado.
- **`tests/snippets/__pycache__/`** apareció en el repo a las 16:56 durante la sesión (ignorado por git). Mis comandos corren sobre la copia y ninguno lo apunta. Quizás lo creó otro auditor, pero no puedo confirmarlo, así que no lo toqué. Conviene borrarlo al final.
