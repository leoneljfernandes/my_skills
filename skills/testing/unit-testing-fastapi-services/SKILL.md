---
name: unit-testing-fastapi-services
description: Use when unit testing business logic in a FastAPI/Python service layer without a database or network - mocking repositories, AsyncSession, external clients (payments, email, HTTP APIs) with unittest.mock or pytest-mock, AsyncMock, create_autospec, patching - or when mocks pass but production breaks, tests are slow because every test hits the DB, or a test asserts on a mock that was never awaited.
domain: testing
tags: [python, pytest, pytest-mock, unittest-mock, unit-testing, fastapi, mocking]
triggers: [pytest-mock, mocker, unittest.mock, AsyncMock, MagicMock, create_autospec, "mock.patch", "assert_awaited", "tests unitarios", "unit tests", mock, stub, "test doubles"]
---

# Tests unitarios de services con mocks

Un test unitario verifica **una regla de negocio** del service en milisegundos. Los colaboradores que no se pueden usar de verdad (clientes externos, fallos de infraestructura) se reemplazan por dobles con la **misma firma** que los reales.

## Contexto y reglas

**Elegir el estilo de test, en este orden**

1. **La regla es una función pura** (calcular ocupación, decidir si un estado puede pasar a otro): extraerla como función y testearla directo, sin mocks ni base. Es el test más barato y el que más se rompe cuando la regla cambia.
2. **El caso de uso toca la base** (valida, escribe, commitea): testearlo contra la base de test con `testing-fastapi-endpoints` (SQLite o PostgreSQL), sin mocks de repositorios. Un mock de repositorio comprueba que el service llama al mock, no que la query funciona.
3. **Mocks**, solo para: clientes externos (pagos, email, APIs HTTP), el reloj y fallos de infraestructura (`commit` que explota). Si el constructor del service recibe más de 4 colaboradores, mockearlos todos prueba poco: usar el estilo 2.

El resto de esta skill describe cómo escribir el estilo 3 sin errores.

**Hacer (cuando se usan mocks)**

- Testear **services**, no routers ni repositorios. Los routers se cubren con integración; los repositorios, contra una base real. La carpeta `tests/unit/` aloja los tres estilos mientras no necesiten HTTP.
- Inyección por constructor (ver `layering-fastapi-apps`): el test construye `OrderService(session_mock, products_mock, orders_mock)`. Sin `patch` de módulos.
- **`create_autospec(Clase, instance=True)`** para repositorios y clientes: los métodos `async def` quedan como `AsyncMock`, las firmas se validan y un método inexistente lanza `AttributeError`.
- **`mocker.AsyncMock(spec=AsyncSession)`** para la sesión: verificar `commit` con `assert_awaited_once()` / `assert_not_awaited()`.
- Estructura **Arrange / Act / Assert**, un comportamiento por test, nombre que describe la regla: `test_place_order_rejects_insufficient_stock_without_side_effects`.
- Verificar **resultado + efectos laterales**: valor devuelto, estado mutado, qué se llamó y, sobre todo, qué **no** se llamó (sin commit cuando falla una regla).
- Entidades ORM transitorias (`Product(id=7, stock=5, ...)`) como datos de entrada: son objetos Python, no necesitan sesión.
- `@pytest.mark.parametrize` para las variantes de una misma regla.
- Probar la propagación de fallos de infraestructura: `session.commit.side_effect = RuntimeError(...)`.
- `mocker.patch("app.services.x.dependency")` solo para lo que no se puede inyectar (reloj, `uuid4`), parcheando **donde se usa**, no donde se define.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `MagicMock()` sin `spec` | acepta `repo.get_by_emial(...)`: el test pasa y prod rompe | `create_autospec(..., instance=True)` |
| `Mock` para métodos `async` | `await mock()` falla, o el test no espera nada | autospec / `AsyncMock` |
| `assert_called_once()` sobre un `AsyncMock` | pasa aunque la corrutina nunca se haya awaiteado | `assert_awaited_once()` |
| Mockear lo que se está probando | test tautológico | mockear solo colaboradores |
| Verificar cada llamada interna | test frágil ante refactors sin cambio de comportamiento | verificar resultado + efectos relevantes |
| `patch("modulo_origen.func")` cuando el service hizo `from modulo import func` | el patch no tiene efecto | parchear `app.services.x.func` |
| Mocks para el SQL del repositorio | prueba el mock, no la query | test de integración del repositorio |

## Ejemplos

`tests/unit/test_order_service.py` (verificado: pytest + mypy `--strict`):

