"""Arma el proyecto de referencia desde los bloques de las SKILL.md (no desde copias).

Uso: python build_ref.py [destino]   (por defecto: ./project, ignorado por git)

Lo único escrito a mano es el pegamento que las skills no publican (los __init__.py, el span
manual de OrderService y lo marcado GLUE). Todo lo demás es el bloque publicado, así que un
arreglo en la skill cambia lo que corre este proyecto.
"""

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from extract import block  # noqa: E402

P = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "project"
for sub in ("app", "tests"):
    shutil.rmtree(P / sub, ignore_errors=True)


def w(rel: str, txt: str) -> None:
    (P / rel).parent.mkdir(parents=True, exist_ok=True)
    (P / rel).write_text(txt, encoding="utf-8")


# Sin tests/__init__.py, como el bootstrap de scaffolding: mypy lo resuelve con mypy_path + explicit_package_bases.
w('app/__init__.py','')
for d in 'api crud schemas services observability'.split(): w(f'app/{d}/__init__.py','')
w('app/config.py',block('configuring-fastapi-settings','class Settings(BaseSettings)'))
w('app/database.py',block('configuring-sqlalchemy-sessions','def build_engine'))
w('app/workers.py',block('configuring-sqlalchemy-sessions','async def expire_pending_orders'))  # DB-14: mypy --strict
w('app/errors.py',block('handling-fastapi-errors','class AppError'))
w('app/observability/tracing.py',block('tracing-with-opentelemetry','def setup_tracing'))
w('app/observability/logging.py',block('logging-json-to-loki','class JsonFormatter'))
w('app/observability/metrics.py',block('exposing-prometheus-metrics','ORDERS_CREATED = Counter'))
w('app/models/base.py',block('modeling-postgres-with-sqlalchemy','class UtcDateTime'))
# El bloque de entidades trae Product, OrderStatus y Order juntos; las skills dicen un módulo por
# entidad (product.py, order.py) y el __init__ publicado las re-exporta (DB-10).
ent=block('modeling-postgres-with-sqlalchemy','class Product(TimestampMixin')
product_src, order_src = ent.split('class OrderStatus(StrEnum):')
w('app/models/product.py','''from decimal import Decimal
from sqlalchemy import CheckConstraint, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, BigIntPK, TimestampMixin
'''+product_src)
w('app/models/order.py','''from decimal import Decimal
from enum import StrEnum
from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, BigIntPK, TimestampMixin
from app.models.product import Product
'''+'class OrderStatus(StrEnum):'+order_src)
w('app/models/__init__.py',block('modeling-postgres-with-sqlalchemy','from app.models.base import Base, BigIntPK'))
w('app/schemas/order.py',block('layering-fastapi-apps','class OrderCreate'))
w('app/schemas/common.py',block('layering-fastapi-apps','class Page[T](BaseModel)'))
w('app/schemas/product.py',block('layering-fastapi-apps','class ProductCreate(BaseModel)'))
w('app/crud/product.py',block('layering-fastapi-apps','class ProductRepository'))
# El método `expire_pending` del worker (configuring-sqlalchemy-sessions) se publica aparte: su bloque trae el
# encabezado de imports completo del módulo, que reemplaza al de layering, y el método va dentro de la clase.
_exp_imports, _exp_method = block('configuring-sqlalchemy-sessions','async def expire_pending(self').split('async def expire_pending(self')
w('app/crud/order.py',_exp_imports+'class OrderRepository'+block('layering-fastapi-apps','class OrderRepository').split('class OrderRepository',1)[1]
  +'\n'+"".join("    "+l if l.strip() else l for l in ('async def expire_pending(self'+_exp_method).splitlines(keepends=True)))
w('app/crud/health.py',block('layering-fastapi-apps','class HealthRepository'))
svc=block('layering-fastapi-apps','class OrderService')
# GLUE (ola 5, OB-09): el service publicado no abre el span manual que tracing-with-opentelemetry muestra en
# "Span manual en un caso de uso" (con `...` en el medio). Se envuelve place_order igual que ahí.
_head, _rest = svc.split("    async def place_order(self, data: OrderCreate) -> Order:\n")
_body, _tail = _rest.split("    async def get(", 1)
_body = "".join("    " + l if l.strip() else l for l in _body.splitlines(keepends=True))
_body = _body.replace("        return order\n", '        span.set_attribute("order.id", order.id)\n        return order\n')
svc = (_head + "    async def place_order(self, data: OrderCreate) -> Order:\n"
       '        with tracer.start_as_current_span(\n            "order.place",\n'
       '            attributes={"order.product_id": data.product_id, "order.quantity": data.quantity},\n'
       "        ) as span:\n" + _body.rstrip("\n") + "\n\n    async def get(" + _tail)
assert "\n\n\nclass InsufficientStockError" in svc  # C2: el error del caso de uso vive en el bloque publicado
svc = "from opentelemetry import trace\n" + svc.replace(
    "\n\n\nclass InsufficientStockError", "\n\ntracer = trace.get_tracer(__name__)\n\n\nclass InsufficientStockError", 1)
