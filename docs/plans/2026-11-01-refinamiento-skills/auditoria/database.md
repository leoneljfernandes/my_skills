# Auditoría de la rama DATABASE

Alcance: `configuring-sqlalchemy-sessions`, `modeling-postgres-with-sqlalchemy`, `migrating-with-alembic` y sus contratos con backend, testing y observability. Repo en `54d8c96`, sin cambios (`git status` limpio al terminar).

## Cómo se comprobó

Armé en `/tmp/claude-1000/-home-leonel-my-skills/927a91bb-bc0d-4938-a40b-4a8225428464/scratchpad/audit/database/proj/` un proyecto con los bloques **extraídos de las SKILL.md** (`tests/snippets/extract.py`): `config.py`, `database.py`, `models/base.py`, entidades, schemas, repositorio y service de `layering`, `errors.py`, `env.py`, `alembic.ini`, migración manual, `conftest.py`, factories y tests de `testing-fastapi-endpoints`. Lo único que agregué a mano: `app/models/__init__.py`, imports faltantes de los fragmentos, un router mínimo y `OrderRepository` (la skill lo usa pero no lo muestra).

Entorno: Python 3.14.8, SQLAlchemy 2.0.55, Alembic 1.20.1, asyncpg 0.32.0, psycopg 3.3.6, pytest 9.2.0, pytest-asyncio 1.4.1.post1, testcontainers 4.15.0, PostgreSQL `16-alpine`, PgBouncer 1.26.1 (`edoburu/pgbouncer`). Contenedores efímeros, ya borrados; no se tocaron los `turnapp_*`.

Resumen: 4 altas, 8 medias, 8 bajas. Al final: Dudosos, lo que se probó y salió bien, y lo que no se pudo verificar.

---

### DB-01: el `conftest.py` publicado no compila
- **Severidad:** alta
- **Tipo:** c, d
- **Evidencia:**
  - `skills/testing/testing-fastapi-endpoints/SKILL.md:116`: `with PostgresContainer("postgres:16-alpine", driver="asyncpg")  # = la versión de producción as pg:`
  - `skills/testing/testing-fastapi-endpoints/SKILL.md:59`: "`tests/conftest.py` (verificado: la misma suite pasa en SQLite y en PostgreSQL 16 vía testcontainers)"
  - `DIAGNOSTICO.md:94`: "parseo de 38 bloques Python y 13 YAML ... 0 errores"
- **Confirmación:** ejecutado. `ast.parse` del bloque: `SyntaxError: expected ':'`. Sobre los 46 bloques `python` de todas las skills, es el único que falla. El comentario se insertó dentro de la sentencia en `edd80d7` (`git log -S`). Con `as pg:` antes del comentario, la suite pasa: SQLite 4 passed + 1 skipped; `TEST_DB=postgres` 5 passed.
- **Impacto:** un agente que copia el conftest obtiene un archivo que no importa, y ningún test corre, tampoco en SQLite.
- **Plan de corrección:** canónico: la sentencia `as pg:`. En `testing-fastapi-endpoints/SKILL.md:116`: `with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:  # = la versión de producción`. Agregar a `tests/snippets/test_python_snippets.py` un test que haga `ast.parse` de cada bloque `python` de cada skill. Hoy daría exactamente este fallo y evita que reaparezca.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** testing (dueño del archivo; puede venir duplicado en su informe).

### DB-02: `VALIDATE` en la misma transacción que `ADD ... NOT VALID` bloquea lecturas y escrituras
- **Severidad:** alta
- **Tipo:** a
- **Evidencia:**
  - `skills/database/migrating-with-alembic/SKILL.md:30`: "Constraints sobre tablas grandes: `NOT VALID` y después `VALIDATE CONSTRAINT`, que valida sin bloquear escrituras."
  - `migrating-with-alembic/SKILL.md:165-166`: "NOT VALID: se aplica a filas nuevas sin escanear la tabla (lock breve); VALIDATE recorre las existentes con un lock que no bloquea lecturas ni escrituras."
  - `migrating-with-alembic/SKILL.md:167-173`: `op.create_check_constraint(... postgresql_not_valid=True)` seguido, en el mismo `upgrade()`, por `op.execute("ALTER TABLE orders VALIDATE CONSTRAINT ck_orders_order_status")`.
  - `migrating-with-alembic/SKILL.md:149`: "CHECK sin bloqueo + índice concurrente (verificada...)"
