---
name: unit-testing-fastapi-services
description: Use when unit testing business logic in a FastAPI/Python service layer - choosing between a pure-function test, a use case against the test database, and mocks only for external clients (payments, email, HTTP APIs) and infrastructure failures, with unittest.mock or pytest-mock, AsyncMock, create_autospec, patching - or when mocks pass but production breaks, tests are slow because every test hits the DB, or a test asserts on a mock that was never awaited.
domain: testing
tags: [python, pytest, pytest-mock, unittest-mock, unit-testing, fastapi, mocking]
triggers: [pytest-mock, mocker, unittest.mock, AsyncMock, MagicMock, create_autospec, "mock.patch", "assert_awaited", "tests unitarios", "unit tests", mock, stub, "test doubles"]
---

# Tests unitarios de services con mocks

Un test unitario verifica **una regla de negocio** del service en milisegundos: sin red y, si la regla es una función pura, sin base. Los colaboradores que no se pueden usar de verdad (clientes externos, fallos de infraestructura) se reemplazan por dobles con la **misma firma** que los reales; los repositorios y la sesión no se mockean.

## Contexto y reglas

**Elegir el estilo de test, en este orden**

1. **La regla es una función pura** (calcular ocupación, decidir si un estado puede pasar a otro): extraerla como función y testearla directo, sin mocks ni base. Es el test más barato y el que más se rompe cuando la regla cambia.
2. **El caso de uso toca la base** (valida, escribe, commitea): testearlo contra la base de test con `testing-fastapi-endpoints` (SQLite o PostgreSQL), sin mocks de repositorios. Un mock de repositorio comprueba que el service llama al mock, no que la query funciona.
3. **Mocks**, solo para: clientes externos (pagos, email, APIs HTTP), el reloj y fallos de infraestructura (`commit` que explota). Si el constructor del service recibe más de 4 colaboradores, mockearlos todos prueba poco: usar el estilo 2.

El resto de esta skill muestra los estilos 2 y 3 sin errores. Los tests son `async`: requieren `pytest-asyncio` con `asyncio_mode = "auto"` (ver `testing-fastapi-endpoints`), y los del estilo 2 usan sus fixtures (`db_session`, `new_session`).

**Hacer**

- Testear **services**, no routers ni repositorios. Los routers se cubren con integración; los repositorios, contra una base real. La carpeta `tests/unit/` aloja los tres estilos mientras no necesiten HTTP.
- Inyección por constructor (ver `layering-fastapi-apps`): el test construye `OrderService(db_session, ProductRepository(db_session), OrderRepository(db_session))`, o `CheckoutService(db_session, gateway)` con el cliente externo doblado. Sin `patch` de módulos.
- **Un caso de uso que commitea se ejecuta con su propia sesión** (`new_session()`), cerrada antes de mirar el resultado con `db_session`: como en una request, lo que quedó sin `commit` se descarta al cerrar. Con la misma sesión que mira el test, un `flush` en lugar de `commit` pasaría en verde.
- **`create_autospec(Clase, instance=True)`** para los clientes externos: los métodos `async def` quedan como `AsyncMock`, las firmas se validan (`TypeError`) y un método inexistente lanza `AttributeError`. `AsyncMock(spec=Clase)` no valida firmas.
- **Fallo de infraestructura** sobre la sesión real: `mocker.patch.object(db_session, "commit", side_effect=RuntimeError(...))`. La sesión no se reemplaza por un mock.
- Estructura **Arrange / Act / Assert**, un comportamiento por test, nombre que describe la regla: `test_place_order_rejects_insufficient_stock_without_side_effects`.
- Verificar **resultado + efectos laterales**: valor devuelto, estado persistido (leído con `db_session`), qué se llamó en los dobles y, sobre todo, qué **no** pasó cuando falla una regla (stock intacto, ninguna orden, el cliente externo sin awaitear).
- Datos de entrada con `create_product(db_session, ...)` (helper de `testing-fastapi-endpoints`). Para una regla pura, entidades transitorias (`Product(id=7, stock=5, ...)`): son objetos Python, no necesitan sesión.
- `@pytest.mark.parametrize` para las variantes de una misma regla.
- Probar la propagación de fallos de infraestructura con el `patch.object` de arriba.
- `mocker.patch("app.services.x.dependency")` solo para lo que no se puede inyectar (reloj, `uuid4`), parcheando **donde se usa**, no donde se define.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `MagicMock()` sin `spec` | acepta `repo.get_by_emial(...)`: el test pasa y prod rompe | `create_autospec(..., instance=True)` |
| `Mock` para métodos `async` | `await mock()` falla, o el test no espera nada | autospec / `AsyncMock` |
| `assert_called_once()` sobre un `AsyncMock` | pasa aunque la corrutina nunca se haya awaiteado | `assert_awaited_once()` |
| Mockear lo que se está probando | test tautológico | mockear solo colaboradores externos |
| Verificar cada llamada interna | test frágil ante refactors sin cambio de comportamiento | verificar resultado + efectos relevantes |
| `patch("modulo_origen.func")` cuando el service hizo `from modulo import func` | el patch no tiene efecto | parchear `app.services.x.func` |
| Mockear repositorios o la sesión en un caso de uso que escribe | prueba que el service llama al mock, no que la query ni el `commit` funcionan | `db_session` (estilo 2) |

## Ejemplos

`tests/unit/test_order_service.py` (verificado (test): pytest + mypy `--strict`; la mutación `commit` → `flush` en `place_order` lo pone en rojo):

