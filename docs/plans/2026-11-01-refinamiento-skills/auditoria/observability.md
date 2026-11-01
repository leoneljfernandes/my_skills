# Auditoría de la rama OBSERVABILITY

**Fecha:** 2026-11-01. **Base:** commit `54d8c96`, árbol limpio. No se modificó nada en `/home/leonel/my_skills`.

## Abreviaturas de archivo

| Abreviatura | Archivo |
|---|---|
| MET | `skills/observability/exposing-prometheus-metrics/SKILL.md` |
| LOG | `skills/observability/logging-json-to-loki/SKILL.md` |
| TRC | `skills/observability/tracing-with-opentelemetry/SKILL.md` |
| SLO | `skills/observability/defining-grafana-slos/SKILL.md` |
| STACK | `skills/observability/defining-grafana-slos/references/stack.md` |
| DASH | `skills/observability/defining-grafana-slos/templates/build_dashboard.py` |
| DOCKER | `skills/backend/scaffolding-fastapi-backends/references/docker.md` |
| SCAF | `skills/backend/scaffolding-fastapi-backends/SKILL.md` |
| LAYER | `skills/backend/layering-fastapi-apps/SKILL.md` |
| ERR | `skills/backend/handling-fastapi-errors/SKILL.md` |
| DB | `skills/database/configuring-sqlalchemy-sessions/SKILL.md` |
| TEST | `skills/testing/testing-fastapi-endpoints/SKILL.md` |

## Cómo se verificó

Todo se ejecutó en `/tmp/claude-1000/-home-leonel-my-skills/927a91bb-bc0d-4938-a40b-4a8225428464/scratchpad/audit/observability/`, con código extraído de las skills mediante `tests/snippets/extract.py`:

- `app_ref/`: app armada con los bloques publicados de `Settings`, `errors.py`, `logging.py`, `metrics.py`, `tracing.py`, `database.py` y `create_app()`. Modelos, router y `lifespan` son míos porque hacen falta para correr. Versiones resueltas: Python 3.14, sqlalchemy 2.0.55, prometheus-fastapi-instrumentator 8.1.0, prometheus-client 0.26.0, opentelemetry-sdk 1.45.2, instrumentaciones 0.66b2, uvicorn 0.54.0, gunicorn 26.2.0.
- `mon/monitoring/`: configs extraídas de SLO y STACK. Los comentarios `… idem` de las reglas se expandieron literalmente.
- Herramientas, con los tags publicados: `promtool` (Prometheus v3.15.1), `amtool` y Alertmanager v0.34.1, `alloy validate` v1.21.2, `loki -verify-config` 3.7.9. Prometheus, Tempo 3.1.1 y Loki corrieron juntos en una red temporal. Todos los contenedores, la red y los dos volúmenes anónimos que dejaron se eliminaron.

## Resultado por severidad

- **Alta:** 2 (OB-01, OB-02)
- **Media:** 12 (OB-03 a OB-14)
- **Baja:** 11 (OB-15 a OB-25)
- **Dudosos:** 8 (sección final)

---

## Hallazgos de severidad alta

### OB-01: las reglas SLI pierden el label `job`: la inhibición no funciona y dos servicios colisionan

- **Severidad:** alta
- **Tipo:** c, e
- **Evidencia:**
  - SLO:67-68: `sum(rate(http_requests_total{job="orders-api",status="5xx"}[5m]))` / `/ clamp_min(sum(rate(http_requests_total{job="orders-api"}[5m])), 1e-9)`. El `sum` sin `by` descarta `job`.
  - SLO:147: `- exp_labels: {severity: page, slo: availability}`. El test publicado confirma que la alerta no lleva `job`.
  - SLO:189-192: `# Si la API está caída, no sumar páginas de burn-rate/latencia del mismo job.` y `equal: [job]`.
  - SLO:21: `Por servicio, 2 SLOs como mínimo`, y STACK:11: `rules/<servicio>-slo.yml`. La plantilla invita a tener un archivo por servicio con los mismos nombres de `record`.
  - SLO:176: `group_by: [alertname, job, slo]`. El `job` no agrupa nada en las alertas de burn rate.
- **Confirmación:** ejecutado.
  - Alertmanager v0.34.1 con el `alertmanager.yml` publicado, enviando tres alertas por la API v2. `OrdersApiDown` con `job=orders-api` quedó `active`. `OrdersApiErrorBudgetFastBurn` sin `job`, con los labels reales de la regla, quedó `active` con `inhibitedBy: []`. El control `BurnConJob` con `job=orders-api` quedó `suppressed`. La inhibición sirve solo si hay `job`.
  - `promtool test rules` con `orders-api-slo.yml` más una copia para `payments-api`: `rule: sli:http_error_ratio:rate5m, time: 30s, err: duplicate sample for timestamp 30000; overrides not allowed: existing 0, new value 0.5`. Igual en rate30m, rate1h y rate6h.
- **Impacto:** el on-call recibe la página de burn rate aunque la API esté caída, contra lo que dice SLO:35. Con un segundo servicio, las series `sli:*` chocan y las alertas de uno leen el ratio del otro.
- **Plan de corrección:** canónico `sum by (job)`, porque es lo único que sostiene `equal: [job]` y "por servicio".
  - SLO:65-76: `sum by (job) (...)` en numerador y denominador de todas las reglas.
  - SLO:83-85 y 97-99: filtrar con `sli:http_error_ratio:rate1h{job="orders-api"}`.
  - SLO:147: `exp_labels: {job: orders-api, severity: page, slo: availability}`.
  - DASH:125-126: `sli:http_error_ratio:rate1h{{{SEL}}}` y lo mismo para rate6h.
  - **Verificación:** ya probé en `mon/fix/` la variante `sum by (job)` con dos servicios: `promtool test rules` da SUCCESS, sin colisión, y solo `PaymentsApi…` dispara. Sumar al test publicado un caso de dos servicios y otro de inhibición.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### OB-02: "traza → Logs for this span" no encuentra nada: `service.name` es `orders-api` y el label de Loki es `backend`

