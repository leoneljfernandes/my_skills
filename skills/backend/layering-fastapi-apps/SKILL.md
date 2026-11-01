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
├── api/             # PRESENTACIÓN: routers + deps.py (composición con Depends)
├── schemas/         # CONTRATOS: Pydantic v2 <X>Create / <X>Update / <X>Read
├── services/        # CASOS DE USO: reglas de negocio, transacción, métricas de negocio
├── crud/            # REPOSITORIOS: único lugar con select/insert/update/delete
├── models/          # ORM SQLAlchemy 2.0 (Mapped + mapped_column)
└── observability/   # logging, metrics, tracing
```

| Capa | Responsabilidad | Puede importar | Nunca |
|---|---|---|---|
| `api/` | validar entrada (schema), resolver deps, elegir status code, serializar `XRead` | `services`, `schemas`, `api.deps`, `errors`, `config`, `models` (enums, tipos) | SQL, reglas de negocio, `commit` |
| `services/` | reglas de negocio, orquestar repositorios y otros services, **dueño de la transacción** (`commit`), lanzar `AppError` | `crud`, `models`, `schemas`, `errors`, `config` (`Settings`), otros `services` | `HTTPException`, `Request`, `Response` |
| `crud/` | queries; `add`/`flush`; devolver entidades o `None` | `models` | `commit`, reglas de negocio, `HTTPException` |
| `models/` | tablas, relaciones, constraints | `models.base` | importar de capas superiores |
| `schemas/` | validación I/O, serialización | `models` (solo enums) | lógica, acceso a datos |

**Hacer**

- **Repositorios como clases** que reciben `AsyncSession` por constructor. **Services como clases** que reciben sesión + repositorios (y, si lo necesitan, `Settings` u otros services). Así los tests reemplazan colaboradores sin `patch` de módulos.
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
- `create_app()` como factory: tests y workers pueden construir apps con otros settings.

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

Flujo completo de un caso de uso (código verificado: 17 tests, mypy `--strict`, ruff).

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


class Page[T](BaseModel):
    items: list[T]
    offset: int
    limit: int
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

`app/services/order.py` (caso de uso, dueño de la transacción):

```python
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
```

`app/api/deps.py` (composición) y `app/api/orders.py` (router fino):

```python
# deps.py
def get_order_service(db: DbSession) -> OrderService:
    return OrderService(db, ProductRepository(db), OrderRepository(db))

OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


# orders.py
router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def place_order(data: OrderCreate, service: OrderServiceDep) -> OrderRead:
    # El router solo traduce HTTP ↔ caso de uso. Sin SQL, sin reglas de negocio, sin try/except.
    return OrderRead.model_validate(await service.place_order(data))


@router.get("/{order_id}")
async def get_order(order_id: int, service: OrderServiceDep) -> OrderRead:
    return OrderRead.model_validate(await service.get(order_id))
```

`app/main.py` (factory):

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    app = FastAPI(
        title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan,
        docs_url=None if settings.is_prod else "/docs", redoc_url=None,
    )
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    setup_metrics(app)
    setup_tracing(app, engine, settings)
    app.include_router(api_router, prefix="/api/v1")
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
```

## Checklist de verificación

- [ ] `uv run lint-imports` cumple los contratos de capas y de "sin HTTP".
- [ ] `grep -rn "select(\|\.execute(" app/api app/services` no devuelve nada: todo el SQL vive en `crud/`.
- [ ] `grep -rn "commit()" app/crud` no devuelve nada: los commits viven en `services/`. Un service colaborador tampoco commitea.
- [ ] `grep -rn "HTTPException\|from fastapi" app/services app/crud` no devuelve nada.
- [ ] Todo endpoint anota el tipo de retorno con un schema `XRead` (o declara `response_model`).
- [ ] Los schemas de entrada tienen `extra="forbid"` y restricciones explícitas (`Field(gt=..., max_length=...)`).
- [ ] Cada service tiene tests, con el estilo que fija `unit-testing-fastapi-services`: reglas puras como funciones, casos de uso contra la base de test, mocks solo para colaboradores externos.
- [ ] `mypy --strict app` pasa.

## Skills relacionadas

- `configuring-fastapi-settings`, `handling-fastapi-errors`, `configuring-sqlalchemy-sessions`: las piezas transversales.
- `modeling-postgres-with-sqlalchemy`: los `models/`.
- `testing-fastapi-endpoints`, `unit-testing-fastapi-services`: cómo se prueba cada capa.
- `scaffolding-fastapi-backends`: orden de construcción de un proyecto nuevo completo.
