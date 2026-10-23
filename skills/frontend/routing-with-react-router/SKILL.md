---
name: routing-with-react-router
description: Use when adding or restructuring routes in a React SPA with React Router (data mode) - createBrowserRouter, loaders, actions, Form, nested layouts with Outlet, protected/authenticated routes, role-based access, middleware, lazy routes and code-splitting, route error boundaries, pending UI - or when migrating from react-router-dom or v6/v7, data is fetched in useEffect per page, or auth checks are duplicated in every component.
domain: frontend
tags: [react, react-router, routing, loaders, actions, code-splitting, auth, typescript]
triggers: [react-router, react-router-dom, createBrowserRouter, RouterProvider, loader, action, useLoaderData, Outlet, "rutas protegidas", "protected routes", middleware, lazy, "code splitting", useNavigation, useRouteError, "nested routes"]
---

# React Router (data mode): rutas, datos y protección

El router es la **capa de datos de página**: cada ruta declara qué necesita (`loader`), cómo muta (`action`), quién puede entrar (`middleware`), qué muestra si falla (`ErrorBoundary`) y qué código carga (`lazy`). Los componentes de ruta solo pintan.

> **Versión**: React Router **v8** (actual) eliminó el paquete `react-router-dom`. Todo se importa de `react-router`, salvo `RouterProvider`/`HydratedRouter`, que vienen de `react-router/dom`. En v7 `react-router-dom` era solo un re-export. Para migrar: reemplazar los imports y quitar el flag `future.v8_middleware` (en v8 el middleware siempre está activo). Requiere React ≥ 19.2.7 y Node ≥ 22.22.

## Contexto y reglas

**Hacer**

- `createBrowserRouter([...])` con route objects, en `src/router.tsx`. `<RouterProvider router={router} onError={...} />` en `main.tsx`.
- **Nested layouts**: la ruta padre renderiza `<Outlet />` (nav, sidebar, indicador global con `useNavigation()`). Las hijas heredan el layout.
- **Loaders** para los datos de página: reciben `request.signal` (cancela la request HTTP al navegar) y `params`. Validar `params` y lanzar `data(..., { status: 404 })` si son inválidos.
- **Actions** + `<Form method="post">` para mutaciones de página: después de una action, el router **revalida** los loaders y la UI se actualiza sola. Errores esperables (422) se devuelven como datos (`useActionData`); los inesperados se lanzan.
- **Rutas protegidas con `middleware`** sobre una ruta *pathless* que agrupa todo lo privado. El middleware corre **antes** de cualquier loader/action hijo: sin usuario → `throw redirect("/login?next=...")`. Pone el usuario en un `createContext` tipado que loaders y actions leen con `context.get(...)`.
- **Roles**: middleware adicional en la rama (`requireRole("admin")`).
- **Code-splitting**: `lazy: () => import("./routes/x")`. El módulo exporta `loader`, `action`, `Component`, `ErrorBoundary`, y Vite genera un chunk por ruta.
- **ErrorBoundary por rama** con `useRouteError()` + `isRouteErrorResponse()`: distingue 404/403 (respuestas de ruta) de errores inesperados.
- Un helper `rethrowAsRouteError` convierte `ApiRequestError` esperables (404, 403) en respuestas de ruta. El resto se relanza (→ boundary + telemetría).
- Pending UI con `useNavigation().state` (`idle | loading | submitting`), no con estados locales.
- Tipar `useLoaderData<typeof loader>()` y `useActionData<typeof action>()`.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `useEffect(() => fetch(...))` en cada página | cascadas de requests, spinners anidados, race conditions | `loader` (corre en paralelo con la carga del chunk) |
| `if (!user) return <Navigate/>` en cada componente | duplicado; los loaders ya se ejecutaron y pidieron datos sin auth | `middleware` en una ruta pathless |
| Rutas importadas estáticamente | bundle inicial gigante | `lazy` por ruta |
| `import ... from "react-router-dom"` en v8 | el paquete no existe | `react-router` y `react-router/dom` |
| Ignorar `request.signal` | requests huérfanas que pisan datos al volver | `{ signal: request.signal }` |
| Una sola ErrorBoundary en la raíz | un 404 de un detalle tira el layout entero | boundary por rama |
| Mutar con `fetch` + `navigate` manual | sin revalidación, estado viejo en pantalla | `action` + `<Form>` / `useFetcher` |