```python
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.order import OrderRepository
from app.crud.product import ProductRepository
from app.errors import NotFoundError
from app.models import Order, OrderStatus
from app.schemas.order import OrderCreate
from app.services.order import InsufficientStockError, OrderService
from tests.factories import create_product


def _order_service(session: AsyncSession) -> OrderService:
    return OrderService(session, ProductRepository(session), OrderRepository(session))


def _order_data(product_id: int, quantity: int = 2) -> OrderCreate:
    return OrderCreate(customer_email="ana@example.com", product_id=product_id, quantity=quantity)


async def _count_orders(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(Order))).scalar_one()


# --- Estilo 2: el caso de uso contra la base de test, sin mocks de repositorios ---------------------


async def test_place_order_decrements_stock_and_commits(
    db_session: AsyncSession, new_session: Callable[[], AsyncSession]
) -> None:
    product = await create_product(db_session, stock=5, price=Decimal("12.50"))

    async with new_session() as use_case_session:  # sesión propia, como la de una request
        order = await _order_service(use_case_session).place_order(_order_data(product.id))
    # Cerrada la sesión del caso de uso, lo no commiteado ya se descartó: acá se ve si hubo commit.

    assert order.total == Decimal("25.00")
    await db_session.refresh(product)
    assert product.stock == 3
    assert await _count_orders(db_session) == 1


async def test_place_order_rejects_insufficient_stock_without_side_effects(db_session: AsyncSession) -> None:
    product = await create_product(db_session, stock=1)

    with pytest.raises(InsufficientStockError) as exc_info:
        await _order_service(db_session).place_order(_order_data(product.id, quantity=2))

    assert exc_info.value.extra == {"available": 1, "requested": 2}
    assert product.stock == 1
    assert await _count_orders(db_session) == 0


async def test_place_order_unknown_product_is_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await _order_service(db_session).place_order(_order_data(product_id=999_999))

    assert await _count_orders(db_session) == 0


async def test_place_order_inactive_product_is_not_found(db_session: AsyncSession) -> None:
    product = await create_product(db_session, stock=99, is_active=False)

    with pytest.raises(NotFoundError):
        await _order_service(db_session).place_order(_order_data(product.id))

    assert product.stock == 99
    assert await _count_orders(db_session) == 0


# --- Estilo 3: fallo de infraestructura sobre la sesión real ----------------------------------------


async def test_place_order_propagates_commit_failure(db_session: AsyncSession, mocker: MockerFixture) -> None:
    product = await create_product(db_session, stock=5)
    mocker.patch.object(db_session, "commit", side_effect=RuntimeError("connection lost"))

    with pytest.raises(RuntimeError, match="connection lost"):
        await _order_service(db_session).place_order(_order_data(product.id))


# --- Estilo 3: cliente externo doblado con autospec --------------------------------------------------


class PaymentGateway(Protocol):
    async def charge(self, *, amount: Decimal, idempotency_key: str) -> str: ...


class PaymentDeclinedError(Exception):
    pass


class CheckoutService:  # mínimo, para el ejemplo; en un proyecto vive en app/services/
    def __init__(self, session: AsyncSession, gateway: PaymentGateway) -> None:
        self._session = session
        self._gateway = gateway

    async def pay(self, order: Order) -> Order:
        try:
            await self._gateway.charge(amount=order.total, idempotency_key=f"order-{order.id}")
            order.status = OrderStatus.PAID
        except PaymentDeclinedError:
            order.status = OrderStatus.CANCELLED
        await self._session.commit()
        return order


@pytest.fixture
def gateway(mocker: MockerFixture) -> MagicMock:
    # autospec: firma real; el método async queda como AsyncMock; un typo o un argumento de más es error.
    return mocker.create_autospec(PaymentGateway, instance=True)


async def test_payment_declined_cancels_the_order(db_session: AsyncSession, gateway: MagicMock) -> None:
    product = await create_product(db_session, stock=5)
    order = Order(customer_email="ana@example.com", product_id=product.id, quantity=2, total=Decimal("25.00"))
    db_session.add(order)
    await db_session.flush()
    gateway.charge.side_effect = PaymentDeclinedError("insufficient funds")

    await CheckoutService(db_session, gateway).pay(order)

    assert order.status == OrderStatus.CANCELLED
    gateway.charge.assert_awaited_once_with(amount=Decimal("25.00"), idempotency_key=f"order-{order.id}")


def test_autospec_rejects_a_wrong_signature(gateway: MagicMock) -> None:
    with pytest.raises(TypeError):
        gateway.charge(amout=Decimal("1"), wrong=2)  # con AsyncMock(spec=...) esto se aceptaría
    with pytest.raises(AttributeError):
        gateway.refund  # método inexistente
```

## Checklist de verificación

- [ ] Cada regla de negocio del service tiene al menos un test de éxito y uno de rechazo.
- [ ] Los tests de rechazo verifican que **no** hubo escrituras: estado intacto leído de la base y, en los dobles, `assert_not_awaited` / `assert_not_called`.
- [ ] Todos los dobles usan autospec; `grep -rn "MagicMock()" tests/unit` no devuelve nada, y `grep -rn "create_autospec(.*Repository" tests/unit` tampoco.
- [ ] Cada caso de uso que commitea tiene un test con sesión propia (`new_session()`) que falla si el `commit` pasa a `flush`.
- [ ] Ninguna aserción usa `assert_called*` sobre métodos async: se usa `assert_awaited*`.
- [ ] Cada regla nueva tiene el test de su estilo: función pura → test directo; caso de uso con base → base de test; cliente externo → `create_autospec`.
- [ ] `tests/unit` corre en pocos segundos, sin red ni Docker (SQLite en memoria alcanza) y con `asyncio_mode = "auto"` configurado.
- [ ] `mypy --strict tests/unit` pasa.

## Skills relacionadas

- `testing-fastapi-endpoints`: integración con base real y los fixtures `db_session` / `new_session`.
- `layering-fastapi-apps`: la inyección por constructor que vuelve esto posible.
