---
name: logging-json-to-loki
description: Use when adding or fixing application logging in a Python/FastAPI service shipped to Grafana Loki - structured JSON logs, log levels, correlating logs with traces via trace_id, uvicorn log format, Grafana Alloy/Promtail pipelines, Loki labels vs structured metadata - or when logs are plain text, print() is used, logs cannot be linked to a request, PII appears in logs, or Loki rejects streams for too many labels.
domain: observability
tags: [python, fastapi, logging, json, loki, grafana-alloy, correlation]
triggers: [logging, "logs JSON", "structured logging", Loki, LogQL, Alloy, Promtail, trace_id, "correlation id", "logger.info", print, "uvicorn logs", "structured metadata", "too many labels"]
---

# Logs JSON correlados con trazas (Loki)

Una línea JSON por evento en stdout. Cada línea lleva `trace_id`/`span_id` de la request en curso. Esta skill tiene dos partes independientes:

- **Formato JSON a stdout**: se aplica **siempre**. Sirve con cualquier alojamiento (los logs de una plataforma, `docker logs`, Loki).
- **Envío a Loki con Alloy**: solo si el despliegue tiene contenedores propios de monitoreo. Alloy parsea el JSON: `level` va como label y `trace_id` como *structured metadata*, y se salta de un log a su traza y de la traza a sus logs.

## Contexto y reglas

**Hacer (formato, siempre)**

- `logging` de la stdlib con un `JsonFormatter` propio (sin dependencias) configurado **una vez** en `create_app()`. Todo módulo usa `logger = logging.getLogger(__name__)`.
- Campos fijos: `ts` (ISO-8601 UTC), `level`, `logger`, `msg`, `service`, `env`. Más `trace_id`/`span_id` si hay span activo, y el contexto vía `extra={...}`.
- Si varias instalaciones del mismo producto reportan a un monitoreo central, sumar el campo opcional `installation` (el nombre de la instalación) a los logs y al `Resource` de las trazas, para identificar de cuál viene un error. **Nunca** como label de Loki ni de Prometheus: crece con cada instalación (alta cardinalidad); va en el JSON y se filtra con `| json`.
- Mensajes **constantes** y datos en campos: `logger.info("order placed", extra={"order_id": 42})`, no f-strings. Así se puede agrupar y contar por `msg`.
- Excepciones con `logger.exception(...)` dentro del `except`: el traceback va en `exc`, en la misma línea JSON.
- Quitar los handlers propios de `uvicorn`/`uvicorn.error`/`uvicorn.access` y propagar al root: todo sale en JSON. El access log se baja a WARNING, porque métricas y trazas ya cubren cada request.
- Logs a **stdout** sin archivos ni rotación: el runtime de contenedores los recoge.

**Hacer (envío a Loki, solo con contenedores propios)**

- **Labels de Loki solo de baja cardinalidad** (`service`, `level`, `env`). `trace_id`, `user_id` y `order_id` van como structured metadata o quedan en el JSON (se filtran con `| json`).
- Niveles con semántica: `debug` diagnóstico, `info` eventos de negocio, `warning` anomalía recuperable, `error` falló una operación, `critical` el proceso no puede seguir.
- Nunca loguear secretos, tokens, contraseñas ni PII sin enmascarar (emails, documentos, tarjetas).

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `print()` | sin nivel, sin trace_id, sin estructura | `logger.info(...)` |
| `logger.info(f"order {id} placed for {email}")` | no agrupable; filtra PII | mensaje fijo + `extra` sin PII |
| `trace_id` como label de Loki | una stream por request → `too many streams`, Loki degradado | structured metadata |
| Logs multilínea (traceback en texto plano) | cada línea es una entrada distinta en Loki | traceback dentro del JSON (`exc`) |
| `logging.basicConfig` en módulos de librería | config impredecible según el orden de import | configurar solo en `create_app()` |
| Loguear request/response bodies completos | volumen, costo y fuga de datos | ids + tamaños; el detalle va en trazas con sampling |
| Nivel `error` para 4xx esperables | alertas ruidosas, fatiga | `info`/`warning` para errores de dominio |

## Ejemplos

`app/observability/logging.py` (verificado: un test comprueba que la línea JSON lleva el `trace_id` del span activo y los campos de `extra`):