- **Severidad:** alta. Es criterio de aceptación del paso 8 de SCAF y no se puede cumplir.
- **Tipo:** b, c
- **Evidencia:**
  - STACK:244-248: `tracesToLogsV2:` con `datasourceUid: loki`, `filterByTraceID: true`, sin `tags` ni `customQuery`.
  - TRC:70: `"service.name": settings.APP_NAME,`, y `configuring-fastapi-settings/SKILL.md:80`: `APP_NAME: str = "orders-api"`.
  - LOG:118-119: `source_labels = ["__meta_docker_container_label_com_docker_compose_service"]` / `target_label  = "service"`, y DASH:12: `LOG_SERVICE = "backend"       # = label service que Alloy toma del servicio de docker-compose`.
  - LOG:105 (JSON): `"service": "orders-api"`, y LOG:166 (label): `{service="backend", level="error"}`. El mismo nombre tiene dos valores.
  - Promesas: SLO:221: `traza → *Logs for this span* abre Loki`; STACK:289: `en la traza, *Logs for this span* vuelve a Loki`; SCAF:41: `un log abre su traza, la traza abre sus logs`.
- **Confirmación:** ejecutado en dos partes, sin clic en la UI de Grafana.
  - Bundle de Grafana 13.2.4 (`public/build/3489.*.js`): `Ys=Zs(["cluster","hostname","namespace","pod","service.name","service.namespace"])`, con `t.replace(".","_")` y `S=n.tags&&n.tags.length>0?n.tags:Ys`. Sin `tags`, el selector resulta `{service_name="orders-api"}`.
  - Loki 3.7.9 con el `loki.yml` publicado, empujando una línea con los labels que produce la config de Alloy (`service=backend`, `container`, `level`; push directo a la API, sin Alloy). `{service_name="orders-api"} |="<trace>"` da 0 streams, `{service="orders-api"} |="<trace>"` da 0 streams, y `{service="backend"} | trace_id="<trace>"` da 1 stream. Loki autogenera `service_name=backend`.
  - `| json` deja `service: backend` y `service_extracted: orders-api`.
- **Impacto:** el salto traza → logs abre una consulta vacía. El agente no puede dar por terminado el paso 8 y el síntoma parece "no hay logs".
- **Plan de corrección:** canónico el filtro por `trace_id` como structured metadata, que ya funciona y no depende de nombres.
  - STACK:244-248: agregar `customQuery: true` y `query: '{service=~".+"} | trace_id="${__span.traceId}"'`.
  - LOG (junto a la línea 21): aclarar que el campo JSON `service` es `APP_NAME` y el label `service` es el nombre en compose.
  - **Verificación:** provisionar en Grafana y comprobar el enlace. La sintaxis de la variable no la probé en la UI.
- **Decisión requerida:** ¿mantener dos nombres (`backend`, `orders-api`) o unificarlos? Opciones:
  - (a) `customQuery` como arriba, sin tocar nombres.
  - (b) Unificar: que el label `service` salga del JSON o renombrar el servicio de compose. Esto permite eliminar `LOG_SERVICE`, pero toca DOCKER y LOG:166-169.
  - **Recomiendo (a):** es mínimo, sirve para varios servicios y no parte streams con las líneas no JSON.
- **Otros dominios afectados:** backend solo si se elige (b): el nombre del servicio en DOCKER:186.

---

## Hallazgos de severidad media

### OB-03: sin ningún 5xx, los SLI de error, el burn rate y la disponibilidad quedan sin datos

- **Severidad:** media
- **Tipo:** a, d
- **Evidencia:**
  - SLO:67: `sum(rate(http_requests_total{job="orders-api",status="5xx"}[5m]))`. El Instrumentator crea cada `status` recién al observarlo.
  - DASH:113-114 (`ratio_30d`) y DASH:125-126 (burn rate) dependen de esa serie.
  - SLO:221: `el panel de burn rate muestra datos`. STACK:289: `el dashboard muestra tráfico, latencia y burn rate`.
- **Confirmación:** ejecutado. `promtool test rules` solo con series `status="2xx"`: `sli:http_error_ratio:rate5m` y la expresión de "Disponibilidad 30d" pasan con `exp_samples: []`, es decir, vector vacío.
- **Impacto:** un servicio sano muestra "No data" en disponibilidad, presupuesto y burn rate, justo cuando debería mostrar 100 %. El checklist falla hasta el primer error.
- **Plan de corrección:** en SLO:67 y sus variantes:
  ```promql
  (sum by (job) (rate(http_requests_total{job="orders-api",status="5xx"}[5m]))
    or 0 * sum by (job) (rate(http_requests_total{job="orders-api"}[5m])))
  / clamp_min(sum by (job) (rate(http_requests_total{job="orders-api"}[5m])), 1e-9)
  ```
  Igual en `ratio_30d` (DASH:113-114) y en "Errores 5xx" (DASH:53). Verificación ya hecha en `mon/fix/`: con solo 2xx da 0 con label `job`. Agregar ese caso al test publicado.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### OB-04: retención de Prometheus de 15 días con un SLO y paneles de 30 días

- **Severidad:** media
- **Tipo:** e
- **Evidencia:**
  - STACK:36: `- --storage.tsdb.retention.time=15d`.
  - SLO:58: `# SLOs de orders-api (ventana 30 días):`.
  - DASH:110: `SLO_TARGET = 0.999  # disponibilidad 30 días`, DASH:112: `row("SLO disponibilidad (30 días)", 74)`, DASH:113: `increase(...[30d])`, DASH:115: `"Disponibilidad 30d"`.
- **Confirmación:** por lectura.
- **Impacto:** "Disponibilidad 30d" y "Presupuesto restante" calculan sobre 15 días como máximo, sin avisar. El presupuesto mensual informado es falso.
- **Plan de corrección:** canónico el SLO. STACK:36 a `--storage.tsdb.retention.time=35d`, con un comentario "≥ ventana del SLO". Agregar a SLO:214-222 un ítem del checklist: retención ≥ ventana.
- **Decisión requerida:** ¿35 días de TSDB local o dejar 15 y renombrar los paneles? Recomiendo 35: es lo que promete la skill.
- **Otros dominios afectados:** ninguno.