- **Confirmación:** ejecutado contra PostgreSQL 16 con 6 M de filas. `upgrade --sql` muestra ambos `ALTER` entre un solo `BEGIN`/`COMMIT`. En vivo, durante el `VALIDATE`: `pg_locks` = `AccessExclusiveLock|ALTER TABLE orders VALIDATE...`, y un `SELECT` concurrente con `lock_timeout=200ms` falló con `canceling statement due to lock timeout`. El lock del `ADD` se retiene hasta el `COMMIT`. Control con revisiones separadas: durante el `VALIDATE`, `locks=[ShareUpdateExclusiveLock]` y el `SELECT` respondió.
- **Impacto:** el ejemplo es justo lo que la skill dice evitar: en una tabla grande bloquea todo el tráfico durante el escaneo, y el comentario afirma lo contrario.
- **Plan de corrección:** canónico: la regla de L30; el ejemplo la viola. Dividir el ejemplo en revisiones (junto con DB-03, ver su plan): una con `ADD ... NOT VALID`, otra con `VALIDATE`. `transaction_per_migration=True` ya las separa en dos transacciones. Agregar a la regla L30: "en revisiones separadas: en la misma transacción, el lock del `ADD` dura todo el `VALIDATE`". Agregar al checklist L217 lo mismo. Verificación: `upgrade --sql` debe mostrar un `COMMIT` entre ambos `ALTER`; test estático que falle si un mismo bloque contiene `postgresql_not_valid` y `VALIDATE CONSTRAINT`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-03: tras un `lock_timeout`, reintentar la migración falla, o deja un índice inválido con `alembic check` en verde
- **Severidad:** alta
- **Tipo:** c, a
- **Evidencia:**
  - `migrating-with-alembic/SKILL.md:23`: "`SET lock_timeout` al inicio. Si la tabla está tomada, la migración falla rápido"
  - `migrating-with-alembic/SKILL.md:176-180`: `with op.get_context().autocommit_block(): op.create_index("ix_products_name", ..., postgresql_concurrently=True, if_not_exists=True)`
  - `migrating-with-alembic/SKILL.md:167-173`: el CHECK va antes, en el mismo `upgrade()`, sin `IF NOT EXISTS`.
  - `migrating-with-alembic/SKILL.md:214`: "`alembic check` dice `No new upgrade operations detected.`" como criterio de cierre; ningún punto del checklist revisa `indisvalid`.
- **Confirmación:** ejecutado. Con un `UPDATE` abierto sobre `products` y la migración literal:
  1. A los 5 s: `LockNotAvailableError` en `CREATE INDEX CONCURRENTLY`.
  2. Estado: `alembic current` sigue en la revisión anterior, pero el CHECK **ya quedó commiteado** (`autocommit_block` commitea lo previo) y existe `ix_products_name` con `indisvalid = f`.
  3. Re-`upgrade`: `DuplicateObjectError: constraint "ck_orders_order_status" ... already exists`. La migración no es reintentable.
  4. Quitando el CHECK a mano y reintentando (lo que pasaría con una migración de solo índice): `IF NOT EXISTS` saltea el índice, `current` = head, `indisvalid` sigue en `f` y `alembic check` dice `No new upgrade operations detected.`
- **Impacto:** `lock_timeout` hace que esta falla sea la esperable en una tabla con tráfico. El agente termina con el deploy trabado, o con un índice inservible que todos los criterios dan por bueno y queries que siguen lentas.
- **Plan de corrección:** canónico: la regla de fallar rápido; el ejemplo tiene que soportar el reintento. En `migrating-with-alembic/SKILL.md` reemplazar el ejemplo por tres revisiones (probadas así, incluido el reintento: `indisvalid = t`):
  ```python
  # 1) op.create_check_constraint("order_status", "orders", sa.text("..."), postgresql_not_valid=True)
  # 2) op.execute("ALTER TABLE orders VALIDATE CONSTRAINT ck_orders_order_status")
  # 3) índice, sola en su revisión
  with op.get_context().autocommit_block():
      op.drop_index("ix_products_name", table_name="products", postgresql_concurrently=True, if_exists=True)
      op.create_index("ix_products_name", "products", ["name"], postgresql_concurrently=True)
  ```
  Reglas nuevas en L31: "una revisión con `autocommit_block` no mezcla DDL transaccional"; "`IF NOT EXISTS` no sirve para reintentar: acepta un índice inválido". Agregar al checklist: `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid` no devuelve filas.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-04: `env.py` usa la misma URL que la app, y detrás de PgBouncer `lock_timeout` se filtra y las prepared statements pueden romper
- **Severidad:** alta (solo en el modo PgBouncer que la skill ofrece)
- **Tipo:** b, c
- **Evidencia:**
  - `configuring-sqlalchemy-sessions/SKILL.md:24`: "**PgBouncer en modo transaction**: ... desactivar las prepared statements de asyncpg"
  - `configuring-sqlalchemy-sessions/SKILL.md:159`: "`migrating-with-alembic`: el `env.py` reutiliza `get_settings().DATABASE_URL`."
  - `migrating-with-alembic/SKILL.md:225`: "`configuring-sqlalchemy-sessions`: misma `DATABASE_URL`."
  - `migrating-with-alembic/SKILL.md:108-109`: `connection.execute(text("SET lock_timeout = '5s'"))` + `connection.commit()`
  - `migrating-with-alembic/SKILL.md:116-120`: `async_engine_from_config(... poolclass=pool.NullPool)`, sin `statement_cache_size`.
  - `configuring-fastapi-settings/SKILL.md:205`: "Alembic (`env.py`), el seed y la telemetría usan `get_settings()`, no URLs propias."
- **Confirmación:** ejecutado contra PgBouncer 1.26.1 en modo transaction.
  - Un cliente hace `SET lock_timeout` + `commit` como `env.py`. Otros cinco clientes concurrentes leen `(pid, lock_timeout)`: `[(247,'0'), (248,'0'), (251,'5s'), (249,'0'), (250,'0')]`. El valor queda en un backend que usan otros clientes, y los demás backends no lo tienen.
  - `alembic upgrade head` por PgBouncer con su configuración por defecto (admite prepared statements): funciona.
  - Con `max_prepared_statements = 0` (comportamiento anterior a PgBouncer 1.21): `DuplicatePreparedStatementError: prepared statement "__asyncpg_stmt_7__" already exists`. En esa misma configuración, las opciones de L24 sí funcionan (30/30).
  - No medí bajo carga que la migración aterrice en otro backend y corra sin `lock_timeout`: lo demostrado es que el valor pertenece al backend y no al cliente.
