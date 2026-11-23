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
- **Actions** + `<Form method="post">` para mutaciones de página: después de una action, el router **revalida** los loaders y la UI se actualiza sola. Los errores esperables (ver más abajo) se devuelven como datos (`useActionData`) con el `ActionResult` de `using-react-19-actions`; los inesperados pasan por `rethrowAsRouteError`.
- **Rutas protegidas con `middleware`** sobre una ruta que agrupa todo lo privado. El middleware corre **antes** de cualquier loader/action hijo: sin usuario → `throw replace("/login?next=...")` (`replace` es un `redirect` que reemplaza la entrada del historial: "atrás" no vuelve a una pantalla que redirige otra vez), con `next` = `pathname + search` (la pantalla con sus filtros). Pone el usuario en un `createContext` tipado que loaders y actions leen con `currentUser(context)`. La sesión vive en `features/auth` (`requireUser`, `usePrivateData`, `authApi`), no en `routes/`.
- **Un solo dueño de la redirección al login: el router.** Primera visita sin sesión: `requireUser` (aunque el refresh responda 401 y llame a `onSessionExpired`, `redirectToLogin` no navega mientras el router no terminó la primera carga: una sola redirección). Sesión vencida con la app abierta: `onSessionExpired` (inyectado desde `main.tsx`) llama a `redirectToLogin(router)` con el destino de la navegación en curso. Un loader o action que igual recibe `unauthorized` lo convierte `rethrowAsRouteError` en `redirect` (nunca llega a la boundary ni a la telemetría). Nunca `window.location.assign`: durante una navegación apunta a la pantalla anterior y recarga la app.
- **`next` se valida antes de redirigir** (`safeNext`): un `?next=//evil.com` sin validar es un *open redirect*. Se acepta solo lo que resuelve al mismo origen.
- **Permisos**: `requirePermission("x.edit")` como middleware de cada rama o ruta que lo exige. Sin permiso → `throw data("…", { status: 403 })`: la `ErrorBoundary` de la rama lo muestra **dentro del layout**, en vez de mandar a una ruta `/forbidden` que habría que definir.
- **Los componentes no leen `context`**: solo loaders, actions y middleware. Para que un componente sepa quién es el usuario, la ruta privada tiene un `id` y un loader que devuelve `{ user, ... }`; los componentes lo leen con `useRouteLoaderData(PRIVATE_ROUTE)`.
- **`HydrateFallback`** en la ruta que carga datos en la primera visita: sin él, la primera carga muestra pantalla en blanco hasta que el loader termina.
- **Code-splitting**: `lazy: () => import("@/routes/x")`. El módulo exporta `loader`, `action`, `Component`, `ErrorBoundary`, y Vite genera un chunk por ruta.
- **ErrorBoundary por rama** con `useRouteError()` + `isRouteErrorResponse()`: distingue 404/403 (respuestas de ruta) de errores inesperados.
- Un helper `rethrowAsRouteError(error, request)` convierte `ApiRequestError` en lo que el router sabe mostrar: `not_found` y `forbidden` → respuestas de ruta (404, 403), `unauthorized` → `redirect` al login. El resto se relanza (→ boundary + telemetría). Se usa en **loaders y actions** por igual, para que la misma falta de permiso se vea igual venga de donde venga.
- **Qué es "esperable" en una action** (se devuelve como dato y se muestra junto al formulario): `validation` (422), `conflict` (409, p. ej. horario ocupado) y los fallos de conexión (`network`, `timeout`), porque en todos la persona necesita **conservar lo que escribió**. Todo lo demás pasa por `rethrowAsRouteError`. Excepción del **login**: `unauthorized` con `code == "invalid_credentials"` (contraseña mala) y `rate_limited` (429 del límite de intentos) también son esperables, y la action los devuelve con el email escrito.
- **`useFetcher`** para mutaciones dentro de una lista o fila (activar, editar, borrar sin salir de la pantalla): cada fila lleva su `fetcher.Form` y un campo oculto `intent`. Es el patrón dominante cuando hay listas editables. Su resultado es el mismo `ActionResult`, así que la fila puede mostrar los errores esperables.
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
| `window.location.assign("/login")` al expirar la sesión | `next` de la pantalla anterior, recarga completa y un segundo redirect del router | `redirectToLogin(router)` inyectado desde `main.tsx` |
| Resetear un form con `ref.current?.reset()` en el render | cada re-render posterior borra lo que se está escribiendo | `useEffect` que depende de `fetcher.data`, una vez por resultado |
| Mandar el 401 de un login (contraseña mala) o el 429 a la boundary | el error más común del formulario de login se ve como "Error inesperado" y ensucia la telemetría | devolverlos como datos en la action del login |