### OB-05: el salto Prometheus → Tempo por exemplars no puede funcionar

- **Severidad:** media
- **Tipo:** b, d
- **Evidencia:**
  - SLO:38: `Prometheus → Tempo (exemplars)`.
  - STACK:38: `--enable-feature=exemplar-storage      # exemplars → salto de métrica a traza`.
  - STACK:222-224: `exemplarTraceIdDestinations:` / `- name: trace_id` / `datasourceUid: tempo`.
  - MET no menciona exemplars. El código de MET:62-66 no los genera.
- **Confirmación:** ejecutado.
  - Prometheus + Tempo con los archivos publicados: `/api/v1/query_exemplars` devuelve `{'traceID': 'd12bcc66…'}`. La etiqueta es `traceID`, no `trace_id`.
  - Grep sobre el paquete del Instrumentator: 0 de 5 archivos mencionan exemplars. `/metrics` con `Accept: application/openmetrics-text` responde `text/plain; version=1.0.0`.
  - No probé el enlace en la UI.
- **Impacto:** la correlación prometida no aparece, ni en las métricas de la app ni en las del metrics-generator.
- **Plan de corrección:** STACK:223 a `name: traceID`, para las métricas de Tempo. En SLO:38 y STACK:38 aclarar que los exemplars salen de `traces_spanmetrics_*` y `traces_service_graph_*`, no de `http_*`. Verificación: abrir un panel de `traces_spanmetrics_latency_bucket` en Grafana y comprobar el enlace.
- **Decisión requerida:** ¿se quieren exemplars también en `http_*`? Requeriría métrica propia y exposición OpenMetrics. Recomiendo no hacerlo: alcanza con spanmetrics.
- **Otros dominios afectados:** ninguno.

### OB-06: con el Instrumentator publicado, `http_request_duration_seconds` tiene solo 3 buckets y los percentiles saturan en 1 s

- **Severidad:** media
- **Tipo:** a, e
- **Evidencia:**
  - MET:23: `Histogramas con buckets alrededor de los umbrales del SLO`. MET:129: `Los buckets de latencia incluyen el umbral del SLO`. MET:35: `p95/p99 con histogram_quantile`.
  - MET:62-66: el `Instrumentator(...)` no fija buckets y no hay instrucción de cómo hacerlo.
  - DASH:73-79 usa esa métrica para p50/p95/p99 y p95 por endpoint.
  - MET:3: la description promete resolver `latency percentiles look wrong`.
- **Confirmación:** ejecutado.
  - `/metrics` real: `le="0.1"`, `"0.5"`, `"1.0"`, `"+Inf"`. `inspect.signature(metrics.default)`: `latency_lowr_buckets: (0.1, 0.5, 1)`.
  - `promtool` con todas las requests por encima de 1 s: `histogram_quantile(0.99, …)` da exactamente `1`.
- **Impacto:**
  - Un servicio con latencia de 5 s muestra p99 = 1 s.
  - Un SLO distinto de 100/500/1000 ms no tiene bucket y `le="0.3"` no devuelve nada.
  - El agente no aprende de la skill cómo cumplir la regla.
- **Plan de corrección:** en MET:62-66 mostrar `.add(metrics.default(latency_lowr_buckets=(...)))`. Probé esa forma con un bucket `0.3` y aparece en `/metrics`. Documentar que `http_request_duration_highr_seconds` tiene 21 buckets sin `handler`, y cambiar los percentiles globales de DASH:59 y DASH:74-77 a esa métrica.
- **Decisión requerida:** ¿buckets propios para todo, o mantener `lowr` para SLO y por endpoint, y `highr` para percentiles globales? Recomiendo lo segundo: más buckets por `handler` choca con la regla de cardinalidad de MET:22.
- **Otros dominios afectados:** ninguno.

### OB-07: el SLO de latencia no tiene alertas ni panel, y la fila `ticket` 3d no está implementada

- **Severidad:** media
- **Tipo:** a, e
- **Evidencia:**
  - SLO:23: `Latencia: % de requests bajo un umbral`. SLO:60: `Latencia: 99 % de requests en < 500 ms → presupuesto 1 %`.
  - SLO:70-76: reglas `sli:http_latency_slow_ratio:*`, solo 5m y 1h, y ninguna alerta las usa en SLO:78-124.
  - SLO:31: `| ticket | 1 | 3d | 6h | 10 % en 3 d |`, frente a SLO:24: `para cada ventana que usen las alertas (5m, 30m, 1h, 6h)`. No existe rate3d ni alerta `ticket` de burn rate.
  - SLO:189: `no sumar páginas de burn-rate/latencia`: refiere a una alerta que no existe.
  - DASH:112: solo `SLO disponibilidad`. SLO:37 no diferencia.
  - Además, las reglas publicadas usan `# … idem` (SLO:69, SLO:76): el bloque no se puede ejecutar tal cual.
- **Confirmación:** ejecutado. `promtool check rules` sobre el archivo expandido: `10 rules found` (6 de SLI y 4 alertas), ninguna de latencia. La lectura de alertas se hizo sobre el mismo archivo.
- **Impacto:** un agente que copia el ejemplo publica un SLO de latencia sin vigilancia y sin la tercera ventana de la tabla, y cree que cumplió.
- **Plan de corrección:** canónica la tabla. En SLO:61-125 agregar las alertas de latencia y `rate3d` con su `ticket`, y escribir las reglas completas sin `… idem` para que el bloque sea extraíble. En DASH agregar una fila "SLO latencia". Tests: un caso que dispara y uno que no, por cada alerta nueva.
- **Decisión requerida:** ¿ejemplo completo, unas 40 líneas más, o aclarar que es parcial? Recomiendo completo, porque el test de snippets exige bloques ejecutables.
- **Otros dominios afectados:** ninguno.

### OB-08: `sli:http_latency_slow_ratio` vale 1 (100 % lento) con cero tráfico

- **Severidad:** media
- **Tipo:** a
- **Evidencia:**
  - SLO:72-75: `1 - (` … `/ clamp_min(sum(rate(http_request_duration_seconds_count{job="orders-api"}[5m])), 1e-9)` `)`.
  - SLO:51: `expresiones que nunca disparan (o siempre)`.
