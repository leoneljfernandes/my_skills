---
name: handling-fastapi-errors
description: Use when a FastAPI service needs error handling - business rule violations, 404/409/422 responses, custom exceptions, global exception handlers, RFC 9457 problem+json, an endpoint returning 500 for an expected case, try/except HTTPException scattered in routers, or error messages leaking internals to clients.
domain: backend
tags: [python, fastapi, exceptions, error-handling, rfc9457, problem-details]
triggers: [HTTPException, exception_handler, "problem+json", "RFC 9457", "RFC 7807", "error 500", "custom exception", "manejo de errores", "excepciones de dominio", RequestValidationError]
---

# Errores de dominio desacoplados de HTTP

Los `services` lanzan **excepciones de dominio** que no saben nada de HTTP. Un único módulo las traduce a respuestas `application/problem+json` (RFC 9457). Un 500 significa siempre un bug, nunca un caso de negocio.

## Contexto y reglas

**Hacer**

- Jerarquía propia con base `AppError`. Cada subclase declara `status_code`, `code` (estable, en snake_case, para que el cliente haga `switch`) y `title`.
- Las excepciones específicas de un caso de uso heredan de la genérica: `InsufficientStockError(BusinessRuleError)`. El handler las cubre sin cambios.
- Un único `register_exception_handlers(app)` registra 4 handlers: `AppError`, `RequestValidationError`, `StarletteHTTPException` (incluye 404/405 de ruteo) y `Exception` (red final).
- El cuerpo siempre tiene la misma forma: `type`, `title`, `status`, `code`, `detail`, `instance` y `trace_id` si hay traza activa. Los campos extra van como extensiones (`available`, `errors`).
- El handler de `Exception` loguea el traceback con `logger.exception` y responde un mensaje genérico. El cliente recibe el `trace_id` para reportar el incidente.
- `HTTPException` solo en la capa `api/`, para errores de transporte (401 con `WWW-Authenticate`, 415, 413).
- Errores de integridad de la base (`IntegrityError`) se capturan **en el service** y se convierten a `ConflictError`, cubriendo la carrera entre "chequeo" e "insert".

**Evitar (anti-patrones)**

| Anti-patrón | Por qué es un problema | En su lugar |
|---|---|---|
| `raise HTTPException(404)` dentro de `services/` | acopla el dominio a HTTP; no reutilizable desde workers/CLI | `raise NotFoundError(...)` |
| `try/except` en cada router para traducir errores | duplicación; un caso olvidado = 500 | handler global por tipo |
| Devolver `{"error": str(exc)}` en un 500 | filtra SQL, DSNs, rutas internas | mensaje genérico + `trace_id`; detalle en logs |
| Formatos distintos por endpoint (`detail` string vs objeto) | el frontend no puede tipar errores | un único shape problem+json |
| Comparar mensajes de texto en el cliente | romper un mensaje rompe la UI | campo `code` estable |
| `except Exception: pass` en services | errores silenciosos, datos inconsistentes | dejar propagar; el handler loguea |
| 400 genérico para todo | el cliente no distingue reintentar de corregir | 404/409/422 según semántica |

| Situación | Excepción | HTTP |
|---|---|---|
| Recurso inexistente o ajeno sin permiso de ver | `NotFoundError` | 404 |
| Duplicado / estado concurrente | `ConflictError` | 409 |
| Regla de negocio violada con payload válido | `BusinessRuleError` | 422 |
| Acción prohibida para este usuario | `PermissionDeniedError` | 403 |
| Payload con forma inválida | `RequestValidationError` (FastAPI) | 422 `validation_error` |
| Cualquier otra cosa | `Exception` | 500 `internal_error` |

## Ejemplos

`app/errors.py` (verificado: tests de integración comprueban 404/409/422/500 y que el 500 no filtra el mensaje interno):

```python
import logging
from collections.abc import Mapping
from typing import Any, ClassVar

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.observability.tracing import current_trace_id

logger = logging.getLogger(__name__)
PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    """Base de los errores de dominio. Los services lanzan esto, nunca HTTPException."""

    status_code: ClassVar[int] = status.HTTP_400_BAD_REQUEST
    code: ClassVar[str] = "bad_request"
    title: ClassVar[str] = "Bad request"

    def __init__(self, detail: str, *, extra: Mapping[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra: dict[str, Any] = dict(extra or {})


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    title = "Resource not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    title = "Conflict"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    title = "Permission denied"


class BusinessRuleError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "business_rule_violated"
    title = "Business rule violated"


def problem(
    request: Request, *, status_code: int, code: str, title: str, detail: str | None = None,
    extra: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://errors.example.com/{code}",  # URI estable y documentada por código
        "title": title, "status": status_code, "code": code, "instance": request.url.path,
    }
    if detail:
        body["detail"] = detail
    if trace_id := current_trace_id():
        body["trace_id"] = trace_id
    if extra:
        body.update(jsonable_encoder(extra))
    return JSONResponse(body, status_code=status_code, media_type=PROBLEM_JSON, headers=headers)


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    logger.info("domain error", extra={"error_code": exc.code, "status": exc.status_code})
    return problem(request, status_code=exc.status_code, code=exc.code, title=exc.title,
                   detail=exc.detail, extra=exc.extra)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [{k: e[k] for k in ("type", "loc", "msg") if k in e} for e in exc.errors()]
    return problem(request, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                   code="validation_error", title="Request validation failed", extra={"errors": errors})


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return problem(request, status_code=exc.status_code, code=f"http_{exc.status_code}",
                   title=str(exc.detail), headers=exc.headers)


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # El traceback va al log (con trace_id); al cliente nunca le llega el mensaje interno.
    logger.exception("unhandled error", extra={"path": request.url.path})
    return problem(request, status_code=500, code="internal_error", title="Internal server error")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)
```

Excepción específica + uso en el service:

```python
class InsufficientStockError(BusinessRuleError):
    code = "insufficient_stock"
    title = "Insufficient stock"


if product.stock < data.quantity:
    raise InsufficientStockError(
        f"Only {product.stock} units available",
        extra={"available": product.stock, "requested": data.quantity},
    )
```

Respuesta resultante:

```json
{"type": "https://errors.example.com/insufficient_stock", "title": "Insufficient stock",
 "status": 422, "code": "insufficient_stock", "instance": "/api/v1/orders",
 "detail": "Only 1 units available", "trace_id": "3db8b2e2...", "available": 1, "requested": 2}
```

Test de la red final (la app debe responder aunque el service explote):

```python
transport = ASGITransport(app=app, raise_app_exceptions=False)  # queremos la respuesta, no la excepción
...
assert response.status_code == 500
assert response.json()["code"] == "internal_error"
assert "hunter2" not in response.text
```

## Checklist de verificación

- [ ] `grep -rn "HTTPException" app/services app/crud` no devuelve nada.
- [ ] Cada regla de negocio tiene un test que verifica status **y** `code`.
- [ ] Un test fuerza una excepción no controlada y verifica 500 + `code="internal_error"`, sin el mensaje interno en el body.
- [ ] Todas las respuestas de error tienen `Content-Type: application/problem+json`, incluidos los 404 de rutas inexistentes y los 422 de validación.
- [ ] Los `IntegrityError` esperables (unique, FK) se traducen a 409/422 en el service.
- [ ] Los códigos (`code`) están documentados para el frontend. Ver `building-axios-clients`, que los mapea a tipos.

## Skills relacionadas

- `layering-fastapi-apps`: qué capa lanza qué.
- `tracing-with-opentelemetry`: de dónde sale `current_trace_id()`.
- `building-axios-clients`: consumo tipado de este formato en el frontend.