## Ejemplos

`src/router.tsx` (verificado a mano (2026-11-01, `tsc --strict` y `vite build`, que genera un chunk por ruta lazy)). Incluye lo que los demás ejemplos necesitan: `orders/:orderId` (adonde redirige la compra), `products/search` (la ruta de recurso del buscador de `architecting-react-apps`) y una ruta `*` **dentro** del layout, para que un 404 se vea con la navegación puesta:

```tsx
import { createBrowserRouter } from "react-router";

import { PRIVATE_ROUTE, privateLoader, requirePermission, requireUser } from "@/features/auth";
import { Loading } from "@/routes/loading";
import { RootLayout } from "@/routes/root-layout";
import { NotFound, RouteError } from "@/routes/route-error";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: RootLayout,
    ErrorBoundary: RouteError, // última red de la app; cada rama puede tener la suya
    children: [
      { path: "login", lazy: () => import("@/routes/login") },
      {
        // Agrupa todo lo protegido bajo un único middleware. El `id` permite que los componentes
        // lean el usuario con usePrivateData().
        id: PRIVATE_ROUTE,
        middleware: [requireUser],
        loader: privateLoader,
        HydrateFallback: Loading, // primera carga: el layout visible en vez de pantalla en blanco
        ErrorBoundary: RouteError,
        children: [
          { index: true, lazy: () => import("@/routes/products") },
          {
            path: "products",
            children: [
              { index: true, lazy: () => import("@/routes/products") },
              // Ruta de recurso del buscador: sin ella, `/products/search` caería en `:productId`.
              { path: "search", lazy: () => import("@/routes/product-search") },
              {
                path: ":productId",
                lazy: () => import("@/routes/product-detail"), // chunk propio (code-splitting)
                ErrorBoundary: RouteError,
              },
            ],
          },
          // Destino de la compra (`redirect` de la action de product-detail).
          { path: "orders/:orderId", lazy: () => import("@/routes/order-detail") },
          {
            path: "admin",
            middleware: [requirePermission("admin.manage")],
            lazy: () => import("@/routes/admin"),
          },
        ],
      },
      // Cualquier otra URL: el 404 queda dentro del layout, no en la boundary de la raíz.
      { path: "*", Component: NotFound },
    ],
  },
]);
```

La sesión es la feature `features/auth` (el tipo `User` y `authApi` están en `building-axios-clients`; el `index.ts`, después de `session.ts`, es la lista explícita de lo público). `src/features/auth/session.ts`: middleware, contexto tipado, `safeNext` y la redirección al expirar la sesión:

```ts
import {
  createContext,
  data,
  replace,
  useRouteLoaderData,
  type DataRouter,
  type LoaderFunctionArgs,
  type MiddlewareFunction,
} from "react-router";

import { isApiRequestError } from "@/lib/http/errors";
import { authApi, type User } from "./api";

/** Contexto tipado del router: los loaders/actions protegidos leen el usuario de acá. */
export const userContext = createContext<User | null>(null);

/** Id de la rama con sesión: los componentes lo usan para leer los datos de su loader. */
export const PRIVATE_ROUTE = "private";

/** Única forma de armar la URL de login: `target` es la pantalla a la que volver (con su query). */
export function loginPath(target: string): string {
  return `/login?next=${encodeURIComponent(target)}`;
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

async function fetchCurrentUser(signal: AbortSignal): Promise<User | null> {
  try {
    // El interceptor hace refresh si hace falta. `signal`: si la persona navega, se cancela.
    return await authApi.me({ signal });
  } catch (error) {
    if (isApiRequestError(error) && error.error.kind === "unauthorized") return null;
    throw error;
  }
}

/** Protege TODA la rama de rutas hija: corre antes que cualquier loader/action. */
export const requireUser: MiddlewareFunction = async ({ request, context }) => {
  const user = await fetchCurrentUser(request.signal);
  if (!user) {
    const url = new URL(request.url);
    throw replace(loginPath(url.pathname + url.search));  // replace: "atrás" no vuelve a una pantalla que redirige otra vez
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

/** El usuario de la rama privada; falla en voz alta si se lo pide fuera de ella. */
export function currentUser(context: LoaderFunctionArgs["context"]): User {
  const user = context.get(userContext);
  if (!user) throw new Error("currentUser must run after requireUser");
  return user;
}

export function privateLoader({ context }: LoaderFunctionArgs): { user: User } {
  return { user: currentUser(context) };
}

/** `undefined` fuera de la rama privada (p. ej. en /login). */
export function usePrivateData(): { user: User } | undefined {
  return useRouteLoaderData<{ user: User }>(PRIVATE_ROUTE);
}

/**
 * La sesión terminó con la app abierta (el cliente HTTP ya descartó el token). Se navega con el
 * router, que es quien conoce el destino: la navegación en curso si la hay (`window.location`
 * todavía apunta a la pantalla anterior) o, si no, la ubicación actual. Se conecta en main.tsx:
 * `setSessionExpiredHandler(() => redirectToLogin(router))`.
 * En la primera carga (router sin inicializar) no navega: el `redirect` de `requireUser` o de
 * `rethrowAsRouteError` ya lleva al login, y navegar acá sería una segunda redirección.
 */
export function redirectToLogin(router: DataRouter): void {
  if (!router.state.initialized) return;
  const target = router.state.navigation.location ?? router.state.location;
  if (target.pathname === "/login") return;
  void router.navigate(loginPath(target.pathname + target.search), { replace: true });
}
```

`src/features/auth/index.ts`, con nombres explícitos (`userContext` queda adentro: loaders y actions leen el usuario con `currentUser(context)`):

```ts
export { authApi, type User } from "./api";
export {
  PRIVATE_ROUTE,
  currentUser,
  loginPath,
  privateLoader,
  redirectToLogin,
  requirePermission,
  requireUser,
  safeNext,
  usePrivateData,
} from "./session";
```

Si la app guarda más estado de la sesión en memoria (un cache de TanStack Query, un store), se limpia en el mismo handler: `lib/http` ya descartó el token, pero no sabe de esos caches.

Login (`src/routes/login.tsx`): la contraseña mala (401 `invalid_credentials`) y el 429 son esperables. La action los devuelve con el email escrito; todo lo demás sube por `rethrowAsRouteError`. Tras el éxito, `safeNext` valida el `next`:

```tsx
import type { ReactNode } from "react";
import { Form, redirect, useActionData, useNavigation, type ActionFunctionArgs } from "react-router";

import { authApi, safeNext } from "@/features/auth";
import { actionError, expectedActionError, type ActionError } from "@/lib/action-result";
import { isApiRequestError } from "@/lib/http/errors";
import { rethrowAsRouteError } from "./load-error";

export async function action({ request }: ActionFunctionArgs): Promise<ActionError<{ email: string }> | Response> {
  const form = await request.formData();
  const email = String(form.get("email") ?? "");
  const values = { email }; // nunca la contraseña: no viaja en los datos de la action (<Form> no vacía el campo)
  try {
    await authApi.login(email, String(form.get("password") ?? ""));
  } catch (error) {
    if (isApiRequestError(error)) {
      const failure = error.error;
      if (failure.kind === "unauthorized" && failure.problem?.code === "invalid_credentials") {
        return actionError("Email o contraseña incorrectos", values);
      }
      if (failure.kind === "rate_limited") {
        return actionError("Demasiados intentos. Esperá unos minutos y probá de nuevo.", values);
      }
    }
    const expected = expectedActionError(error, values); // 422 o sin conexión
    if (expected) return expected;
    rethrowAsRouteError(error, request);
  }
  return redirect(safeNext(new URL(request.url).searchParams.get("next")));
}

export function Component(): ReactNode {
  const result = useActionData<typeof action>();
  const submitting = useNavigation().state === "submitting";
  const error = result?.status === "error" ? result : null;
  return (
    <Form method="post">
      <label>
        Email
        <input name="email" type="email" autoComplete="username" defaultValue={error?.values.email ?? ""} required />
      </label>
      <label>
        Contraseña
        <input name="password" type="password" autoComplete="current-password" required />
      </label>
      {error ? <p role="alert">{error.message}</p> : null}
      <button type="submit" disabled={submitting} aria-busy={submitting}>
        {submitting ? "Ingresando…" : "Ingresar"}
      </button>
    </Form>
  );
}
```