## Ejemplos

`src/router.tsx` (verificado: `tsc --strict` y `vite build`, que genera un chunk por ruta lazy):

```tsx
import { createBrowserRouter } from "react-router";

import { requireRole, requireUser } from "./auth";
import { RootLayout } from "./routes/root-layout";
import { RouteError } from "./routes/route-error";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: RootLayout,
    ErrorBoundary: RouteError, // última red de la app; cada rama puede tener la suya
    children: [
      { index: true, lazy: () => import("./routes/products") },
      { path: "login", lazy: () => import("./routes/login") },
      {
        // Ruta "pathless": agrupa todo lo protegido bajo un único middleware.
        middleware: [requireUser],
        children: [
          {
            path: "products",
            children: [
              { index: true, lazy: () => import("./routes/products") },
              {
                path: ":productId",
                lazy: () => import("./routes/product-detail"), // chunk propio (code-splitting)
                ErrorBoundary: RouteError,
              },
            ],
          },
          {
            path: "admin",
            middleware: [requireRole("admin")],
            lazy: () => import("./routes/admin"),
          },
        ],
      },
    ],
  },
]);
```

`src/auth.ts` (middleware + contexto tipado):

```ts
import { createContext, redirect, type MiddlewareFunction } from "react-router";

import { http } from "./lib/http";
import { isApiRequestError } from "./lib/http/errors";

export interface User {
  id: number;
  email: string;
  roles: ReadonlyArray<"admin" | "customer">;
}

/** Contexto tipado del router: los loaders/actions protegidos leen el usuario de acá. */
export const userContext = createContext<User | null>(null);

async function fetchCurrentUser(): Promise<User | null> {
  try {
    const { data } = await http.get<User>("/auth/me"); // el interceptor hace refresh si hace falta
    return data;
  } catch (error) {
    if (isApiRequestError(error) && error.error.kind === "unauthorized") return null;
    throw error;
  }
}

/** Protege TODA la rama de rutas hija: corre antes que cualquier loader/action. */
export const requireUser: MiddlewareFunction = async ({ request, context }) => {
  const user = await fetchCurrentUser();
  if (!user) {
    const next = new URL(request.url).pathname;
    throw redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  context.set(userContext, user);
};

export function requireRole(role: User["roles"][number]): MiddlewareFunction {
  return ({ context }) => {
    const user = context.get(userContext);
    if (!user?.roles.includes(role)) throw redirect("/forbidden");
  };
}
```

Módulo de ruta lazy con loader + action + Form (`src/routes/product-detail.tsx`):