```python
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.observability.tracing import current_span_id, current_trace_id

# Atributos estándar de LogRecord: todo lo demás vino por extra={...}.
_RESERVED = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self._static = {"service": service, "env": environment}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            **self._static,
        }
        if trace_id := current_trace_id():
            payload["trace_id"] = trace_id
            payload["span_id"] = current_span_id()
        payload.update(
            {k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")}
        )
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service=settings.APP_NAME, environment=settings.APP_ENV.value))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.LOG_LEVEL)
    # uvicorn trae sus propios handlers en texto plano: se los quita para que todo salga en JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # métricas y trazas ya cubren el acceso
```

Línea emitida durante una request real:

```json
{"ts": "2026-10-23T21:36:30.364+00:00", "level": "info", "logger": "app.services.order", "msg": "order placed", "service": "orders-api", "env": "test", "trace_id": "3db8b2e25b44fc32c88719630671f3c6", "span_id": "33c676cef82f7648", "order_id": 1, "product_id": 1}
```

`monitoring/alloy/config.alloy` (validado con `alloy validate`, y probado de punta a punta: Loki indexa `level` como label y `trace_id` como structured metadata):

```river
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

discovery.relabel "containers" {
  targets = discovery.docker.containers.targets
  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_service"]
    target_label  = "service"
  }
  rule {
    source_labels = ["__meta_docker_container_name"]
    regex         = "/(.*)"
    target_label  = "container"
  }
}

loki.source.docker "containers" {
  host          = "unix:///var/run/docker.sock"
  targets       = discovery.relabel.containers.output
  relabel_rules = discovery.relabel.containers.rules
  forward_to    = [loki.process.json_logs.receiver]
}

loki.process "json_logs" {
  // Parsea la línea JSON emitida por la app; líneas no-JSON pasan intactas.
  stage.json {
    expressions = { level = "level", trace_id = "trace_id", span_id = "span_id", ts = "ts" }
  }
  // Label: SOLO baja cardinalidad (level tiene ~5 valores).
  stage.labels {
    values = { level = "" }
  }
  // trace_id/span_id como structured metadata: filtrables, sin crear streams nuevos.
  stage.structured_metadata {
    values = { trace_id = "", span_id = "" }
  }
  // Usa el timestamp de la app, no el de ingesta.
  stage.timestamp {
    source = "ts"
    format = "RFC3339"
  }
  forward_to = [loki.write.default.receiver]
}

loki.write "default" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

Loki necesita `limits_config.allow_structured_metadata: true` (ver `defining-grafana-slos` → references/stack.md). Consultas LogQL:

```logql
{service="backend", level="error"}                                        # errores del backend
{service="backend"} | trace_id="3db8b2e25b44fc32c88719630671f3c6"         # todo lo de una request
{service="backend"} | json | msg="order placed" | order_id="42"           # campo del JSON
sum by (level) (count_over_time({service="backend"}[5m]))                 # volumen por nivel
```

## Checklist de verificación

- [ ] `grep -rn "print(" app/` solo encuentra comandos de línea de comandos (un `bootstrap.py` o `seed.py` ejecutado con `python -m`, que informan por stdout). Excluirlos: `grep -rn "print(" app/ --exclude=bootstrap.py --exclude=seed.py` no devuelve nada.
- [ ] `docker compose logs backend` (o los logs de la plataforma) muestra solo líneas JSON válidas, incluidas las de uvicorn y los tracebacks.
- [ ] Durante una request, las líneas tienen `trace_id` (si hay traza activa).
- [ ] Con Loki: en Grafana el link *Ver traza* abre la traza en Tempo, y `curl loki:3100/loki/api/v1/labels` no lista `trace_id`, `user_id`, `installation` ni otros labels de alta cardinalidad.
- [ ] Ningún log contiene contraseñas, tokens, `Authorization` ni emails completos.
- [ ] Los errores de dominio (4xx) se loguean como `info`/`warning`; `error` queda para fallos reales.

## Skills relacionadas

- `tracing-with-opentelemetry`: de dónde salen `current_trace_id()` y `current_span_id()`.
- `defining-grafana-slos`: datasources (derived field Loki → Tempo) y dashboards.