Módulo de ruta lazy con loader + action + Form (`src/routes/product-detail.tsx`). La action devuelve los errores esperables con lo escrito, y todo lo demás pasa por `rethrowAsRouteError`:

```tsx
import type { ReactNode } from "react";
import {
  Form, data, redirect, useActionData, useLoaderData, useNavigation,
  type ActionFunctionArgs, type LoaderFunctionArgs,
} from "react-router";

import { currentUser } from "@/features/auth";
import { ordersApi } from "@/features/orders";
import { productsApi } from "@/features/products";
import { actionError, expectedActionError, type ActionError } from "@/lib/action-result";
import { rethrowAsRouteError } from "./load-error";

function parseId(raw: string | undefined): number {
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0) throw data("Id inválido", { status: 404 });
  return id;
}

export async function loader({ params, request }: LoaderFunctionArgs) {
  try {
    return await productsApi.getProduct(parseId(params.productId), { signal: request.signal });
  } catch (error) {
    rethrowAsRouteError(error, request);
  }
}

export async function action({
  params,
  request,
  context,
}: ActionFunctionArgs): Promise<ActionError<{ quantity: string }> | Response> {
  const user = currentUser(context); // lanza si el middleware requireUser no corrió
  const form = await request.formData();
  const rawQuantity = String(form.get("quantity") ?? "");
  const values = { quantity: rawQuantity };
  const quantity = Number(rawQuantity);
  if (!Number.isInteger(quantity) || quantity < 1) {
    return actionError("Revisá los datos", values, { quantity: "Cantidad inválida" });
  }
  try {
    const order = await ordersApi.placeOrder({
      customer_email: user.email,
      product_id: parseId(params.productId),
      quantity,
    });
    return redirect(`/orders/${order.id}`);
  } catch (error) {
    // Esperables (422, 409, sin conexión): se muestran junto al form, que conserva lo escrito.
    const expected = expectedActionError(error, values);
    if (expected) return expected;
    return rethrowAsRouteError(error, request); // 403/404 → respuesta de ruta; 401 → login; el resto → boundary
  }
}

export function Component(): ReactNode {
  const product = useLoaderData<typeof loader>();
  const result = useActionData<typeof action>();
  const navigation = useNavigation();
  const submitting = navigation.state === "submitting";
  const error = result?.status === "error" ? result : null;

  return (
    <article>
      <h1>{product.name}</h1>
      <Form method="post">
        <label>
          Cantidad
          <input name="quantity" type="number" min={1} defaultValue={error?.values.quantity ?? 1} />
        </label>
        {/* Un 422 o 409 sin error de campo igual se ve: `message` cubre lo que no es de `quantity`. */}
        {error ? <p role="alert">{error.fieldErrors.quantity ?? error.message}</p> : null}
        <button type="submit" disabled={submitting} aria-busy={submitting}>
          {submitting ? "Comprando…" : "Comprar"}
        </button>
      </Form>
    </article>
  );
}
```

Lista con mutaciones por fila (`useFetcher`): cada fila es un `fetcher.Form` con su `intent`, y el componente de ruta no necesita estado propio. `fetcher.Form` **conserva** los valores del formulario tras la action. Si es de alta, se vacía **una vez por resultado**: un `useEffect` que depende de `fetcher.data` (cada respuesta es un objeto nuevo). Resetear en el render lo haría en cada re-render posterior y borraría lo que se escribe después del primer alta:

```tsx
import { useEffect, useRef, type ReactNode } from "react";
import { useFetcher } from "react-router";

import type { Product } from "@/features/products";
import type { ActionResult } from "@/lib/action-result";

export function ProductRow({ product }: { product: Product }): ReactNode {
  const fetcher = useFetcher<ActionResult>();
  const saving = fetcher.state !== "idle";
  return (
    <fetcher.Form method="post">
      <input type="hidden" name="intent" value="update" />
      <input type="hidden" name="id" value={product.id} />
      <input name="name" defaultValue={product.name} />
      <button type="submit" disabled={saving} aria-busy={saving}>{saving ? "Guardando…" : "Guardar"}</button>
      {fetcher.data?.status === "error" ? <p role="alert">{fetcher.data.message}</p> : null}
    </fetcher.Form>
  );
}

export function NewProductForm(): ReactNode {
  const fetcher = useFetcher<ActionResult>();
  const formRef = useRef<HTMLFormElement>(null);
  const saving = fetcher.state !== "idle";
  // Alta con éxito: vaciar el formulario una sola vez por resultado.
  useEffect(() => {
    if (fetcher.data?.status === "success") formRef.current?.reset();
  }, [fetcher.data]);
  return (
    <fetcher.Form method="post" ref={formRef}>
      <input type="hidden" name="intent" value="create" />
      <input name="name" required />
      <button type="submit" disabled={saving} aria-busy={saving}>{saving ? "Agregando…" : "Agregar"}</button>
      {fetcher.data?.status === "error" ? <p role="alert">{fetcher.data.message}</p> : null}
    </fetcher.Form>
  );
}
```

Componente de extensión sin ruta propia (un botón dentro de una pantalla que no es suya, que no puede declarar `action`): puede mutar con la API directa y refrescar con `useRevalidator()`. Solo en ese caso. En un componente que pertenece a una ruta, la mutación que cambia datos de algún loader va por `action` + `useFetcher`; un widget cuya mutación **no cambia datos de ningún loader** (preferencias locales, un formulario de contacto) puede usar `useActionState`, como dice la tabla "Dónde vive la mutación" de `using-react-19-actions`. `useTransition` da el estado pendiente sin `useState` y manda el rechazo a la boundary (el reporte llega por `onError` y la persona ve el fallback, no un botón mudo):

```tsx
import { useTransition, type ReactNode } from "react";
import { useRevalidator } from "react-router";

import { ordersApi } from "@/features/orders";

export function NotifyButton({ orderId }: { orderId: number }): ReactNode {
  const { revalidate } = useRevalidator();
  const [pending, startTransition] = useTransition();
  return (
    <button
      type="button"
      disabled={pending}
      aria-busy={pending}
      onClick={() => {
        startTransition(async () => {
          await ordersApi.notify(orderId); // si rechaza, llega a la ErrorBoundary más cercana
          await revalidate();
        });
      }}
    >
      Notificar
    </button>
  );
}
```

Errores de ruta (`src/routes/load-error.ts` y `route-error.tsx`):

```ts
import { data, replace } from "react-router";

import { loginPath } from "@/features/auth";
import { isApiRequestError } from "@/lib/http/errors";

/**
 * Convierte errores de API en lo que el router sabe mostrar. Se usa en loaders Y en actions.
 * Los 404/403 salen como respuestas de ruta (isRouteErrorResponse), el 401 como redirección.
 */
export function rethrowAsRouteError(error: unknown, request: Request): never {
  if (isApiRequestError(error)) {
    switch (error.error.kind) {
      case "not_found":
        throw data("El recurso no existe", { status: 404 });
      case "forbidden":
        throw data("No tenés permiso", { status: 403 });
      case "unauthorized": {
        // La sesión terminó: el cliente ya limpió el token y el router va al login. El destino es esta request.
        const url = new URL(request.url);
        throw replace(loginPath(url.pathname + url.search));
      }
      case "canceled":
        throw error; // navegación interrumpida: el router lo ignora
      default:
        break; // los kind que la UI no distingue siguen a `throw error`
    }
  }
  throw error; // inesperado → boundary + RouterProvider onError → telemetría
}
```