- **Impacto:** en un proyecto con PgBouncer, el agente deja las migraciones por la URL del pool. La protección de L23 deja de estar garantizada, sin aviso, justo donde más importa, y el `SET` queda en una conexión compartida con la app.
- **Plan de corrección:** canónico: las migraciones van **directo a Postgres**.
  - `configuring-fastapi-settings/SKILL.md`: agregar `DB_MIGRATION_HOST: str | None = None`, `DB_MIGRATION_PORT: int | None = None` y el computed `MIGRATION_DATABASE_URL` con `repr=False`, que cae en `DATABASE_URL` si no se definen.
  - `migrating-with-alembic/SKILL.md:73`: leer `MIGRATION_DATABASE_URL`; L225: "misma base; detrás de PgBouncer, URL directa".
  - `configuring-sqlalchemy-sessions/SKILL.md:24` y `:159`: la misma aclaración.
  - Test: `test_settings_has_every_field_other_skills_read` usa `\bsettings\.` y no ve `get_settings().X`, así que hoy no cubriría `env.py`; ampliar la regex. Agregar un test de que `MIGRATION_DATABASE_URL` cae en `DATABASE_URL`.
- **Decisión requerida:** ¿campo nuevo en `Settings` o solo una advertencia? Recomiendo el campo: sin él, la regla de `configuring-fastapi-settings` ("no URLs propias") impide seguir la advertencia. Alternativa si PgBouncer no es un caso real: quitar el modo de `sessions`.
- **Otros dominios afectados:** backend (`configuring-fastapi-settings`: campos nuevos, `.env.example`; `docker.md`, solo si se documenta PgBouncer en compose).

### DB-05: "autogenerate NO detecta CHECK" es falso al crear tablas, y seguirlo duplica el constraint
- **Severidad:** media
- **Tipo:** a, c
- **Evidencia:**
  - `migrating-with-alembic/SKILL.md:25`: "Escribir a mano lo que autogenerate **no detecta**: ... `CHECK` constraints (incluido el CHECK de un `Enum` no nativo)"
  - `migrating-with-alembic/SKILL.md:164`: "Escrita a mano: autogenerate NO detecta CHECK constraints."
  - `migrating-with-alembic/SKILL.md:216`: "con los CHECK que autogenerate no ve."
  - `modeling-postgres-with-sqlalchemy/SKILL.md:138-139,160,177-185`: los modelos declaran CHECK y `create_constraint=True`.
- **Confirmación:** ejecutado. `revision --autogenerate` con los modelos de la skill genera en `create_table`: `sa.CheckConstraint("price >= 0", name=op.f("ck_products_price_non_negative"))`, el de `stock`, el de `quantity`, y `sa.Enum(..., name="order_status", native_enum=False, create_constraint=True, length=20)`. En la base: `ck_orders_order_status` existe. Aplicar encima la migración manual de L151-188: `DuplicateObjectError: constraint "ck_orders_order_status" for relation "orders" already exists`.
- **Impacto:** para una tabla nueva, un agente que lee L216 busca "los CHECK que no ve", agrega el manual y `upgrade` falla. El §5.3 de `DIAGNOSTICO.md` sigue siendo cierto solo para tablas existentes: no es una reaparición, es la regla generalizada de más.
- **Plan de corrección:** canónico: lo observado. Lo que no se detecta es **agregar o cambiar** un CHECK sobre una tabla existente, incluida la lista de valores del Enum. Redactar así L25, L164 y L216; L149 debe decir "sobre una tabla existente". Agregar: "en `create_table` autogenerate sí los escribe: no duplicarlos". Verificación: test con `alembic.autogenerate` sobre `Order`, que afirme que el `create_table` renderizado contiene `create_constraint=True`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-06: la regla de `statement_timeout` por conexión no se puede combinar con PgBouncer, ni `build_engine` con `NullPool`
- **Severidad:** media
- **Tipo:** a, c
- **Evidencia:**
  - `configuring-sqlalchemy-sessions/SKILL.md:22`: "`application_name` y `statement_timeout` por conexión vía `connect_args`: trazabilidad en `pg_stat_activity` y ninguna query eterna." (sin condición)
  - `configuring-sqlalchemy-sessions/SKILL.md:64-69`: `connect_args={"server_settings": {... "statement_timeout": ...}}`
  - `configuring-sqlalchemy-sessions/SKILL.md:91-95`: el engine de PgBouncer no lo incluye y no lo explica.
  - `configuring-sqlalchemy-sessions/SKILL.md:58-61`: `build_engine` siempre pasa `pool_size`, `max_overflow`, `pool_timeout`.
- **Confirmación:** ejecutado contra PgBouncer 1.26.1, 30 clientes concurrentes por caso:
  - Snippet L91-95 literal: 30 ok.
  - Sumándole `server_settings` (lo que pide L22): 0 ok, `unsupported startup parameter: statement_timeout`.
  - `build_engine` + `poolclass=NullPool`: `TypeError: Invalid argument(s) 'pool_size','max_overflow','pool_timeout' sent to create_engine()`.