```python
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.order import OrderRepository
from app.crud.product import ProductRepository
from app.errors import NotFoundError
from app.models import Order, Product
from app.schemas.order import OrderCreate
from app.services.order import InsufficientStockError, OrderService


@pytest.fixture
def session(mocker: MockerFixture) -> AsyncMock:
    mock: AsyncMock = mocker.AsyncMock(spec=AsyncSession)
    return mock


@pytest.fixture
def products(mocker: MockerFixture) -> MagicMock:
    # autospec: el mock tiene la firma real; métodos async → AsyncMock; un typo es AttributeError.
    return mocker.create_autospec(ProductRepository, instance=True)


@pytest.fixture
def orders(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(OrderRepository, instance=True)


@pytest.fixture
def service(session: AsyncMock, products: MagicMock, orders: MagicMock) -> OrderService:
    return OrderService(session, products, orders)


def _product(*, stock: int, price: str = "10.00", active: bool = True) -> Product:
    return Product(id=7, sku="SKU-1", name="Mug", price=Decimal(price), stock=stock, is_active=active)


def _order_data(quantity: int = 2) -> OrderCreate:
    return OrderCreate(customer_email="ana@example.com", product_id=7, quantity=quantity)


async def test_place_order_decrements_stock_and_commits(
    service: OrderService, session: AsyncMock, products: MagicMock, orders: MagicMock
) -> None:
    product = _product(stock=5, price="12.50")
    products.get_for_update.return_value = product

    order = await service.place_order(_order_data(quantity=2))

    assert product.stock == 3
    assert order.total == Decimal("25.00")
    products.get_for_update.assert_awaited_once_with(7)
    orders.add.assert_called_once()
    assert isinstance(orders.add.call_args.args[0], Order)
    session.commit.assert_awaited_once()


async def test_place_order_rejects_insufficient_stock_without_side_effects(
    service: OrderService, session: AsyncMock, products: MagicMock, orders: MagicMock
) -> None:
    products.get_for_update.return_value = _product(stock=1)

    with pytest.raises(InsufficientStockError) as exc_info:
        await service.place_order(_order_data(quantity=2))

    assert exc_info.value.extra == {"available": 1, "requested": 2}
    orders.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("product", [None, _product(stock=99, active=False)])
async def test_place_order_unknown_or_inactive_product_is_not_found(
    service: OrderService, session: AsyncMock, products: MagicMock, product: Product | None
) -> None:
    products.get_for_update.return_value = product

    with pytest.raises(NotFoundError):
        await service.place_order(_order_data())

    session.commit.assert_not_awaited()


async def test_place_order_propagates_commit_failure(
    service: OrderService, session: AsyncMock, products: MagicMock
) -> None:
    products.get_for_update.return_value = _product(stock=5)
    session.commit.side_effect = RuntimeError("connection lost")

    with pytest.raises(RuntimeError, match="connection lost"):
        await service.place_order(_order_data())
```

Colaborador externo definido como `Protocol` e inyectado:

```python
class PaymentGateway(Protocol):
    async def charge(self, *, amount: Decimal, idempotency_key: str) -> str: ...


async def test_payment_declined_marks_order_failed(mocker: MockerFixture) -> None:
    gateway = mocker.AsyncMock(spec=PaymentGateway)
    gateway.charge.side_effect = PaymentDeclinedError("insufficient funds")
    ...
    gateway.charge.assert_awaited_once_with(amount=Decimal("25.00"), idempotency_key=mocker.ANY)
```

## Checklist de verificación

- [ ] Cada regla de negocio del service tiene al menos un test de éxito y uno de rechazo.
- [ ] Los tests de rechazo verifican que **no** hubo commit ni escrituras (`assert_not_awaited`, `assert_not_called`).
- [ ] Todos los dobles usan `spec`/autospec; `grep -rn "MagicMock()" tests/unit` no devuelve nada.
- [ ] Ninguna aserción usa `assert_called*` sobre métodos async: se usa `assert_awaited*`.
- [ ] Cada regla nueva tiene el test de su estilo: función pura → test directo; caso de uso con base → base de test; cliente externo → mock con autospec.
- [ ] `tests/unit` corre en pocos segundos, sin red ni Docker (SQLite en memoria alcanza).
- [ ] `mypy --strict tests/unit` pasa.

## Skills relacionadas

- `testing-fastapi-endpoints`: integración con base real.
- `layering-fastapi-apps`: la inyección por constructor que vuelve esto posible.
