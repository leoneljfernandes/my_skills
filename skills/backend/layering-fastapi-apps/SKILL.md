---
name: layering-fastapi-apps
description: Use when structuring or extending a FastAPI codebase - adding an endpoint, resource or use case, deciding where code goes (api, schemas, services, crud/repositories, models), dependency injection with Depends, Pydantic v2 DTOs, or when routers contain SQL or business logic, services raise HTTPException, or modules import each other in circles.
domain: backend
tags: [python, fastapi, clean-architecture, layered-architecture, pydantic-v2, dependency-injection, sqlalchemy]
triggers: [FastAPI, "Clean Architecture", "arquitectura en capas", Depends, router, endpoint, "service layer", repository, crud, schemas, "Pydantic v2", DTO, "nuevo endpoint", "inyección de dependencias"]
---

# Arquitectura en capas para FastAPI

Cuatro capas con dependencias en un solo sentido: `api → services → crud → models`. `schemas` es transversal (contratos). Cada capa es reemplazable y testeable por separado.

## Contexto y reglas

```text
app/
├── main.py          # create_app(): middlewares, handlers, routers, lifespan
├── config.py        # Settings (ver configuring-fastapi-settings)
├── database.py      # engine, SessionFactory, get_db (ver configuring-sqlalchemy-sessions)
├── errors.py        # AppError + handlers (ver handling-fastapi-errors)
├── security.py      # JWT y hashing, sin base de datos (ver scaffolding-fastapi-backends/references/security.md)
├── api/             # PRESENTACIÓN: routers + deps.py (composición con Depends)
├── schemas/         # CONTRATOS: Pydantic v2 <X>Create / <X>Update / <X>Read
├── services/        # CASOS DE USO: reglas de negocio, transacción, métricas de negocio
├── crud/            # REPOSITORIOS: único lugar con select/insert/update/delete
├── models/          # ORM SQLAlchemy 2.0: base.py, una entidad por módulo y __init__.py que las re-exporta
└── observability/   # logging, metrics, tracing
```

| Capa | Responsabilidad | Puede importar | Nunca |
|---|---|---|---|
| `api/` | validar entrada (schema), resolver deps, elegir status code, serializar `XRead` | `services`, `schemas`, `api.deps`, `errors`, `config`, `models` (enums, tipos). Solo `api/deps.py` (la raíz de composición) importa también `crud` y `database` | SQL, reglas de negocio, `commit` |
| `services/` | reglas de negocio, orquestar repositorios y otros services, **dueño de la transacción** (`commit`), lanzar `AppError` | `crud`, `models`, `schemas`, `errors`, `config` (`Settings`), `observability` (métricas y `tracer`), `security`, otros `services` | `HTTPException`, `Request`, `Response` |
| `crud/` | queries; `add`/`flush`; devolver entidades o `None` | `models` | `commit`, reglas de negocio, `HTTPException` |
| `models/` | tablas, relaciones, constraints | `models.base` | importar de capas superiores |
| `schemas/` | validación I/O, serialización | `models` (solo enums) | lógica, acceso a datos |

**Hacer**