- **Impacto:** quien respeta L22 en modo PgBouncer no conecta. Quien copia L91-95 se queda sin `statement_timeout` sin saberlo. `Settings` no tiene forma de elegir el modo.
- **Plan de corrección:** canónico: L22 como objetivo ("ninguna query eterna"); el mecanismo depende del modo. Agregar a L24: "detrás de PgBouncer, `statement_timeout` se fija en el servidor (`ALTER ROLE app SET statement_timeout = '15s'`)". Hacer que `build_engine` ramifique con un campo `DB_PGBOUNCER: bool = False`. Test sin conexión: `build_engine` con la bandera construye el engine sin `TypeError`, con `NullPool` y sin `server_settings`.
- **Decisión requerida:** ¿`DB_PGBOUNCER` en `Settings` o dos bloques documentados? Recomiendo el campo, porque el código deja de divergir. Se decide junto con DB-04.
- **Otros dominios afectados:** backend (`configuring-fastapi-settings`, si se agrega el campo).

### DB-07: la variante síncrona no sale de `Settings`, lleva credenciales escritas y no aplica el timeout
- **Severidad:** media
- **Tipo:** a, b
- **Evidencia:**
  - `configuring-sqlalchemy-sessions/SKILL.md:18`: "`engine` y `SessionFactory` a nivel de módulo (`app/database.py`), creados desde `Settings`."
  - `configuring-sqlalchemy-sessions/SKILL.md:109`: `"postgresql+psycopg://app:secret@db:5432/app_db",`
  - `configuring-sqlalchemy-sessions/SKILL.md:110-114`: `pool_size=40`, etc. sin `connect_args`, contra L22.
  - `configuring-fastapi-settings/SKILL.md:124`: `"postgresql+asyncpg",` fijo en `DATABASE_URL`.
  - `configuring-fastapi-settings/SKILL.md:205`: "no URLs propias".
- **Confirmación:** ejecutado.
  - `create_engine(get_settings().DATABASE_URL)`: `MissingGreenlet` en la primera conexión.
  - psycopg con `connect_args={"server_settings": ...}` (forma de L64-69): `ProgrammingError: invalid connection option "server_settings"`.
  - psycopg con `connect_args={"application_name": "x", "options": "-c statement_timeout=15000"}`: `SHOW statement_timeout` = `15s`.
  - `create_async_engine` con `postgresql+psycopg`: conecta, así que el `env.py` async sirve también para un proyecto síncrono (eso no es un hallazgo).
- **Impacto:** quien elige la variante sync (que L17 ofrece) no tiene un camino que cumpla las reglas: o escribe la URL con la contraseña en el código, o pasa la de `Settings` y falla. Además no tiene `statement_timeout` ni la forma de configurarlo.
- **Plan de corrección:** canónico: L18 + `configuring-fastapi-settings`. En `Settings`, `DB_DRIVER: Literal["asyncpg", "psycopg"] = "asyncpg"`, usado en `DATABASE_URL`. En `sessions/SKILL.md:108-115`: `create_engine(settings.DATABASE_URL, ..., connect_args={"application_name": settings.APP_NAME, "options": f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS}"})`. En L22, nombrar las dos formas por driver. Test: `Settings(DB_DRIVER="psycopg").DATABASE_URL` empieza con `postgresql+psycopg`, más el test de contrato ya existente.
- **Decisión requerida:** ¿se mantiene la variante sync como camino completo? El directivo C de `DIAGNOSTICO.md:55` la exige ("SessionMaker async/sync"), así que recomiendo que sí, con `DB_DRIVER`.
- **Otros dominios afectados:** backend (`configuring-fastapi-settings`: `DB_DRIVER`).

### DB-08: el ejemplo y el anti-patrón de renombre contradicen expand/contract
- **Severidad:** media
- **Tipo:** a
- **Evidencia:**
  - `migrating-with-alembic/SKILL.md:26`: "**Zero-downtime (expand/contract)**: cada deploy debe funcionar con el esquema anterior y el nuevo."
  - `migrating-with-alembic/SKILL.md:218`: "Cambios incompatibles siguen expand/contract en deploys separados."
  - `migrating-with-alembic/SKILL.md:39`: "renombre = drop + add = datos perdidos | revisar y usar `op.alter_column(new_column_name=...)`"
  - `migrating-with-alembic/SKILL.md:190-198`: `op.alter_column("orders", "customer_email", new_column_name="buyer_email")` sin ninguna aclaración.
- **Confirmación:** por lectura. Releí el contexto: no hay ninguna salvedad de "ventana de mantenimiento". `RENAME COLUMN` es inmediato, así que el código anterior deja de encontrar `customer_email` hasta terminar el deploy.
- **Impacto:** un agente al que le piden renombrar copia el ejemplo, o sigue la fila del anti-patrón de L39, y produce la caída que L26 y L218 prometen evitar.
- **Plan de corrección:** canónico: L26. Encabezar L190: "Renombre con ventana de mantenimiento (app detenida o sin escrituras). Sin ventana: expand/contract: columna nueva, escribir en ambas, backfill, leer de la nueva, borrar la vieja". L39: agregar "...o expand/contract si no hay ventana". Verificación: lectura.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-09: el SQL para el DBA (`--sql`) no lleva `lock_timeout`
- **Severidad:** media
- **Tipo:** a, e
- **Evidencia:**
  - `migrating-with-alembic/SKILL.md:23`: "`SET lock_timeout` al inicio."
  - `migrating-with-alembic/SKILL.md:92-102`: `run_migrations_offline()` no lo emite; solo `do_run_migrations` (L106-109).
  - `migrating-with-alembic/SKILL.md:206`: "`uv run alembic upgrade head --sql > migration.sql  # SQL para revisión/DBA`"
