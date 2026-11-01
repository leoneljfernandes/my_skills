"""Escribe en web/generated/ el código TypeScript publicado en las skills (lo corre `npm test`)."""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import block  # noqa: E402

OUT = Path(__file__).parent / "web" / "generated"
shutil.rmtree(OUT, ignore_errors=True)  # sin restos de una corrida anterior


def write(dest: str, text: str) -> None:
    path = OUT / dest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# `generated/` hace de `src/` (el alias `@/` apunta acá: tsconfig.json y vitest.config.ts).
TARGETS = [
    ("building-axios-clients", "export function toApiError", "lib/http/errors.ts"),
    ("building-axios-clients", "export function createHttpClient", "lib/http/client.ts"),
    ("building-axios-clients", "export function setSessionExpiredHandler", "lib/http/index.ts"),
    ("building-axios-clients", "export const authApi", "features/auth/api.ts"),
    ("building-axios-clients", "export const productsApi", "features/products/api.ts"),
    ("building-axios-clients", "export const ordersApi", "features/orders/api.ts"),
    ("handling-react-errors", "export function setErrorReporter", "lib/telemetry.ts"),
    ("handling-react-errors", "class ErrorBoundary", "components/ErrorBoundary.tsx"),
    ("handling-react-errors", "createRoot(container", "main.tsx"),
    ("using-react-19-actions", "export function expectedActionError", "lib/action-result.ts"),
    ("using-react-19-actions", "export function NameForm", "NameForm.tsx"),
    ("using-react-19-actions", "export function QuickOrderForm", "features/orders/QuickOrderForm.tsx"),
    ("using-react-19-actions", "export function ProductStock", "features/products/ProductStock.tsx"),
    ("routing-with-react-router", "export const router = createBrowserRouter", "router.tsx"),
    ("routing-with-react-router", "export function redirectToLogin", "features/auth/session.ts"),
    ("routing-with-react-router", "authApi.login(email, String", "routes/login.tsx"),
    ("routing-with-react-router", "export async function loader({ params, request }", "routes/product-detail.tsx"),
    ("routing-with-react-router", "export function NewProductForm", "routes/list-forms.tsx"),
    ("routing-with-react-router", "export function NotifyButton", "routes/notify.tsx"),
    ("routing-with-react-router", "export function rethrowAsRouteError", "routes/load-error.ts"),
    ("routing-with-react-router", "export function RouteError", "routes/route-error.tsx"),
    ("routing-with-react-router", "export function RootLayout", "routes/root-layout.tsx"),
    ("architecting-react-apps", "searchProducts(query, { signal: request.signal })", "routes/product-search.ts"),
    ("optimizing-react-renders", "export function AutoSave", "renders.tsx"),
]

for skill, marker, dest in TARGETS:
    try:
        write(dest, block(skill, marker))
    except LookupError as exc:
        (OUT / dest).unlink(missing_ok=True)
        print(f"AVISO: {exc}", file=sys.stderr)


# Funciones sueltas que se prueban solas (sin el resto del bloque que las contiene).
def function_source(skill: str, marker: str, dest: str) -> None:
    text = block(skill, marker)
    start = text.index(marker)
    end = text.index("\n}\n", start) + 3
    write(dest, text[start:end] + "\n")


function_source("routing-with-react-router", "export function safeNext", "safe-next.ts")

# `onRouterError` de main.tsx, solo (main.tsx abre el DOM al importarse y no se puede probar entero).
main_text = block("handling-react-errors", "createRoot(container")
start = main_text.index("const onRouterError")
write(
    "on-router-error.ts",
    'import { isRouteErrorResponse, type ClientOnErrorFunction } from "react-router";\n\n'
    'import { reportError } from "@/lib/telemetry";\n\n'
    + "export "
    + main_text[start : main_text.index("\n};\n", start) + 4]
    + "\n",
)


# Tests que el SKILL.md publica (usan fakeServer/client/auth/memoryTokens de tests/helpers/http.ts).
HEADER = """import { expect, it, vi } from "vitest";

import { ApiRequestError } from "@/lib/http/errors";
import { auth, client, fakeServer, memoryTokens } from "../tests/helpers/http";

"""
published = block("building-axios-clients", 'it("shares ONE refresh across concurrent 401s')
write("http-client.published.test.ts", HEADER + published)


# Módulos de la app que ninguna skill publica entera: los usan el router y los tests como stubs mínimos.
STUBS = {
    "features/auth/index.ts": 'export { authApi, type User } from "./api";\nexport * from "./session";\n',
    "features/products/index.ts": 'export { productsApi, type Product } from "./api";\n',
    "features/orders/index.ts": (
        'export { ordersApi, type Order, type PlaceOrderInput } from "./api";\n'
        'export { QuickOrderForm } from "./QuickOrderForm";\n'
    ),
    "routes/loading.tsx": 'export function Loading() {\n  return <p>Cargando…</p>;\n}\n',
    "routes/products.tsx": 'export function Component() {\n  return <p>products</p>;\n}\n',
    "routes/order-detail.tsx": 'export function Component() {\n  return <p>order-detail</p>;\n}\n',
    "routes/admin.tsx": 'export function Component() {\n  return <p>admin</p>;\n}\n',
}
for dest, text in STUBS.items():
    write(dest, text)

# Hook de búsqueda de architecting-react-apps: el bloque omite los imports de React y de la feature.
ARCH_HEADER = """import { useEffect, useState } from "react";

import { productsApi, type Product } from "@/features/products";
import { isApiRequestError, type ApiError } from "@/lib/http/errors";

"""
write("useProductSearch.tsx", ARCH_HEADER + block("architecting-react-apps", "export function useProductSearch"))

# ESLint de architecting-react-apps: la configuración publicada se prueba con tests/lint.mjs.
write("eslint.config.js", block("architecting-react-apps", "const axiosOnlyInLibHttp"))