- **Repositorios como clases** que reciben `AsyncSession` por constructor. **Services como clases** que reciben sesión + repositorios (y, si lo necesitan, `Settings` u otros services). Así los tests reemplazan colaboradores externos sin `patch` de módulos.
- **Un service puede recibir otros services** (`OrderService` usa `StockService`). Solo commitea el que abre el caso de uso; los colaboradores usan `flush`. Un colaborador que commitea en medio libera los bloqueos (`FOR UPDATE`) del caso de uso que lo llamó.
- **Composición en `api/deps.py`**: funciones `get_<x>_service(db: DbSession)` + alias `XServiceDep = Annotated[XService, Depends(...)]`. Los routers solo declaran `service: XServiceDep`.
- **Un `commit` por caso de uso, en el service que lo abre**. El repositorio y los services colaboradores hacen `add`/`flush`. Si el caso de uso falla antes del commit, la sesión se cierra y todo se descarta.
- **Trío de schemas** por recurso: `XCreate` (`extra="forbid"`, restricciones con `Annotated[..., Field(...)]`), `XUpdate` (todo opcional; se aplica con `model_dump(exclude_unset=True)`), `XRead` (`from_attributes=True`).
- **Acciones** (reprogramar, cambiar estado, cancelar) tienen su propio schema chico (`OrderReschedule`, `OrderStatusChange`), no un `XUpdate` reutilizado: cada uno exige exactamente los campos de esa acción.
- **`null` explícito en un `PATCH`**: un campo `NOT NULL` rechaza `null` en el schema (`field_validator` que levanta `ValueError` → 422). Un campo nullable lo acepta y `exclude_unset` lo escribe como `NULL`. Sin ese validador, `{"campo": null}` sobre un campo `NOT NULL` termina en 500.
- El router **retorna el DTO** (`-> OrderRead`, `OrderRead.model_validate(entity)`). FastAPI usa la anotación como `response_model`: filtra campos que no estén en el schema.
- **Qué devuelve un service**: la entidad por defecto. Devuelve un DTO (`OrderRead`) solo si la respuesta necesita datos que el router no tiene, por ejemplo la zona horaria de la instalación para formatear fechas.
- Dinero como `Decimal` (`Numeric` en la base); Pydantic lo serializa como string en JSON, sin pérdida de precisión.
- Paginación (`offset`/`limit` acotado con `Query(ge=1, le=100)`) en todo listado que crece sin límite. Un catálogo chico y acotado (decenas de filas) puede devolverse completo; un listado por rango de fechas exige el rango con un máximo explícito (p. ej. 62 días).
- `create_app()` como factory, **sin parámetros**: lee `get_settings()` y le pasa esa `settings` a lo que arma (título, CORS, docs, logging, métricas y tracing). Dos piezas no pasan por ahí: los errores llaman a `get_settings()` en cada request (`ERRORS_BASE_URL`) y el engine se crea **al importar** `app.database`, con la config de ese momento. Por eso una `Settings` pasada a mano no gobernaría la app entera. Para otra configuración en tests: variables de entorno + `get_settings.cache_clear()` antes de `create_app()` (fixture `env` de `configuring-fastapi-settings`); otra base u otro pool exigen fijar el entorno antes del primer import de `app.database`.
- `lifespan` en `main.py` cierra lo que la app abrió: `engine.dispose()` (sin `await` con la variante síncrona de `configuring-sqlalchemy-sessions`) y, al final, `shutdown_tracing()` para no perder los últimos spans.
- Salud en `/health/live` y `/health/ready`, fuera de `/api/v1`: es lo que consulta el orquestador, y las exclusiones de métricas y trazas (`/health/.*`) ya los cubren. `ready` hace `SELECT 1` a través de un repositorio (`HealthRepository.ping()`), no con SQL en el router.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `select(...)` dentro del router | lógica no reutilizable, imposible de testear sin HTTP | método del repositorio |
| `await db.commit()` en el repositorio | dos repos = dos transacciones; estado parcial ante fallos | commit en el service |
| Service que recibe `Request` o devuelve `JSONResponse` | acoplado a HTTP; no sirve desde un worker | recibir DTOs, devolver entidades (o un DTO de dominio, nunca una respuesta HTTP) |
| Devolver la entidad ORM sin `response_model` | expone columnas internas (`password_hash`) | retornar `XRead` |
| Colaborador (service) que hace `commit` en medio de un caso de uso | libera el bloqueo de la fila y deja el caso de uso a medias | `flush` en el colaborador; `commit` solo en el service que abre el caso de uso |
| Un único schema para crear, actualizar y leer | `id`/`created_at` aceptados como input; updates pisan con `None` | trío Create/Update/Read |
| `Optional[...]` + `model_dump()` en PATCH | campos omitidos se escriben como `NULL` | `model_dump(exclude_unset=True)` |
| Instanciar servicios a mano dentro del endpoint | no se pueden sobreescribir en tests | `Depends(get_x_service)` |
| `float` para importes | errores de redondeo en totales | `Decimal` + `Numeric(12, 2)` |

## Ejemplos

Flujo completo de un caso de uso (código verificado a mano (2026-10-23, pytest, mypy `--strict` y ruff)).