- **Confirmación:** ejecutado. La salida de `upgrade --sql` no contiene `lock_timeout`. Con `context.execute("SET lock_timeout = '5s'")` después de `context.configure(...)` en modo offline, la primera línea pasa a ser `SET lock_timeout = '5s';`.
- **Impacto:** justo el camino usado en producciones con revisión manual aplica sin protección, y encola tráfico detrás del lock.
- **Plan de corrección:** canónico: L23. Agregar esa línea en `run_migrations_offline()`. Verificación: test que corra `upgrade --sql` y afirme que `lock_timeout` aparece antes del primer `ALTER`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-10: todas las skills importan de `app.models`, pero nadie define `app/models/__init__.py`
- **Severidad:** media
- **Tipo:** c, e
- **Evidencia:**
  - `modeling-postgres-with-sqlalchemy/SKILL.md:66`: "Base y mixins (`app/models/base.py`..."
  - `migrating-with-alembic/SKILL.md:64`: `from app.models import Base, UtcDateTime  # importa el paquete → registra TODOS los modelos`
  - `testing-fastapi-endpoints/SKILL.md:85`: `from app.models import Base`
  - `layering-fastapi-apps/SKILL.md:79,116`: `from app.models import OrderStatus`, `from app.models import Product`; L25: `models/` sin desglose.
  - `grep -rn "__init__\.py" skills/`: sin resultados.
- **Confirmación:** ejecutado. Con `__init__.py` vacío, `alembic current`: `ImportError: cannot import name 'Base' from 'app.models'`. Con las re-exportaciones que escribí, todo funciona.
- **Impacto:** el comentario de `env.py` promete que importar el paquete registra todo, pero eso depende de un archivo no documentado. Si el `__init__.py` existe y no importa un modelo nuevo, autogenerate propone borrar su tabla (L17 advierte el síntoma pero no la causa). Además, `UtcDateTime` debe re-exportarse, lo cual nada indica.
- **Plan de corrección:** canónico: `from app.models import ...`, usado por todas las skills que importan modelos. En `modeling/SKILL.md`, después de las entidades:
  ```python
  # app/models/__init__.py: importar cada módulo aquí registra sus tablas en Base.metadata
  from app.models.base import Base, BigIntPK, TimestampMixin, UtcDateTime
  from app.models.order import Order, OrderStatus
  from app.models.product import Product
  ```
  Regla: "modelo nuevo = línea nueva acá"; y en `layering/SKILL.md:25` mencionar `base.py` + `__init__.py`. Verificación: el test de ejecución de `env.py` de DB-12.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend (`layering-fastapi-apps`: árbol), testing (ningún cambio de código; se apoya en esto).

### DB-11: `flush` + `rollback` del service borran los datos de la factory en el fixture de savepoint
- **Severidad:** media
- **Tipo:** b, c
- **Evidencia:**
  - `handling-fastapi-errors/SKILL.md:25`: "Antes de lanzar el error de dominio, hacer `rollback`"; L197: `await self._session.rollback()`
  - `testing-fastapi-endpoints/SKILL.md:25`: "hacen `flush` (obtienen id sin commitear)"; L276: "Los helpers de datos hacen `flush`, no `commit`"
  - `testing-fastapi-endpoints/SKILL.md:24`: "el test y la app ven los mismos datos sin commitear."
  - `modeling-postgres-with-sqlalchemy/SKILL.md:45`: "`async with session.begin_nested():` (SAVEPOINT) cuando una parte puede fallar sin abortar el todo (importaciones por lote, \"crear si no existe\")."
- **Confirmación:** ejecutado en SQLite, con un router mínimo mío que aplica el patrón de `handling:193-199`. Test: `create_product`, POST con el mismo SKU, 409. Después: `product in db_session` = False, `count = 0`, `db_session.refresh(product)` → `InvalidRequestError: Instance ... is not persistent within this Session`. El test publicado (L206-214) pasa porque no vuelve a leer nada. Con `async with db.begin_nested(): add + flush` en lugar de `rollback`: `count = 1`, `refresh` ok, y los 4 tests de `test_e2e` siguen pasando.
- **Impacto:** el `rollback` vuelve al savepoint del test, no al del caso de uso. Cualquier test que verifique "tras el 409 el registro original sigue intacto" falla por una razón ajena al código bajo prueba, y el agente tiende a resolverlo con `commit` en la factory, cosa que el checklist prohíbe.
- **Plan de corrección:** canónico: `modeling` L45, porque resuelve el caso sin deshacer lo anterior. En `handling/SKILL.md:190-200` y L25:
  ```python
  try:
      async with self._session.begin_nested():
          self._products.add(product)
          await self._session.flush()
  except IntegrityError as exc:
      raise ConflictError(f"SKU {data.sku} already exists") from exc
  await self._session.commit()
  ```
  En `testing/SKILL.md`: añadir al test de 409 una aserción de que el producto original sigue existiendo.
- **Decisión requerida:** ¿savepoint en el service (recomendado) o conservar el `rollback` y documentar en testing que tras un conflicto los datos de la factory desaparecen? La segunda opción deja igual el código del service, pero es una trampa permanente.
- **Otros dominios afectados:** backend (`handling-fastapi-errors`), testing.