```tsx
import type { ReactNode } from "react";
import { Link, isRouteErrorResponse, useRevalidator, useRouteError } from "react-router";

export function RouteError(): ReactNode {
  const error = useRouteError();
  const { revalidate, state } = useRevalidator();
  if (isRouteErrorResponse(error)) {
    return (
      <section role="alert">
        <h1>{error.status === 404 ? "No encontrado" : `Error ${error.status}`}</h1>
        {/* En un 404 el texto es fijo: el del router ("No route matches URL...") es interno. */}
        <p>
          {error.status === 404
            ? "El recurso no existe o fue movido."
            : typeof error.data === "string" ? error.data : error.statusText}
        </p>
        <Link to="/">Ir al inicio</Link>
      </section>
    );
  }
  return (
    <section role="alert">
      <h1>Error inesperado</h1>
      <p>No pudimos completar la operación.</p>
      {/* revalidate() vuelve a correr los loaders de la ruta y limpia el error si ya no falla. */}
      <button type="button" disabled={state === "loading"} onClick={() => void revalidate()}>Reintentar</button>
      <Link to="/">Ir al inicio</Link>
    </section>
  );
}

/** Ruta `*` dentro del layout. */
export function NotFound(): ReactNode {
  return (
    <section role="alert">
      <h1>No encontrado</h1>
      <p>La página no existe.</p>
      <Link to="/">Ir al inicio</Link>
    </section>
  );
}
```

`Reintentar` re-ejecuta los **loaders**; el error de una `action` se limpia al volver a enviar el formulario o al navegar.

Layout con pending UI global:

```tsx
import type { ReactNode } from "react";
import { NavLink, Outlet, useNavigation } from "react-router";

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
- [ ] Entrar a una ruta protegida sin sesión redirige a `/login?next=...` **sin** ejecutar loaders hijos (verificar en la pestaña Network), con una sola navegación aunque el refresh responda 401.
- [ ] Con la sesión vencida, navegar a `/products/7?x=1` termina en `/login?next=%2Fproducts%2F7%3Fx%3D1` (el destino, no la pantalla anterior), sin recarga completa y sin "Error inesperado". El test de jsdom lo comprueba con el router; la carrera real entre la navegación y la respuesta 401 solo se ve en un navegador.
- [ ] Login: una contraseña mala conserva el email y muestra el aviso; un 429 muestra el aviso de espera; ninguno llega a la boundary ni a `onError`.
- [ ] Una action cuyo backend responde 409 o 422 sin campo conserva lo escrito y muestra el mensaje; si responde 403 o 404, se ve la respuesta de ruta ("Error 403"/"No encontrado"), igual que en un loader.
- [ ] Tras comprar, `/orders/:orderId` existe; `/products/search` no cae en `:productId`; una URL inexistente muestra el 404 dentro del layout.
- [ ] Un alta con `useFetcher` vacía el form una vez; escribir el siguiente registro y re-renderizar el padre no lo borra.
- [ ] "Reintentar" en `RouteError` recupera una ruta cuyo loader falló una vez.
- [ ] `vite build` muestra un chunk por cada ruta `lazy`.
- [ ] Un id inexistente muestra el 404 de la rama sin romper el layout.
- [ ] Navegar rápido entre detalles cancela las requests anteriores (estado "canceled" en Network).
- [ ] Después de un `action` exitoso los datos se ven actualizados sin recargar.
- [ ] `tsc --noEmit` estricto pasa.

## Skills relacionadas

- `building-axios-clients`: `authApi`, `ApiRequestError`, `signal` y `setSessionExpiredHandler`.
- `using-react-19-actions`: `ActionResult`, qué `kind` se muestran en el formulario y cómo conservar los valores.
- `handling-react-errors`: `onError` del router y boundaries.
- `choosing-ssr-or-spa`: cuándo pasar de data mode (SPA) a framework mode (SSR).