`app/schemas/order.py`:

```python
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PositiveInt

from app.models import OrderStatus


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos → 422, no se ignoran

    customer_email: EmailStr
    product_id: PositiveInt
    quantity: Annotated[int, Field(gt=0, le=1000)]


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_email: EmailStr
    product_id: int
    quantity: int
    total: Decimal
    status: OrderStatus
    created_at: datetime
```

`app/schemas/common.py` (la página de cualquier listado) y `app/schemas/product.py`. Producto no tiene `PATCH` en este ejemplo, así que no lleva `ProductUpdate`; los límites copian los del modelo (`String(64)`, `Numeric(12, 2)`, `CHECK`), así un valor fuera de rango es un 422 y no un error de la base:

```python
from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    offset: int
    limit: int
```

```python
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Annotated[str, Field(min_length=1, max_length=64)]
    name: Annotated[str, Field(min_length=1, max_length=200)]
    price: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    stock: Annotated[int, Field(ge=0)] = 0


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    price: Decimal
    stock: int
    is_active: bool
```

`app/crud/product.py` (repositorio):

```python
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product


class ProductRepository:
    """Único lugar con SQL de productos. No hace commit: eso lo decide el service."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, product_id: int) -> Product | None:
        return await self._session.get(Product, product_id)

    async def get_for_update(self, product_id: int) -> Product | None:
        # SELECT ... FOR UPDATE: bloquea la fila hasta el commit (evita sobreventa concurrente).
        stmt = select(Product).where(Product.id == product_id).with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()

    async def list(self, *, offset: int, limit: int) -> Sequence[Product]:
        stmt = select(Product).order_by(Product.id).offset(offset).limit(limit)
        return (await self._session.scalars(stmt)).all()

    def add(self, product: Product) -> None:
        self._session.add(product)
```

`app/crud/order.py` y `app/crud/health.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, order_id: int) -> Order | None:
        return await self._session.get(Order, order_id)

    def add(self, order: Order) -> None:
        self._session.add(order)
```

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class HealthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ping(self) -> None:
        await self._session.execute(text("SELECT 1"))  # falla si la base no responde
```

`app/services/product.py` (alta con el `IntegrityError → ConflictError` de `handling-fastapi-errors`: el `UNIQUE` del SKU decide, sin un `SELECT` previo que otra request puede ganar):

```python
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.product import ProductRepository
from app.errors import ConflictError
from app.models import Product
from app.schemas.product import ProductCreate


class ProductService:
    def __init__(self, session: AsyncSession, products: ProductRepository) -> None:
        self._session = session
        self._products = products

    async def list(self, *, offset: int, limit: int) -> Sequence[Product]:
        return await self._products.list(offset=offset, limit=limit)

    async def create(self, data: ProductCreate) -> Product:
        product = Product(**data.model_dump())
        try:
            self._products.add(product)
            await self._session.flush()  # acá salta el UNIQUE, antes del commit
        except IntegrityError as exc:
            await self._session.rollback()  # tras el fallo la sesión no sirve hasta el rollback
            raise ConflictError(f"SKU {data.sku} already exists") from exc
        await self._session.commit()
        return product
```

`app/services/order.py` (caso de uso, dueño de la transacción). Su error propio, `InsufficientStockError`, vive acá: `app/errors.py` tiene las bases y los handlers, no los errores de cada caso de uso:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.order import OrderRepository
from app.crud.product import ProductRepository
from app.errors import BusinessRuleError, NotFoundError
from app.models import Order
from app.schemas.order import OrderCreate


class InsufficientStockError(BusinessRuleError):
    code = "insufficient_stock"
    title = "Insufficient stock"


class OrderService:
    def __init__(
        self, session: AsyncSession, products: ProductRepository, orders: OrderRepository
    ) -> None:
        self._session = session
        self._products = products
        self._orders = orders

    async def place_order(self, data: OrderCreate) -> Order:
        product = await self._products.get_for_update(data.product_id)
        if product is None or not product.is_active:
            raise NotFoundError(f"Product {data.product_id} not found")
        if product.stock < data.quantity:
            raise InsufficientStockError(
                f"Only {product.stock} units available",
                extra={"available": product.stock, "requested": data.quantity},
            )
        product.stock -= data.quantity
        order = Order(
            customer_email=data.customer_email,
            product_id=product.id,
            quantity=data.quantity,
            total=product.price * data.quantity,
        )
        self._orders.add(order)
        await self._session.commit()  # un solo commit por caso de uso
        return order

    async def get(self, order_id: int) -> Order:
        order = await self._orders.get(order_id)
        if order is None:
            raise NotFoundError(f"Order {order_id} not found")
        return order
```