### DB-12: los bloques "verificados" de la rama no tienen el test que el README exige
- **Severidad:** media
- **Tipo:** d
- **Evidencia:**
  - `README.md:66`: "Un bloque que el texto marca como **verificado** tiene su test en `tests/snippets/`."
  - `configuring-sqlalchemy-sessions/SKILL.md:25,43,98`; `modeling-postgres-with-sqlalchemy/SKILL.md:66,213`; `migrating-with-alembic/SKILL.md:50,149`: los bloques marcados.
  - `tests/snippets/test_python_snippets.py:94-118`: único test de base de datos: `UtcDateTime` sobre SQLite (no PostgreSQL 16, como dice `modeling` L66, y sin mixins ni `Base`).
  - Versiones: `modeling:66` y `testing:59` dicen "PostgreSQL 16"; `sessions:43,98`, `migrating:50` dicen 17; `DIAGNOSTICO.md:84,87` dice 17 para todo, incluido testcontainers; el stack fijado es 16 (`docker.md:157`, `testing:116`).
- **Confirmación:** por lectura (test + `grep` de marcadores). Es un dato ya admitido en parte: `DIAGNOSTICO.md:170` declara que los proyectos de referencia están fuera del repo, pero la regla del README sigue afirmando lo contrario. DB-01, DB-02 y DB-03 están en bloques marcados como verificados o derivados de ellos.
- **Impacto:** el agente y el dueño confían en una etiqueta que no impide regresiones. `edd80d7` y `2daa512` (origen de DB-01 y DB-13) tocaron bloques con esa etiqueta sin que nada fallara.
- **Plan de corrección:** canónico: la regla del README; es la que da valor a la etiqueta. Mínimo sin Docker en `tests/snippets/`: `ast.parse` de todos los bloques; bloques de `sessions` con `create_async_engine` (sin conectar); `Base` + entidades en SQLite; autogenerate offline de `env.py`. Con Docker, marcados `TEST_DB=postgres`: round-trip de `env.py` y migración manual, savepoints, `SKIP LOCKED`, optimista. Unificar las etiquetas en PostgreSQL 16 tras volver a correrlas. El proyecto de `.../scratchpad/audit/database/proj/` sirve de punto de partida.
- **Decisión requerida:** ¿implementar los tests o relajar el README a "verificado una vez, sin test"? Recomiendo tests para DB; lo que requiere Docker puede ir en un job aparte. Esta decisión es transversal a los 5 dominios.
- **Otros dominios afectados:** todos (la regla es global); testing en especial (`:59`).

### DB-13: imports duplicados en `app/models/base.py`, que hacen fallar `ruff check`
- **Severidad:** baja
- **Tipo:** a, d
- **Evidencia:**
  - `modeling-postgres-with-sqlalchemy/SKILL.md:69-73`: `from datetime import datetime` / `from typing import Annotated, Any, ClassVar` y de nuevo `from datetime import UTC, datetime` / `from typing import Annotated, Any, ClassVar`.
  - `migrating-with-alembic/SKILL.md:53-58`: `from typing import Any` separado por línea en blanco de `logging.config`.
  - `scaffolding-fastapi-backends/SKILL.md:109`: "`uv run ruff check` pasan"; `DIAGNOSTICO.md:85`: "`ruff` (E,F,I,UP,B,SIM,ASYNC) | sin errores".
- **Confirmación:** ejecutado. `ruff check --isolated` sobre `base.py`: 4 `F811` (y `I001` con `--select I`). Sobre `env.py`: `I001`. Los duplicados vienen de `2daa512`.
- **Impacto:** el proyecto no cumple el checklist del scaffolding hasta reparar el bloque.
- **Plan de corrección:** borrar L69-71 en `modeling`; ordenar los imports de `env.py`. Verificación: extender el test de bloques con `ruff check --select F,I` sobre los bloques completos.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-14: `result.rowcount` no pasa `mypy --strict`
- **Severidad:** baja
- **Tipo:** c
- **Evidencia:**
  - `configuring-sqlalchemy-sessions/SKILL.md:135,143`: `async def expire_pending_orders() -> int:` ... `return result.rowcount`
  - `layering-fastapi-apps/SKILL.md:254`: "`mypy --strict app` pasa."; `README.md:51`: "código production-ready tipado".
- **Confirmación:** ejecutado. `"Result[Any]" has no attribute "rowcount"` y `Returning Any from function declared to return "int"`. En runtime funciona (rowcount = 1 en PostgreSQL).
- **Impacto:** un worker copiado rompe `mypy app`.
- **Plan de corrección:** `result = cast("CursorResult[Any]", await session.execute(...))`. Verificación: `mypy --strict` sobre el bloque.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-15: la regla dice `joinedload` para muchos-a-uno, y el ejemplo usa `selectinload`
- **Severidad:** baja
- **Tipo:** a
- **Evidencia:**
  - `modeling-postgres-with-sqlalchemy/SKILL.md:24`: "El repositorio decide `selectinload` (colecciones) o `joinedload` (muchos-a-uno)."
  - `modeling-postgres-with-sqlalchemy/SKILL.md:191,209`: `product: Mapped[Product] = relationship(lazy="raise")` (muchos-a-uno) y `.options(selectinload(Order.product))`.