- **Confirmación:** ejecutado. `promtool` con counters quietos: `sli:http_latency_slow_ratio:rate5m` da `1`, y `sli:http_error_ratio:rate5m` da `0` con la misma técnica.
- **Impacto:** si se agrega la alerta de latencia que falta (OB-07), pagina cada noche o en cualquier período sin tráfico.
- **Plan de corrección:** reescribir como `(count - bucket) / clamp_min(count, 1e-9)` con `sum by (job)`. Verificación ya hecha en `mon/fix/`: da 0 en reposo. Agregar ese caso al test publicado.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### OB-09: el test de TRC usa `ProductFactory`, que ninguna skill define

- **Severidad:** media
- **Tipo:** b, c
- **Evidencia:**
  - TRC:148: `product = await ProductFactory.create_async(stock=5)`.
  - TEST:25: `helpers async en tests/factories.py (create_product(session, **overrides))`. TEST:174: `async def create_product(session: AsyncSession, **overrides: object) -> Product:`. TEST:193: `product = await create_product(db_session, stock=5, price=Decimal("12.50"))`.
  - TEST:26 reserva `polyfactory` para modelos con más de 10 columnas obligatorias. `grep ProductFactory` en todo `skills/`: un único resultado, TRC:148.
- **Confirmación:** ejecutado con el `conftest` de TEST, corrigiendo solo su `SyntaxError` (ver notas al final). Tal cual: `NameError: name 'ProductFactory' is not defined`. Con `create_product(db_session, stock=5)` y `db_session` en la firma, el test pasa: span manual, SQL hijos y mismo `trace_id`.
- **Impacto:** el test que "impide que la instrumentación falle en silencio" no corre al combinarlo con la skill de testing.
- **Plan de corrección:** canónico TEST. En TRC:145-148: `client: AsyncClient, db_session: AsyncSession, spans: InMemorySpanExporter` y `await create_product(db_session, stock=5)`. Agregar un test en `tests/snippets/` que ejecute el bloque.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** testing: ninguno, su helper es la referencia.

### OB-10: `lifespan` no está definido en ninguna skill, y tres reglas dependen de él

- **Severidad:** media
- **Tipo:** c, e
- **Evidencia:**
  - LAYER:207: `title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan,`. LAYER:17: `create_app(): middlewares, handlers, routers, lifespan`.
  - TRC:23: `provider.shutdown() en el lifespan`. TRC:40: `shutdown_tracing() en el lifespan`.
  - DB:18: `await engine.dispose() en el lifespan al apagar`. DB:153: `lifespan llama a engine.dispose() al apagar`.
  - `grep -rn "def lifespan" skills` da 0. `shutdown_tracing` solo aparece en TRC.