`app/api/deps.py` (la raíz de composición: el único módulo de `api/` que conoce `crud` y `database`). Nace en el paso 3 de `scaffolding-fastapi-backends` con `HealthRepoDep`; las líneas `# paso 4` llegan con el primer recurso:

```python
from typing import Annotated

from fastapi import Depends, Query

from app.crud.health import HealthRepository
from app.crud.order import OrderRepository  # paso 4
from app.crud.product import ProductRepository  # paso 4
from app.database import DbSession
from app.services.order import OrderService  # paso 4
from app.services.product import ProductService  # paso 4


def get_health_repository(db: DbSession) -> HealthRepository:
    return HealthRepository(db)


def get_product_service(db: DbSession) -> ProductService:  # paso 4
    return ProductService(db, ProductRepository(db))  # paso 4


def get_order_service(db: DbSession) -> OrderService:  # paso 4
    return OrderService(db, ProductRepository(db), OrderRepository(db))  # paso 4


HealthRepoDep = Annotated[HealthRepository, Depends(get_health_repository)]
ProductServiceDep = Annotated[ProductService, Depends(get_product_service)]  # paso 4
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]  # paso 4
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
```

`app/api/products.py` (listado paginado y alta):

```python
from fastapi import APIRouter, status

from app.api.deps import Limit, Offset, ProductServiceDep
from app.schemas.common import Page
from app.schemas.product import ProductCreate, ProductRead

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
async def list_products(
    service: ProductServiceDep, offset: Offset = 0, limit: Limit = 50
) -> Page[ProductRead]:
    products = await service.list(offset=offset, limit=limit)
    return Page[ProductRead](
        items=[ProductRead.model_validate(p) for p in products], offset=offset, limit=limit
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(data: ProductCreate, service: ProductServiceDep) -> ProductRead:
    return ProductRead.model_validate(await service.create(data))  # SKU repetido: 409 desde el service
```

`app/api/orders.py` (router fino) y `app/api/router.py` (como `api_router` en `main.py`, llega en el paso 4 con el primer recurso):

```python
from fastapi import APIRouter, status

from app.api.deps import OrderServiceDep
from app.schemas.order import OrderCreate, OrderRead

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def place_order(data: OrderCreate, service: OrderServiceDep) -> OrderRead:
    # El router solo traduce HTTP ↔ caso de uso. Sin SQL, sin reglas de negocio, sin try/except.
    return OrderRead.model_validate(await service.place_order(data))


@router.get("/{order_id}")
async def get_order(order_id: int, service: OrderServiceDep) -> OrderRead:
    return OrderRead.model_validate(await service.get(order_id))
```

```python
from fastapi import APIRouter

from app.api import orders, products  # paso 4

api_router = APIRouter()
api_router.include_router(products.router)  # paso 4: un include por router de recurso
api_router.include_router(orders.router)  # paso 4
```

`app/api/health.py`. Las líneas con `# paso N` se suman recién en ese paso del orden de construcción de `scaffolding-fastapi-backends` (la 3, `ready`, necesita la base); sin ellas el módulo ya sirve en el paso 2:

```python
from fastapi import APIRouter

from app.api.deps import HealthRepoDep  # paso 3

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}  # el proceso responde; no toca la base


@router.get("/ready")  # paso 3
async def ready(health: HealthRepoDep) -> dict[str, str]:  # paso 3
    await health.ping()  # paso 3
    return {"status": "ok"}  # paso 3
```