- **Confirmación:** por lectura.
- **Impacto:** el ejemplo enseña lo contrario de la regla y genera una query adicional donde la regla pedía un JOIN.
- **Plan de corrección:** canónico: la regla. L209: `joinedload(Order.product)`. Revisar `sessions:36`, que sugiere `selectinload()` en general, y dejarlo como "carga explícita".
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-16: tres formas de fijar SQLAlchemy, y los tests corren con la versión prohibida
- **Severidad:** baja
- **Tipo:** b, e
- **Evidencia:**
  - `scaffolding-fastapi-backends/SKILL.md:21`: "`sqlalchemy>=2.0,<2.1`"; L73 y L101: `sqlalchemy[asyncio]>=2.0.40,<2.1`.
  - `tracing-with-opentelemetry/SKILL.md:26`: "Fijar `sqlalchemy<2.1`".
  - `DIAGNOSTICO.md:70`: "`sqlalchemy>=2.0.40,<2.1`".
  - `README.md:70` y `tests/snippets/test_python_snippets.py:4`: `--with sqlalchemy`, sin cota.
- **Confirmación:** ejecutado. El comando del README instala `sqlalchemy 2.1.6`; 7 passed, pero sobre una versión que la biblioteca prohíbe. `opentelemetry-instrumentation-sqlalchemy` 0.66b2 sigue declarando `< 2.1.0`, así que el fundamento se sostiene. El piso 2.0.40 funciona en Python 3.14 con estos modelos, así que no hay problema con el piso en sí.
- **Impacto:** un agente puede tomar la forma floja, y el test de `UtcDateTime` no prueba la versión que se publica.
- **Plan de corrección:** canónico: `sqlalchemy[asyncio]>=2.0.40,<2.1` (el de `pyproject`). Usarlo en `scaffolding:21`, `tracing:26`, `README:70`, docstring del test. Verificación: test que recorra las skills y falle si aparece un pin de sqlalchemy distinto.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend (`scaffolding`), observability (`tracing:26`), raíz del repo (`README`, `tests`).

### DB-17: "`ALTER TYPE ... ADD VALUE` no corre en transacción" es falso en el stack declarado
- **Severidad:** baja
- **Tipo:** d
- **Evidencia:**
  - `modeling-postgres-with-sqlalchemy/SKILL.md:57`: "`ALTER TYPE ... ADD VALUE` no corre en transacción y no se puede quitar un valor"
  - `scaffolding-fastapi-backends/SKILL.md:21`: "PostgreSQL 16+".
- **Confirmación:** ejecutado en PostgreSQL 16: `BEGIN; ALTER TYPE tt ADD VALUE 'b'; COMMIT;` funciona, `enum_range` = `{a,b}`.
- **Impacto:** la decisión de no usar ENUM nativo se sostiene (no se puede quitar un valor), pero con un argumento obsoleto, y puede llevar a usar `autocommit_block` sin necesidad.
- **Plan de corrección:** L57: "no se puede quitar un valor, y el valor nuevo no se puede usar en la misma transacción". Sin cambio de decisión.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-18: testing afirma que SQLite no tiene índices parciales ni CHECK reales
- **Severidad:** baja
- **Tipo:** b, d
- **Evidencia:**
  - `testing-fastapi-endpoints/SKILL.md:20`: "para lo que SQLite no tiene (`FOR UPDATE`, índices parciales, JSONB, CHECK reales, tipos)."
  - `modeling-postgres-with-sqlalchemy/SKILL.md:164-167`: `sqlite_where=text("status = 'pending'")` y "un índice ÚNICO parcial se vuelve único total" si no se declara.
- **Confirmación:** ejecutado. SQLite rechaza `CHECK constraint failed` y respeta un `UNIQUE ... WHERE` parcial.
- **Impacto:** un agente puede saltear tests de CHECK en SQLite, o concluir que `sqlite_where` no hace nada, y dejar un parcial convertido en único total en los tests.
- **Plan de corrección:** canónico: `modeling`. `testing:20`: "`FOR UPDATE`, JSONB, tipos estrictos, y la expresión exacta de los índices parciales si no se declara `sqlite_where`".
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** testing.

### DB-19: `render_item` advierte de un `import` que autogenerate no escribe
- **Severidad:** baja
- **Tipo:** d
- **Evidencia:**
  - `migrating-with-alembic/SKILL.md:19`: "sin él, autogenerate escribe `import app.models` en la migración, justo lo que está prohibido."
- **Confirmación:** ejecutado. Sin `render_item` se genera `app.models.base.UtcDateTime(timezone=True)` **sin ningún import**, y `upgrade` falla con `NameError: name 'app' is not defined`.
- **Impacto:** quien tenga ese síntoma no lo reconoce, y puede "arreglarlo" agregando el import prohibido.
- **Plan de corrección:** L19: "sin él, la migración referencia `app.models.base.UtcDateTime` sin importarlo y falla con `NameError`; agregar el import violaría la regla de L46".
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### DB-20: el `description` promete síntomas que el cuerpo no trata
- **Severidad:** baja
- **Tipo:** a
- **Evidencia:**
  - `configuring-sqlalchemy-sessions/SKILL.md:3`: "...or DetachedInstanceError." `grep -rn DetachedInstance skills/`: solo esa línea.
  - `migrating-with-alembic/SKILL.md:3`: "\"Target database is not up to date\"". `grep`: solo esa línea; L23 describe una causa sin nombrar el mensaje.