- **Confirmación:** ejecutado el grep. El harness debió escribir su propio `lifespan` (con `shutdown_tracing()` antes de `engine.dispose()`, orden inverso al que propongo abajo). Con él, uvicorn apaga limpio. Que `create_app()` da `NameError` es por lectura.
- **Impacto:** `create_app()` tal como se publica da `NameError`. Cada agente improvisa el `lifespan` y es fácil omitir el flush de spans, que TRC:40 define como anti-patrón.
- **Plan de corrección:** canónico LAYER, dueño de `main.py`. Agregar al bloque de LAYER:202:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI) -> AsyncIterator[None]:
      yield
      await engine.dispose()
      shutdown_tracing()  # flush de spans en buffer, al final
  ```
  con los imports completos. En TRC:23 y DB:18 referir a ese bloque. Test: extraer `create_app` y comprobar que `shutdown_tracing` se llama al salir del lifespan.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend (LAYER:200-223), database (DB:18, referencia).

### OB-11: `tracing.py` no sirve en "modo mínimo", y `main.py`/errores no son compatibles con el orden de SCAF ni con el camino Vercel

- **Severidad:** media
- **Tipo:** a, c, e
- **Evidencia:**
  - TRC:17: `alcanza con opentelemetry-api y la función current_trace_id() de abajo`, y `errors.py y el formateador de logs funcionan igual`.
  - TRC:51-57: el bloque importa `opentelemetry.exporter...`, `opentelemetry.sdk...` y las instrumentaciones a nivel de módulo.
  - ERR:66 y LOG:58: `from app.observability.tracing import current_trace_id…`.
  - SCAF:35: paso 2 `uv run uvicorn app.main:app arranca`. SCAF:30: `Cada paso termina en verde antes del siguiente`. SCAF:41: la observabilidad es el paso 8. SCAF:101: `uv add` no incluye OTel ni Prometheus, aunque SCAF:75-77 sí en `pyproject.toml`.
  - LAYER:205, 216-217: `configure_logging`, `setup_metrics` y `setup_tracing(app, engine, settings)` incondicionales. MET:15: `Solo si el despliegue tiene contenedores propios`. SCAF:41 para Vercel: solo `logging-json-to-loki` y `vercel-index`.
- **Confirmación:** ejecutado.
  - Con solo `opentelemetry-api` e `import app.observability.tracing`: `ModuleNotFoundError: No module named 'opentelemetry.exporter'`.
  - Con los paquetes de SCAF:101 e `import app.errors`: el mismo error.
- **Impacto:**
  - El modo mínimo no existe como archivo: el agente debe inventarlo.
  - El paso 2 no llega a verde con el bootstrap.
  - En Vercel, LOG (obligatorio) importa una skill que no está en la lista, y `create_app` llama a funciones que ese camino no crea.
- **Plan de corrección:**
  - TRC:49-58: mover los imports de SDK e instrumentaciones **dentro** de `setup_tracing`. Con eso `current_trace_id()` funciona solo con la API y no cambia ninguna ruta.
  - SCAF:101: agregar `opentelemetry-api`. SCAF:41: incluir el modo mínimo de TRC en el camino Vercel.
  - LAYER:216-217: indicar cómo omitir `setup_metrics`/`setup_tracing` o agregarlos en el paso 8.
  - Test: importar el bloque con solo `opentelemetry-api` en el entorno y comprobar que `current_trace_id()` devuelve `None`.
- **Decisión requerida:** ¿cómo se apaga `/metrics` sin contenedores propios? (a) flag `METRICS_ENABLED` en `Settings`, hoy inexistente; (b) no llamar `setup_metrics`, y los services no importan `metrics.py`. Recomiendo (a), con import diferido de `prometheus_fastapi_instrumentator`: sigue el modelo de `OTEL_EXPORTER_OTLP_ENDPOINT` y mantiene igual el código de los services.
- **Otros dominios afectados:** backend: SCAF:41, SCAF:101, LAYER:216-217, y `configuring-fastapi-settings` si se elige (a).

### OB-12: el ejemplo multiproceso no arranca sin crear el directorio y usa un worker deprecado; además deja vacíos los paneles de recursos

- **Severidad:** media
- **Tipo:** a, c
- **Evidencia:**
  - MET:121: `PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4`. MET:25: `apuntando a un directorio vacío en cada arranque`. MET:113: `El directorio se vacía en cada deploy (p. ej. emptyDir / tmpfs)`.
  - SCAF:70-78: `gunicorn` no está en las dependencias.
  - DASH:83-85: `process_cpu_seconds_total`, `process_resident_memory_bytes`, `process_open_fds`.
  - `DIAGNOSTICO.md:169` ya declara `gunicorn.conf.py` como no compilado, y aun así la skill lo presenta como receta.
- **Confirmación:** ejecutado, gunicorn 26.2.0 y uvicorn 0.54.0.
  - Sin el directorio: `FileNotFoundError: … mp2/counter_90464.db` al importar la app.
  - `import uvicorn.workers`: `The uvicorn.workers module is deprecated. Please use uvicorn-worker package instead.`
  - Con directorio y 2 workers: 8 requests suman `8.0`, correcto. `/metrics` no tiene ninguna serie `process_*`.
- **Impacto:** el comando copiado falla al arrancar. Con directorio, el dashboard queda con tres paneles vacíos sin explicación. Nada indica vaciar el directorio en cada arranque.
- **Plan de corrección:** MET:121: `rm -rf "$D" && mkdir -p "$D"` en el entrypoint, y `-k uvicorn_worker.UvicornWorker` con `gunicorn` y `uvicorn-worker` como dependencias condicionales. Agregar una nota de que `process_*` no existe en multiproceso, en MET:25 y en DASH:82. Verificación: el test de checklist MET:131 con 2 workers en `tests/snippets/` o en un script.
- **Decisión requerida:** ¿mantener gunicorn o recomendar `uvicorn --workers`? Sin `child_exit` en este último, `mark_process_dead` no corre. Recomiendo gunicorn + `uvicorn-worker`.
- **Otros dominios afectados:** backend: SCAF:70-78, si se documenta como dependencia condicional.

### OB-13: `HTTPXClientInstrumentor` aparece en la regla y la description, pero no en el código ni en las dependencias

- **Severidad:** media
- **Tipo:** a
- **Evidencia:**
  - TRC:3: `auto-instrumenting FastAPI/SQLAlchemy/httpx`. TRC:25: `y HTTPXClientInstrumentor para llamadas salientes (propaga traceparent)`. TRC:11: `cada llamada saliente`.
  - TRC:49-89: `setup_tracing` no lo importa ni lo llama.
  - SCAF:76-77: `"opentelemetry-instrumentation-fastapi", "opentelemetry-instrumentation-sqlalchemy",`, sin httpx.
- **Confirmación:** por lectura. El paquete `opentelemetry-instrumentation-httpx` se instala e importa en Python 3.14 (ejecutado).
- **Impacto:** al copiar el ejemplo, las llamadas salientes no generan spans ni propagan `traceparent`: la traza se corta entre servicios sin ningún error.
- **Plan de corrección:** canónica la regla. En TRC:89 agregar `HTTPXClientInstrumentor().instrument(tracer_provider=_provider)` con su import. SCAF:77: agregar `opentelemetry-instrumentation-httpx` con el comentario "si hay llamadas salientes". Test: span CLIENT con `traceparent` en una request contra `httpx.MockTransport`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend (SCAF:75-77).

### OB-14: el comando publicado `promtool check config` no valida las reglas

- **Severidad:** media
- **Tipo:** d
- **Evidencia:**
  - STACK:107: `- /etc/prometheus/rules/*.yml`.
  - SLO:209 y STACK:283: `-v "$PWD/monitoring/prometheus:/p:ro,z" … check config /p/prometheus.yml`. El mount en `/p` hace que el glob absoluto no encuentre nada.
  - SLO:55: `verificado: promtool check rules`, pero `check rules` no aparece en los comandos de SLO:207-212 ni de STACK:280-287.
  - SLO:217: `promtool check config … pasan en CI`.
- **Confirmación:** ejecutado. Con `rules/broken.yml` inválido, el comando publicado da `SUCCESS` con rc=0, sin leer ningún rule file. Montando en `/etc/prometheus`: `FAILED … unclosed left parenthesis`, rc=1. Con las reglas buenas: `10 rules found`, rc=0.
- **Impacto:** el CI da verde con reglas rotas. Prometheus falla recién al arrancar, justo lo que el texto de SLO:36 quiere evitar. `test rules` solo cubre los archivos que el test nombra.
- **Plan de corrección:** en SLO:209 y STACK:283, `-v "$PWD/monitoring/prometheus:/etc/prometheus:ro,z" --entrypoint promtool prom/prometheus:v3.15.1 check config /etc/prometheus/prometheus.yml`. La verificación es la prueba de arriba.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

---

## Hallazgos de severidad baja

### OB-15: "solo líneas JSON válidas" es falso con el compose de DOCKER y con gunicorn

- **Severidad:** baja
- **Tipo:** b
- **Evidencia:**
  - LOG:175: `docker compose logs backend … muestra solo líneas JSON válidas, incluidas las de uvicorn`. LOG:25: `todo sale en JSON`.
  - DOCKER:200: `"--reload"`. MET:121: gunicorn.
- **Confirmación:** ejecutado.
  - Con `--reload`: `INFO:     Will watch for changes…`, `INFO:     Started reloader process…`, `INFO:     Stopping reloader process…` en texto plano.
  - Con gunicorn: `[INFO] Starting gunicorn 26.2.0`, y varias más.
- **Impacto:** el checklist no se puede cumplir en desarrollo.
- **Plan de corrección:** LOG:175: "salvo las del proceso supervisor (reloader de uvicorn, master de gunicorn), que corren antes de `create_app()`". El proceso de la app no cambia.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### OB-16: la prueba de punta a punta de STACK usa `/docs`, que no genera ningún log con `trace_id`

- **Severidad:** baja
- **Tipo:** a, c
- **Evidencia:**
  - STACK:289: `generar tráfico (/docs) → … Loki {service="backend"} → abrir un log → *Ver traza*`.
  - LOG:25 y LOG:99: `El access log se baja a WARNING`.
  - LAYER:208: `docs_url=None if settings.is_prod else "/docs"`.
- **Confirmación:** ejecutado. Tres `GET /docs` con OTel activo responden 200, y hay 0 líneas con `docs` o `trace_id` en stdout.
- **Impacto:** el verificador no encuentra ningún log con enlace a traza y concluye que la correlación está rota.
- **Plan de corrección:** STACK:289: generar tráfico con `POST /api/v1/orders` o un 404 de dominio, que sí loguean (`order placed`, `domain error`).
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### OB-17: la lista de labels de Loki de la regla no coincide con la config de Alloy

- **Severidad:** baja
- **Tipo:** a
- **Evidencia:**
  - LOG:30: `Labels de Loki solo de baja cardinalidad (service, level, env)`.
  - LOG:138-143: `stage.json` no extrae `env`, y `stage.labels` solo define `level`.
  - LOG:122-124: el relabel agrega `container`, no mencionado en la regla.
- **Confirmación:** ejecutado parcialmente, con push directo a Loki usando los labels que define la config. `/labels` da `["container","level","service","service_name"]`, y `{env="test"}` da 0 streams. Que Alloy no extrae `env` es por lectura.
- **Impacto:** un agente escribe `{env="prod"}` y no obtiene nada, o agrega `env` en un lugar y lo omite en otro.
- **Plan de corrección:** LOG:30: `(service, level, container; env queda en el JSON y se filtra con | json)`.
- **Decisión requerida:** ¿`env` como label o no? Recomiendo no: con un stack por entorno tiene un único valor. Si un mismo Loki recibe varios entornos, agregarlo a `stage.json` y `stage.labels`.
- **Otros dominios afectados:** ninguno.

### OB-18: consultas que no filtran por `job`, contra la decisión de MET:26

- **Severidad:** baja
- **Tipo:** e
- **Evidencia:**
  - MET:26: `Las reglas SLO y los dashboards filtran por job`.
  - DASH:83-85: `rate(process_cpu_seconds_total[1m])`, `process_resident_memory_bytes`, `process_open_fds`.
  - MET:106-107: `sum(rate(shop_orders_created_total[5m])) * 60`, y SLO:17: `sum(rate(http_requests_total[1h]))`. Frente a SLO:118, que sí filtra.
- **Confirmación:** ejecutado: `build_dashboard.py` genera esas tres queries tal cual.
- **Impacto:** al sumar un segundo job (o Tempo o Alloy con métricas), los paneles mezclan procesos.
- **Plan de corrección:** agregar `{{{SEL}}}` en DASH:83-85 y `{job="orders-api"}` en MET:106-107 y SLO:17.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### OB-19: el dashboard no sigue el orden declarado, y el script falla en un proyecto limpio

- **Severidad:** baja
- **Tipo:** a
- **Evidencia:**
  - SLO:37: `Resumen → Tráfico/errores → Latencia → SLO … → Recursos → Logs → Trazas`.
  - DASH (filas generadas): Resumen y=0, Tráfico y=5, Latencia y=14, Recursos y=23, Logs y=31, Trazas y=55, SLO y=74.
  - SLO:205: `ajustar SERVICE/JOB/LOG_SERVICE/SLO_TARGET`, contra DASH:3: `ajustar SERVICE / JOB / LOG_SERVICE / TITLE`.
  - DASH:140-141: escribe sin crear el directorio.
- **Confirmación:** ejecutado. Sin el directorio: `FileNotFoundError: … grafana/dashboards/orders-api.json`. Con él: 26 paneles, 7 filas, en el orden indicado. El conteo de `DIAGNOSTICO.md:92` es correcto.
- **Impacto:** el SLO queda al final del dashboard, y la primera corrida en un proyecto nuevo falla.
- **Plan de corrección:** canónico SLO:37: mover el bloque SLO y recalcular `y` (idealmente con un contador de filas). DASH:140: `out.parent.mkdir(parents=True, exist_ok=True)`. Unificar la lista en DASH:3 y SLO:205.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### OB-20: "verificado" con test en `tests/snippets/` no se cumple en observabilidad

- **Severidad:** baja
- **Tipo:** d
- **Evidencia:**
  - `README.md:66`: `Un bloque que el texto marca como **verificado** tiene su test en tests/snippets/`.
  - Marcados como verificados: MET:43, LOG:48, LOG:108, TRC:46, SLO:55, SLO:168, STACK:3.
  - `tests/snippets/*.py` no referencia ninguna skill de observabilidad (grep: 0 coincidencias).
  - `DIAGNOSTICO.md:170`: los proyectos de referencia viven fuera del repo.
- **Confirmación:** ejecutado el grep, y la suite publicada corre: 7 passed. Ninguno ejecuta un bloque de observabilidad; el único contacto es el test de contrato de `Settings`, que busca `settings.X` en el texto de todas las skills.
- **Impacto:** las verificaciones publicadas no se pueden repetir. OB-01, OB-03, OB-08 y OB-09 sobrevivieron a esa declaración.
- **Plan de corrección:** agregar `tests/snippets/test_observability_snippets.py` con lo que usé en esta auditoría: extraer los bloques, armar la app, comprobar series, spans y logs. Para reglas y Alertmanager, un script opcional con Docker. Es imprescindible quitar los `… idem` (OB-07).
- **Decisión requerida:** ¿cumplir la regla o reformularla? Recomiendo cumplirla para el código Python, y dejar para reglas y configs un marcador `verificado con herramienta` sin exigir test en pytest.
- **Otros dominios afectados:** probablemente todos: el orquestador puede cruzarlo con los otros informes.

### OB-21: comentario de DOCKER contradice cómo consulta Loki

- **Severidad:** baja
- **Tipo:** b
- **Evidencia:**
  - DOCKER:188: `container_name: backend_app       # nombre fijo: las queries de Loki lo usan`.
  - LOG:166-169 y DASH:12, 90-96: todas las queries usan `{service="backend"}`. LOG:118 lo toma del servicio de compose.
- **Confirmación:** por lectura.
- **Impacto:** un agente puede creer que debe conservar ese nombre, o filtrar por `container`.
- **Plan de corrección:** DOCKER:188: quitar el comentario, o aclarar que las queries usan el nombre del servicio (`backend`).
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend (DOCKER:188).

### OB-22: el ejemplo de alertas no cumple la regla de anotaciones

- **Severidad:** baja
- **Tipo:** a
- **Evidencia:**
  - SLO:34: `Toda alerta lleva severity (page | ticket), summary, description con el valor y runbook_url`.
  - SLO:108-115 (`OrdersApiDown`) y SLO:117-124 (`OrdersApiNoOrders`): sin `description`. SLO:219 no la pide en el checklist.
  - SLO:35: `si ServiceDown está activa`, contra SLO:108 y SLO:190: `OrdersApiDown`.
- **Confirmación:** por lectura.
- **Impacto:** el agente copia alertas que incumplen la regla, y el texto de inhibición usa otro nombre.
- **Plan de corrección:** agregar `description` a ambas. Alinear SLO:219 con SLO:34. SLO:35: `OrdersApiDown`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### OB-23: la tabla de capas no permite a los services importar `observability`

- **Severidad:** baja
- **Tipo:** b
- **Evidencia:**
  - LAYER:32: services `Puede importar`: `crud, models, schemas, errors, config (Settings), otros services`.
  - MET:20: `módulo app/observability/metrics.py … importadas por los services`. LAYER:23: `services/ … métricas de negocio`.
- **Confirmación:** por lectura. El contrato de `import-linter` (LAYER:232-241) no incluye `app.observability`, así que no lo bloquea.
- **Impacto:** un revisor siguiendo la tabla rechazaría el patrón de MET:82-85.
- **Plan de corrección:** LAYER:32: agregar `observability` (métricas y `tracer`) a `Puede importar`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend (LAYER:32).

### OB-24: la description de LOG promete Promtail, sin contenido

- **Severidad:** baja
- **Tipo:** a
- **Evidencia:**
  - LOG:3: `Grafana Alloy/Promtail pipelines`. LOG:6: `Promtail` en `triggers`.
  - El cuerpo de LOG solo tiene Alloy.
- **Confirmación:** por lectura.
- **Impacto:** quien pide un pipeline de Promtail activa la skill y no obtiene eso ni una indicación de migrar.
- **Plan de corrección:** agregar en el cuerpo "Promtail: migrar a Alloy", manteniendo el trigger, o quitarlo de la description.
- **Decisión requerida:** ¿mantener el trigger? Recomiendo mantenerlo con esa línea: atrae a quien tiene un Promtail heredado.
- **Otros dominios afectados:** ninguno.

### OB-25: el pin de SQLAlchemy está escrito de tres formas, y la skill de engine no lo menciona

- **Severidad:** baja
- **Tipo:** b, e
- **Evidencia:**
  - SCAF:21: `sqlalchemy>=2.0,<2.1`. SCAF:73 y SCAF:101: `sqlalchemy[asyncio]>=2.0.40,<2.1`. TRC:26: `sqlalchemy<2.1`.
  - DB: sin ninguna mención, aunque instala el engine que TRC:89 instrumenta.
  - TRC:26: versión `0.66b1`. Hoy se resuelve `0.66b2`, con la misma restricción.
- **Confirmación:** ejecutado. Con sqlalchemy 2.1.6 e instrumentación 0.66b2: `SQLAlchemyInstrumentor only instruments "sqlalchemy >= 1.0.0, < 2.1.0", but currently installed version ("sqlalchemy 2.1.6") falls outside of that range`, y no instrumenta. El texto de TRC:179 es exacto. Sin pin, pip/uv instalan 2.1.6 hoy.
- **Impacto:** un agente que entra por DB sin pasar por SCAF ni TRC instala 2.1 y pierde los spans SQL en silencio.
- **Plan de corrección:** canónico `sqlalchemy[asyncio]>=2.0.40,<2.1` (el de `pyproject`, y el de `DIAGNOSTICO.md:70`). Unificar SCAF:21 y TRC:26. Agregar una línea en DB con referencia a TRC:26. TRC:26: "0.66b1 y 0.66b2".
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** database (DB) y backend (SCAF:21).

---

## Dudosos

No los cuento como hallazgos: dependen de una lectura de intención o de una decisión que el texto no fija.

1. **`OrdersApiNoOrders` frente al aviso de volumen mínimo.** SLO:17 pide limitar las alertas de ausencia al horario con actividad. SLO:118 publica la alerta sin eso. SLO:17 está planteada como condición "antes de activar", así que puede ser intencional.
2. **Dos líneas `error` por cada 500.** Ejecutado: `unhandled error` con `trace_id`, y luego `uvicorn.error` `"Exception in ASGI application\n"` sin `trace_id`, porque Starlette re-lanza la excepción. Choca en parte con LOG:176.
3. **`color_message` en el JSON.** Ejecutado: uvicorn emite `"color_message": "Started server process [\u001b[36m%d\u001b[0m]"`. LOG:21 no lo lista, pero admite campos de `extra`.
4. **Puertos publicados.** MET:39 desaconseja `/metrics` público. DOCKER:197 publica `8000:8000` (el nginx solo proxea `/api/`) y STACK publica 9090, 9093, 3100 (`auth_enabled: false`) y 3200. DOCKER:230 solo restringe `--reload` y el volumen de código para producción.
5. **Secretos de Alertmanager ausentes.** `amtool check-config` da SUCCESS sin los archivos de `url_file` (ejecutado). Que un clon limpio arranque y las páginas fallen recién al enviarse es deducción, sin ejecutar. `SCAF:50` promete que clonar + `up` reproduce todo, y SCAF:110 solo exceptúa `.env` y el bootstrap.
6. **Guardia de `setup_tracing` con varias apps.** TRC:67 retorna si `_provider` ya existe, así que un segundo `create_app()` queda sin instrumentar, contra LAYER:50 (`tests y workers pueden construir apps con otros settings`). Por lectura. `setup_metrics` no tiene ese problema: ejecuté `create_app()` dos veces y ambas apps exponen sus métricas sin error.
7. **Regla de cardinalidad y `http_requests_total`.** MET:22: producto de labels `< 100` por métrica. `handler × method × status` la supera en una API mediana, y MET:19 lo recomienda. Puede leerse como aplicable solo a métricas de negocio.
8. **Detalles de `build_dashboard.py`.** `README.md:51` pide ejemplos tipados y DASH no tiene type hints. DASH:111 emite `0.0010000000000000009` en las queries, contra `0.001` en las reglas (mismo resultado práctico).

---

## Cruces que dieron correctos

No hace falta revisarlos:

- **Nombres de métricas y labels:** `http_requests_total{handler,method,status}`, `http_request_duration_seconds_{bucket,count}`, `shop_orders_created_total`, `shop_order_rejections_total{reason}`, `shop_order_value_usd_*` coinciden entre `/metrics` real, reglas, alertas, PromQL de MET y queries de DASH. `status="5xx"` y `le="0.5"` existen.
- **`job="orders-api"`:** coincide entre `prometheus.yml`, reglas y DASH. `backend:8000` y `/metrics` coinciden con compose y `setup_metrics`.
- **`service.name` = `APP_NAME` = `SERVICE` en DASH.** `{service="backend"}` coincide con el nombre del servicio en DOCKER.
- **Exclusiones `/metrics` y `/health/.*`:** cubren `/api/v1/health/live` en métricas y en trazas (ejecutado), como afirma DB:25.
- **Campos de log:** `level` en minúscula coincide con `level=~"error|critical"`. `trace_id` de 32 hex y `span_id` de 16 hex coinciden con Alloy, structured metadata, derived field y ERR. Tempo acepta el `trace_id` por `/api/v2/traces/<id>` con 200.
- **Handler de 500:** devuelve `trace_id` también en el 500, y el log `unhandled error` lleva el mismo id (ejecutado con OTel activo). Sin OTel, el campo no aparece. `problem+json` sigue igual.
- **`Settings`:** `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `OTEL_TRACES_SAMPLER_RATIO`, `LOG_LEVEL`, `APP_NAME`, `APP_VERSION` y `APP_ENV.value` existen. `tests/snippets/test_python_snippets.py`: 7 passed. No hay campo `METRICS_*` y ninguna skill lo lee.
- **`setup_tracing(app, engine, settings)`, `setup_metrics(app)`, `configure_logging(settings)`:** firmas iguales en LAYER y en las skills. `engine.sync_engine` funciona con el engine async de DB.
- **Versiones de imágenes:** idénticas en SLO, STACK, TRC:46 y `DIAGNOSTICO.md`. Los seis tags existen localmente; todos corrieron salvo Grafana, de la que solo inspeccioné el bundle.
- **Rutas:** las de `monitoring/...` coinciden entre SLO, LOG y STACK. `allow_structured_metadata` está en `loki.yml`.
- **Herramientas:** `promtool test rules`, `check rules`, `amtool check-config`, `alloy validate` y `loki -verify-config` pasan sobre los bloques publicados.
- **Tempo 3.1.1:** arranca con `tempo.yml`, `block_retention: 168h` se aplica, y el metrics-generator envía `traces_spanmetrics_*` y `traces_service_graph_*` a Prometheus.
- **Log `falls outside of that range`** de TRC:179: texto exacto.

## Lo que no se pudo verificar

- **UI de Grafana:** no abrí Grafana ni hice clic en los enlaces. OB-02 y OB-05 combinan lectura del bundle con consultas reales a Loki y Prometheus. Las correcciones `customQuery` y `name: traceID` están sin probar en la UI.
- **Alloy de punta a punta:** solo `alloy validate`. No lo conecté al socket de Docker porque habría leído logs de los contenedores ajenos del host (TurnApp). En Loki empujé con los labels de la config.
- **`docker compose up` completo del stack:** corrí Prometheus, Tempo y Loki en una red manual, no con el compose publicado.
- **PostgreSQL:** toda la app de referencia usó SQLite en memoria o nada de base. El comportamiento de `get_for_update` y spans SQL en Postgres no se repitió.
- **Alertas reales de Prometheus hacia Alertmanager:** la prueba de inhibición envió alertas por la API con los labels que `promtool` confirmó, no desde Prometheus.
- **Bug de `opentelemetry` importable en el bootstrap:** el error en SCAF:101 es `No module named 'opentelemetry.exporter'`, no `opentelemetry` a secas: algún paquete del entorno ya trae la API. No investigué cuál; el fallo de arranque es el mismo.

## Notas fuera de alcance, para otros auditores

- **Testing, TEST:116:** `with PostgresContainer("postgres:16-alpine", driver="asyncpg")  # = la versión de producción as pg:`. El comentario se comió el `as pg:`. Ejecutado con `compile()`: `SyntaxError: expected ':'`. El `conftest` publicado no compila, aunque TEST:59 lo marca como verificado.
- **Testing, TEST:156 y TEST:28:** el `client` usa `ASGITransport(app=app)` con el default `raise_app_exceptions=True`, y la matriz pide "un 500 forzado". ERR:213 sí usa `raise_app_exceptions=False`. Por lectura.
- **Backend, `configuring-fastapi-settings/SKILL.md:37`:** recomienda `DOCS_ENABLED`, que no existe en `Settings` (`SKILL.md:79-109`), y LAYER:208 usa `settings.is_prod`. Por lectura.