```tsx
import { useState, type ReactNode } from "react";
import {
  Form, data, redirect, useActionData, useLoaderData, useNavigation,
  type ActionFunctionArgs, type LoaderFunctionArgs,
} from "react-router";

import { userContext } from "../auth";
import { ordersApi } from "../features/orders/api";
import { isApiRequestError } from "../lib/http/errors";
import { rethrowAsRouteError } from "./load-error";

function parseId(raw: string | undefined): number {
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0) throw data("Id inválido", { status: 404 });
  return id;
}

export async function loader({ params, request }: LoaderFunctionArgs) {
  try {
    return await ordersApi.getProduct(parseId(params.productId), { signal: request.signal });
  } catch (error) {
    rethrowAsRouteError(error);
  }
}

export async function action({ params, request, context }: ActionFunctionArgs) {
  const user = context.get(userContext); // garantizado por el middleware requireUser
  const form = await request.formData();
  const quantity = Number(form.get("quantity"));
  if (!Number.isInteger(quantity) || quantity < 1) {
    return { fieldErrors: { quantity: "Cantidad inválida" } };
  }
  try {
    const order = await ordersApi.placeOrder(
      { customer_email: user?.email ?? "", product_id: parseId(params.productId), quantity },
      String(form.get("idempotencyKey")),
    );
    return redirect(`/orders/${order.id}`);
  } catch (error) {
    // 422 = error esperable: se muestra en el form. Cualquier otro sube a la ErrorBoundary.
    if (isApiRequestError(error) && error.error.kind === "validation") {
      if (error.error.problem?.code === "insufficient_stock") {
        return { fieldErrors: { quantity: "No hay stock suficiente" } };
      }
      return { fieldErrors: error.error.fieldErrors };
    }
    throw error;
  }
}

export function Component(): ReactNode {
  const product = useLoaderData<typeof loader>();
  const result = useActionData<typeof action>();
  const navigation = useNavigation();
  const submitting = navigation.state === "submitting";
  // Una key por intento de compra (estable entre renders): reintentar no duplica la orden.
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  return (
    <article>
      <h1>{product.name}</h1>
      <Form method="post">
        <input type="hidden" name="idempotencyKey" value={idempotencyKey} />
        <label>
          Cantidad
          <input name="quantity" type="number" min={1} defaultValue={1} />
        </label>
        {result?.fieldErrors.quantity ? <p role="alert">{result.fieldErrors.quantity}</p> : null}
        <button type="submit" disabled={submitting}>{submitting ? "Comprando…" : "Comprar"}</button>
      </Form>
    </article>
  );
}
```

Errores de ruta (`src/routes/load-error.ts` y `route-error.tsx`):

```tsx
/** Convierte errores de API esperables en Responses de ruta (→ isRouteErrorResponse). */
export function rethrowAsRouteError(error: unknown): never {
  if (isApiRequestError(error)) {
    switch (error.error.kind) {
      case "not_found":
        throw data("El recurso no existe", { status: 404 });
      case "forbidden":
        throw data("No tenés permiso", { status: 403 });
      case "canceled":
        throw error; // navegación interrumpida: el router lo ignora
      default:
        break;
    }
  }
  throw error; // inesperado → boundary + RouterProvider onError → telemetría
}

export function RouteError(): ReactNode {
  const error = useRouteError();
  if (isRouteErrorResponse(error)) {
    return (
      <section role="alert">
        <h1>{error.status === 404 ? "No encontrado" : `Error ${error.status}`}</h1>
        <p>{typeof error.data === "string" ? error.data : error.statusText}</p>
      </section>
    );
  }
  return (
    <section role="alert">
      <h1>Error inesperado</h1>
      <p>Ya lo registramos. Probá recargar la página.</p>
    </section>
  );
}
```

Layout con pending UI global:

```tsx
export function RootLayout(): ReactNode {
  const navigation = useNavigation();
  return (
    <div className="layout">
      <nav><NavLink to="/products">Productos</NavLink></nav>
      {navigation.state !== "idle" ? <div role="progressbar" aria-label="Cargando" /> : null}
      <main><Outlet /></main>
    </div>
  );
}
```

## Checklist de verificación

- [ ] `grep -rn "react-router-dom" src package.json` no devuelve nada (en v8).
- [ ] Entrar a una ruta protegida sin sesión redirige a `/login?next=...` **sin** ejecutar loaders hijos (verificar en la pestaña Network).
- [ ] `vite build` muestra un chunk por cada ruta `lazy`.
- [ ] Un id inexistente muestra el 404 de la rama sin romper el layout.
- [ ] Navegar rápido entre detalles cancela las requests anteriores (estado "canceled" en Network).
- [ ] Después de un `action` exitoso los datos se ven actualizados sin recargar.
- [ ] `tsc --noEmit` estricto pasa.

## Skills relacionadas

- `building-axios-clients`: `ordersApi`, `ApiRequestError`, `signal`.
- `handling-react-errors`: `onError` del router y boundaries.
- `choosing-ssr-or-spa`: cuándo pasar de data mode (SPA) a framework mode (SSR).
