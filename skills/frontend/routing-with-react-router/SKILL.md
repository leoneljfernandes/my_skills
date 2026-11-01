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
- **Rutas protegidas con `middleware`** sobre una ruta que agrupa todo lo privado. El middleware corre **antes** de cualquier loader/action hijo: sin usuario → `throw redirect("/login?next=...")`, con `next` = `pathname + search` (la pantalla con sus filtros). Pone el usuario en un `createContext` tipado que loaders y actions leen con `context.get(...)`.
- **`next` se valida antes de redirigir** (`safeNext`): un `?next=//evil.com` sin validar es un *open redirect*. Se acepta solo lo que resuelve al mismo origen.
- **Permisos**: `requirePermission("x.edit")` como middleware de cada rama o ruta que lo exige. Sin permiso → `throw data("…", { status: 403 })`: la `ErrorBoundary` de la rama lo muestra **dentro del layout**, en vez de mandar a una ruta `/forbidden` que habría que definir.
- **Los componentes no leen `context`**: solo loaders, actions y middleware. Para que un componente sepa quién es el usuario, la ruta privada tiene un `id` y un loader que devuelve `{ user, ... }`; los componentes lo leen con `useRouteLoaderData(PRIVATE_ROUTE)`.
- **`HydrateFallback`** en la ruta que carga datos en la primera visita: sin él, la primera carga muestra pantalla en blanco hasta que el loader termina.
- **Code-splitting**: `lazy: () => import("./routes/x")`. El módulo exporta `loader`, `action`, `Component`, `ErrorBoundary`, y Vite genera un chunk por ruta.
- **ErrorBoundary por rama** con `useRouteError()` + `isRouteErrorResponse()`: distingue 404/403 (respuestas de ruta) de errores inesperados.
- Un helper `rethrowAsRouteError` convierte `ApiRequestError` esperables (404, 403) en respuestas de ruta. El resto se relanza (→ boundary + telemetría).
- **Qué es "esperable" en una action** (se devuelve como dato y se muestra junto al formulario): `validation` (422), `conflict` (409, p. ej. horario ocupado) y los fallos de conexión (`network`, `timeout`), porque en todos la persona necesita **conservar lo que escribió**. Todo lo demás se lanza.
- **`useFetcher`** para mutaciones dentro de una lista o fila (activar, editar, borrar sin salir de la pantalla): cada fila lleva su `fetcher.Form` y un campo oculto `intent`. Es el patrón dominante cuando hay listas editables.
- Pending UI con `useNavigation().state` (`idle | loading | submitting`) en formularios de página, y `fetcher.state` en los de `useFetcher`; no con estados locales.
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
| `?next=` sin validar | open redirect: el login manda a un sitio externo | `safeNext` |
| `fetch` sin `request.signal` en el middleware de sesión | la request del usuario sigue viva tras navegar | pasar `signal` también ahí |

## Ejemplos

`src/router.tsx` (verificado: `tsc --strict` y `vite build`, que genera un chunk por ruta lazy):

```tsx
import { createBrowserRouter } from "react-router";

import { requirePermission, requireUser } from "./auth";
import { Loading } from "./routes/loading";
import { privateLoader, PRIVATE_ROUTE } from "./routes/private";
import { RootLayout } from "./routes/root-layout";
import { RouteError } from "./routes/route-error";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: RootLayout,
    ErrorBoundary: RouteError, // última red de la app; cada rama puede tener la suya
    children: [
      { path: "login", lazy: () => import("./routes/login") },
      {
        // Agrupa todo lo protegido bajo un único middleware. El `id` permite que los componentes
        // lean el usuario con useRouteLoaderData(PRIVATE_ROUTE).
        id: PRIVATE_ROUTE,
        middleware: [requireUser],
        loader: privateLoader,
        HydrateFallback: Loading, // primera carga: el layout visible en vez de pantalla en blanco
        ErrorBoundary: RouteError,
        children: [
          { index: true, lazy: () => import("./routes/products") },
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
            middleware: [requirePermission("admin.manage")],
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
import { createContext, data, redirect, type MiddlewareFunction } from "react-router";

import { http } from "./lib/http";
import { isApiRequestError } from "./lib/http/errors";

export interface User {
  id: number;
  email: string;
  role: string;
  permissions: ReadonlyArray<string>;
}

/** Contexto tipado del router: los loaders/actions protegidos leen el usuario de acá. */
export const userContext = createContext<User | null>(null);

async function fetchCurrentUser(signal: AbortSignal): Promise<User | null> {
  try {
    // El interceptor hace refresh si hace falta. `signal`: si la persona navega, se cancela.
    const { data } = await http.get<User>("/auth/me", { signal });
    return data;
  } catch (error) {
    if (isApiRequestError(error) && error.error.kind === "unauthorized") return null;
    throw error;
  }
}

/**
 * Solo rutas internas: evita que ?next= mande al usuario a otro sitio (open redirect).
 * Se resuelve como lo haría el navegador (descarta tabs y saltos de línea, trata "\\" como "/")
 * y se acepta solo si el resultado queda en el mismo origen.
 */
export function safeNext(raw: string | null): string {
  if (!raw?.startsWith("/")) return "/";
  const target = new URL(raw, window.location.origin);
  if (target.origin !== window.location.origin) return "/";
  return target.pathname + target.search + target.hash;
}

/** Protege TODA la rama de rutas hija: corre antes que cualquier loader/action. */
export const requireUser: MiddlewareFunction = async ({ request, context }) => {
  const user = await fetchCurrentUser(request.signal);
  if (!user) {
    const url = new URL(request.url);
    throw redirect(`/login?next=${encodeURIComponent(url.pathname + url.search)}`);
  }
  context.set(userContext, user);
};

export function requirePermission(permission: string): MiddlewareFunction {
  return ({ context }) => {
    if (!context.get(userContext)?.permissions.includes(permission)) {
      // 403 como respuesta de ruta: la ErrorBoundary de la rama lo muestra dentro del layout.
      throw data("No tenés permiso", { status: 403 });
    }
  };
}
```