w('app/services/order.py',svc)
w('app/services/product.py',block('layering-fastapi-apps','class ProductService'))
w('app/api/deps.py',block('layering-fastapi-apps','def get_order_service'))
w('app/api/orders.py',block('layering-fastapi-apps','router = APIRouter(prefix="/orders"'))
w('app/api/products.py',block('layering-fastapi-apps','router = APIRouter(prefix="/products"'))
w('app/api/health.py',block('layering-fastapi-apps','prefix="/health"'))
w('app/api/router.py',block('layering-fastapi-apps','api_router = APIRouter()'))
w('app/main.py',block('layering-fastapi-apps','def create_app'))

# ---- auth (security.md): bloques publicados + pegamento mínimo (imports, TokenRead, ruta de admin) ------
SEC = dict(file="references/security.md")
w('app/security.py', block('scaffolding-fastapi-backends', 'ALGORITHM = "HS256"', **SEC))
w('app/models/auth.py', block('scaffolding-fastapi-backends', 'class Role(Base)', **SEC))
w('app/models/__init__.py', (P / 'app/models/__init__.py').read_text() + "from app.models.auth import Permission, Role, Session, User\n__all__ += [\"Permission\", \"Role\", \"Session\", \"User\"]\n")
w('app/crud/auth.py', """from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Session, User


""" + block('scaffolding-fastapi-backends', 'class UserRepository', **SEC))
w('app/services/auth.py', """import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.crud.auth import SessionRepository, UserRepository
from app.errors import InvalidCredentialsError, NotAuthenticatedError, SessionRotatedError
from app.models import Session, User
from app.security import (
    DUMMY_HASH,
    create_access_token,
    decode_access_token,
    hash_token,
    new_refresh_token,
    verify_password,
)


""" + block('scaffolding-fastapi-backends', 'REUSE_GRACE = timedelta', **SEC))
w('app/schemas/auth.py', "from pydantic import BaseModel\n\n\nclass TokenRead(BaseModel):  # GLUE\n    access_token: str\n    token_type: str = 'bearer'\n")
w('app/api/auth.py', """from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from app.api.deps import AuthServiceDep, CurrentUser
from app.config import Settings, SettingsDep
from app.errors import NotAuthenticatedError
from app.schemas.auth import TokenRead

router = APIRouter(prefix="/auth", tags=["auth"])


""" + block('scaffolding-fastapi-backends', 'REFRESH_COOKIE = "refresh_token"', **SEC))
w('app/api/admin.py', """from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.models import Permission, User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/report")  # GLUE: un endpoint que exige un permiso
async def report(user: Annotated[User, Depends(require_permission(Permission.ADMIN_REPORT))]) -> dict[str, str]:
    return {"user": user.email}
""")
deps = (P / 'app/api/deps.py').read_text()
w('app/api/deps.py', deps + """
from collections.abc import Awaitable, Callable  # noqa: E402

from fastapi.security import OAuth2PasswordBearer  # noqa: E402

from app.config import SettingsDep  # noqa: E402
from app.crud.auth import SessionRepository, UserRepository  # noqa: E402
from app.errors import PermissionDeniedError  # noqa: E402
from app.models import Permission, User  # noqa: E402
from app.services.auth import AuthService  # noqa: E402


""" + block('scaffolding-fastapi-backends', 'oauth2_scheme = OAuth2PasswordBearer', **SEC).replace('# api/deps.py\n', ''))
w('app/api/router.py', (P / 'app/api/router.py').read_text().replace('from app.api import orders, products', 'from app.api import admin, auth, orders, products') + 'api_router.include_router(auth.router)\napi_router.include_router(admin.router)\n')

# ---- tests, verbatim
w('tests/conftest.py',block('testing-fastapi-endpoints','def _sqlite_memory_engine'))
w('tests/factories.py',block('testing-fastapi-endpoints','async def create_product'))
w('tests/test_endpoints.py',block('testing-fastapi-endpoints','test_place_order_decrements_stock'))
# TS-06: polyfactory es opcional (regla de testing); solo va a los proyectos que lo declaran (la referencia sí).
if any("polyfactory" in f.read_text() for f in (P / "pyproject.toml", P.parent / "pyproject.toml") if f.exists()):
    w('tests/test_product_factory.py',block('testing-fastapi-endpoints','class ProductFactory'))
conc=block('testing-fastapi-endpoints','test_two_orders_for_last_unit_one_wins')
w('tests/test_concurrency.py','''import asyncio, os
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from app.crud.order import OrderRepository
from app.crud.product import ProductRepository
from app.models import Order, Product
from app.schemas.order import OrderCreate
from app.services.order import InsufficientStockError, OrderService
from tests.factories import create_product

'''+conc)
w('tests/unit/test_order_service.py',block('unit-testing-fastapi-services','test_place_order_decrements_stock_and_commits'))
# Test de tracing publicado, con los imports que el bloque no trae (el bloque no es un archivo completo).
w('tests/test_tracing.py','''from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.main import app
from tests.factories import create_product

'''+block('tracing-with-opentelemetry','test_place_order_emits_manual_span_with_sql_children'))

# ---- tests de las olas (viven en waveN_tests/, se copian al proyecto) ------------------------------
for t in sorted(HERE.glob("wave[0-9]_tests/test_wave[0-9]_*.py")):
    w(f"tests/{t.name}", t.read_text(encoding="utf-8"))