- **Confirmación:** por lectura (`grep`).
- **Impacto:** la skill se activa con ese error y el agente no encuentra el diagnóstico.
- **Plan de corrección:** agregar una fila al anti-patrón de cada skill. `sessions`: "acceder a un atributo no cargado tras cerrar la sesión | `DetachedInstanceError` | `expire_on_commit=False` + carga explícita antes de cerrar". `alembic`: en L23 citar el mensaje y sumar la otra causa: base con migraciones pendientes.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

---

## Dudosos (no los cuento como hallazgos)

1. **`SET NOT NULL` en tablas grandes** (`migrating:29,43`): la skill lo da como solución, pero escanea con `ACCESS EXCLUSIVE` salvo que exista un CHECK `IS NOT NULL` validado. Es la misma clase de problema que L30 evita. Por lectura y documentación de PostgreSQL; no lo ejecuté. Recomendación: agregar "con un CHECK `NOT VALID` + `VALIDATE` antes".
2. **Engine fijado al importar** (`sessions:73`) contra `layering:50` ("`create_app()` como factory: tests y workers pueden construir apps con otros settings") y `configuring-fastapi-settings:41`. La fila de settings se limita a "módulos de dominio", y `database.py` no lo es, pero `create_app(otros_settings)` no cambia la base.
3. **Workers y funciones sueltas con SQL** (`sessions:135-143`, `modeling:216-243`) contra `layering:24` ("único lugar con select/insert/update/delete") y `:39` ("Repositorios como clases"). El grep del checklist solo mira `app/api` y `app/services`; pueden leerse como ilustración de la técnica.
4. **"Métricas del pool"** (`sessions:37`): ninguna skill de observability las expone (`grep checkedout|engine.pool` vacío). Es una mención al pasar, no una promesa fuerte.
5. **`lifespan`** (`sessions:18,153`, `layering:207`, `tracing:23`): se usa en varias skills y `def lifespan` no aparece en ninguna. No hay contradicción, pero tres skills cuelgan cosas de algo que nadie define.
6. **Sync contra el resto de la biblioteca**: `layering` y `testing` solo cubren `AsyncSession`. Nada promete compatibilidad, pero conviene decirlo en `sessions:17`. Se relaciona con DB-07.
7. **Detalles fuera de mi dominio, sin evaluar a fondo:** `ci.md:8` resume el round-trip sin el `upgrade head` final (el YAML de L106-109 sí lo tiene); `filterwarnings` está en `testing:56` y no en `scaffolding:86-90`; `cimg/postgres:16.4` y `postgres:16-alpine`, contra "misma versión" (`testing:30`); `layering:68` dice "17 tests" y `DIAGNOSTICO.md:84` dice 18.

## Probado y correcto (sin hallazgo)

- Contrato de campos de `Settings` ↔ `build_engine`: todos existen.
- `get_db` / `DbSession` ↔ `dependency_overrides`, `layering`: firmas compatibles. Commit en el service: consistente.
- E2E: `conftest` (con DB-01 corregido) + entidades + `OrderService`: SQLite y PostgreSQL 16 por testcontainers verdes, con `filterwarnings = error::SAWarning` activo, y receta de concurrencia incluida.
- `UtcDateTime`, `eager_defaults`, `render_item`, `compare_type`, `compare_server_default`: `alembic check` limpio, también con `JSON().with_variant(JSONB())` y `Document`. FK hereda `BIGINT` de la PK.
- `naming_convention`: `ck_orders_order_status`, `uq_products_sku`, `fk_orders_product_id_products`, `ix_orders_product_id`, `pk_*`.
- `alembic.ini`: `file_template` y hooks `ruff` tipo `module` funcionan. `upgrade → check → downgrade base → upgrade` funciona con la migración autogenerada.
- `import_products`, `SKIP LOCKED`, `StaleDataError`, `expire_pending_orders` (este último solo en PostgreSQL): funcionan.
- Exclusión `/health/.*` en OTel: excluye `/api/v1/health/live`. `testcontainers.community.postgres` existe en 4.15.0.
- `docker.md` y `ci.md`: paso `migrate` previo y bloqueante, entorno suficiente para `get_settings()` en el job `migrations`: coinciden con `migrating:32-33` (por lectura; no levanté ese compose ni CircleCI).

## No verificado

- **PostgreSQL 17**, que las etiquetas citan: corrí todo en 16, la versión del stack.
- **`lock_timeout` perdido bajo carga real** a través de PgBouncer (DB-04): demostré el mecanismo, no una migración concreta sin timeout.
- **`application_name` solo por `server_settings` detrás de PgBouncer**: el error de DB-06 lo da `statement_timeout`; no lo aislé.
- **PgBouncer real anterior a 1.21**: lo emulé con `max_prepared_statements = 0`.
- **Los snippets `/health/ready` y el `SessionFactory` síncronos literales**: probé el engine psycopg y las opciones de conexión, no el endpoint.
- **Exclusión `/health/.*` en `prometheus-fastapi-instrumentator`**: vi que compila regex pero no hice una corrida contra una app.
- **`mypy` con el plugin `pydantic.mypy`** de scaffolding: corrí `mypy --strict` sin él. Eso produce errores `_env_file` en `config.py` que no atribuyo a la skill; queda para backend.
- **Compose completo, CircleCI**: por lectura.