`app/main.py` (factory y `lifespan`). Cada línea `# paso N` se suma en ese paso; sin ellas la app ya importa y arranca en el paso 2 con `health.py`, `errors.py` y el `tracing.py` mínimo, con solo `opentelemetry-api` instalado. Qué entra en cada paso: el 3 trae `database.py` (el engine), `deps.py` con `HealthRepoDep` y `/health/ready`; el 4, el primer recurso (`api_router`, sus routers y las líneas `# paso 4` de `deps.py`); el 9, logging, métricas y tracing completos:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.router import api_router  # paso 4
from app.config import get_settings
from app.database import engine  # paso 3
from app.errors import register_exception_handlers
from app.observability.logging import configure_logging  # paso 9
from app.observability.metrics import setup_metrics  # paso 9
from app.observability.tracing import setup_tracing, shutdown_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()  # paso 3 (variante síncrona: engine.dispose(), sin await)
    shutdown_tracing()  # al final: flush de los spans en buffer (no hace nada sin tracing)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)  # paso 9
    app = FastAPI(
        title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan, redoc_url=None,
        docs_url="/docs" if settings.DOCS_ENABLED else None,
        openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,  # sin esto el esquema queda público
    )
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    setup_metrics(app, settings)  # paso 9: no hace nada si METRICS_ENABLED=false
    setup_tracing(app, engine, settings)  # paso 9: no hace nada sin OTEL_EXPORTER_OTLP_ENDPOINT
    app.include_router(health_router)
    app.include_router(api_router, prefix="/api/v1")  # paso 4
    return app


app = create_app()
```

Las capas se hacen cumplir con `import-linter` (en `pyproject.toml`), no solo con `grep`; falla el CI o el paso previo a integrar:

```toml
[tool.importlinter]
root_package = "app"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Capas: api -> services -> crud -> models"
type = "layers"
layers = ["app.api", "app.services", "app.crud", "app.models"]

[[tool.importlinter.contracts]]
name = "Services y crud no conocen HTTP"
type = "forbidden"
source_modules = ["app.services", "app.crud"]
forbidden_modules = ["fastapi"]
allow_indirect_imports = true  # errors.py y config.py usan FastAPI; lo que se prohíbe es el import directo

[[tool.importlinter.contracts]]
name = "Solo api/deps.py compone repositorios y sesión"
type = "forbidden"
source_modules = ["app.api"]
forbidden_modules = ["app.crud", "app.database"]
allow_indirect_imports = true
ignore_imports = ["app.api.deps -> app.crud.*", "app.api.deps -> app.database"]
```

## Checklist de verificación

- [ ] `uv run lint-imports` cumple los contratos de capas, de "sin HTTP" y de "solo `api/deps.py` compone".
- [ ] `grep -rn "select(\|\.execute(" app/api app/services` no devuelve nada: todo el SQL vive en `crud/`.
- [ ] `grep -rn "commit()" app/crud` no devuelve nada: los commits viven en `services/`. Un service colaborador tampoco commitea.
- [ ] `grep -rn "HTTPException\|from fastapi" app/services app/crud` no devuelve nada.
- [ ] Todo endpoint anota el tipo de retorno con un schema `XRead` (o declara `response_model`).
- [ ] Los schemas de entrada tienen `extra="forbid"` y restricciones explícitas (`Field(gt=..., max_length=...)`).
- [ ] Cada service tiene tests, con el estilo que fija `unit-testing-fastapi-services`: reglas puras como funciones, casos de uso contra la base de test, mocks solo para colaboradores externos.
- [ ] `mypy --strict app` pasa.
- [ ] `/health/live` responde 200 sin base, `/health/ready` ejecuta `SELECT 1` y al apagar la app corren `engine.dispose()` y `shutdown_tracing()`.

## Skills relacionadas

- `configuring-fastapi-settings`, `handling-fastapi-errors`, `configuring-sqlalchemy-sessions`: las piezas transversales.
- `modeling-postgres-with-sqlalchemy`: los `models/`.
- `testing-fastapi-endpoints`, `unit-testing-fastapi-services`: cómo se prueba cada capa.
- `scaffolding-fastapi-backends`: orden de construcción de un proyecto nuevo completo.