Loader de la rama privada y lectura desde un componente (`src/routes/private.ts`):

```ts
import { useRouteLoaderData, type LoaderFunctionArgs } from "react-router";

import { userContext, type User } from "../auth";

/** Id de la rama con sesión: los componentes lo usan para leer los datos de su loader. */
export const PRIVATE_ROUTE = "private";

export function privateLoader({ context }: LoaderFunctionArgs): { user: User } {
  const user = context.get(userContext);
  if (!user) throw new Error("privateLoader must run after requireUser");
  return { user };
}

/** `undefined` fuera de la rama privada (p. ej. en /login). */
export function usePrivateData(): { user: User } | undefined {
  return useRouteLoaderData<{ user: User }>(PRIVATE_ROUTE);
}
```

Módulo de ruta lazy con loader + action + Form (`src/routes/product-detail.tsx`):

```tsx
import type { ReactNode } from "react";
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
    const order = await ordersApi.placeOrder({
      customer_email: user?.email ?? "",
      product_id: parseId(params.productId),
      quantity,
    });
    return redirect(`/orders/${order.id}`);
  } catch (error) {
    // Errores esperables: se muestran junto al form, que conserva lo escrito. El resto sube a la boundary.
    if (isApiRequestError(error)) {
      switch (error.error.kind) {
        case "validation":
          if (error.error.problem?.code === "insufficient_stock") {
            return { fieldErrors: { quantity: "No hay stock suficiente" } };
          }
          return { fieldErrors: error.error.fieldErrors };
        case "network":
        case "timeout":
          return { fieldErrors: { quantity: "Sin conexión. Probá de nuevo." } };
        default:
          break;
      }
    }
    throw error;
  }
}

export function Component(): ReactNode {
  const product = useLoaderData<typeof loader>();
  const result = useActionData<typeof action>();
  const navigation = useNavigation();
  const submitting = navigation.state === "submitting";

  return (
    <article>
      <h1>{product.name}</h1>
      <Form method="post">
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

Lista con mutaciones por fila (`useFetcher`): cada fila es un `fetcher.Form` con su `intent`, y el componente de ruta no necesita estado propio. `fetcher.Form` **conserva** los valores del formulario tras la action; si el formulario es de alta, se limpia a mano al terminar con éxito:

```tsx
function ProductRow({ product }: { product: Product }): ReactNode {
  const fetcher = useFetcher<{ ok: boolean }>();
  const saving = fetcher.state !== "idle";
  return (
    <fetcher.Form method="post">
      <input type="hidden" name="intent" value="update" />
      <input type="hidden" name="id" value={product.id} />
      <input name="name" defaultValue={product.name} />
      <button type="submit" disabled={saving}>{saving ? "Guardando…" : "Guardar"}</button>
    </fetcher.Form>
  );
}

function NewProductForm(): ReactNode {
  const fetcher = useFetcher<{ ok: boolean }>();
  const formRef = useRef<HTMLFormElement>(null);
  // Alta con éxito: vaciar el formulario. Se hace al detectar el resultado, no en un efecto.
  if (fetcher.state === "idle" && fetcher.data?.ok) formRef.current?.reset();
  return (
    <fetcher.Form method="post" ref={formRef}>
      <input type="hidden" name="intent" value="create" />
      <input name="name" required />
      <button type="submit">Agregar</button>
    </fetcher.Form>
  );
}
```

Componente de extensión sin ruta propia (un botón dentro de una pantalla que no es suya, que no puede declarar `action`): puede mutar con la API directa y refrescar con `useRevalidator()`. Solo en ese caso; en cualquier componente que pertenezca a una ruta, `action` + `useFetcher`.

```tsx
function NotifyButton({ orderId }: { orderId: number }): ReactNode {
  const { revalidate } = useRevalidator();
  const [sending, setSending] = useState(false);
  return (
    <button
      type="button"
      disabled={sending}
      onClick={async () => {
        setSending(true);
        try {
          await ordersApi.notify(orderId);
          await revalidate();
        } finally {
          setSending(false);
        }
      }}
    >
      Notificar
    </button>
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
        break; // los kind que la UI no distingue siguen a `throw error`
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
- [ ] `safeNext("//evil.com")`, `safeNext("/\\evil.com")` y `safeNext("https://evil.com")` devuelven `/`; `safeNext("/a?b=1")` conserva el query.
- [ ] Un usuario sin permiso ve el 403 dentro del layout, no una página en blanco ni una ruta inexistente.
- [ ] La primera carga muestra el layout con el `HydrateFallback`, no pantalla en blanco.
- [ ] Entrar a una ruta protegida sin sesión redirige a `/login?next=...` **sin** ejecutar loaders hijos (verificar en la pestaña Network).
- [ ] `vite build` muestra un chunk por cada ruta `lazy`.
- [ ] Un id inexistente muestra el 404 de la rama sin romper el layout.
- [ ] Navegar rápido entre detalles cancela las requests anteriores (estado "canceled" en Network).
- [ ] Después de un `action` exitoso los datos se ven actualizados sin recargar.
- [ ] `tsc --noEmit` estricto pasa.

## Skills relacionadas

- `building-axios-clients`: `ordersApi`, `ApiRequestError`, `signal`.
- `using-react-19-actions`: qué `kind` se muestran en el formulario y cómo conservar los valores.
- `handling-react-errors`: `onError` del router y boundaries.
- `choosing-ssr-or-spa`: cuándo pasar de data mode (SPA) a framework mode (SSR).
