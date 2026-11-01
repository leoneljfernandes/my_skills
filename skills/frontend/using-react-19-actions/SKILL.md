---
name: using-react-19-actions
description: Use when building forms or mutations in React 19 - form actions, pending/submitting state, optimistic UI, server validation errors, reading promises or context with use(), transitions - or when code uses useState+onSubmit+isLoading boilerplate, useFormState, manual optimistic rollbacks, or useEffect to fetch inside Suspense.
domain: frontend
tags: [react, react-19, forms, actions, useActionState, useOptimistic, suspense, typescript]
triggers: [useActionState, useFormStatus, useOptimistic, "use(", useTransition, startTransition, "form action", "Server Actions", formulario, "optimistic UI", "UI optimista", Suspense, useFormState, "pending state"]
---

# Actions y hooks de formularios de React 19

Una **Action** es una función async ejecutada dentro de una transition. React maneja el estado pendiente, los errores (van a la Error Boundary), el reset del form y la UI optimista. Desaparece el boilerplate `isLoading`/`try`/`finally`.

## Contexto y reglas

| Hook | Para qué | Regla clave |
|---|---|---|
| `useActionState(action, initial)` | estado devuelto por la última ejecución (errores de campo, resultado) | la acción recibe `(prevState, formData)` y **devuelve** el nuevo estado |
| `useFormStatus()` (react-dom) | `pending` del `<form>` **padre** | solo funciona en un componente **hijo** del form |
| `useOptimistic(value, reducer)` | mostrar el resultado esperado mientras la acción corre | llamar al setter **dentro** de una Action/transition; al terminar vuelve al valor real |
| `use(promise)` | leer una promesa dentro de `<Suspense>` | la promesa se crea **una vez por entrada** (loader, prop, o `useState` en un componente que vive *dentro* de la boundary y se remonta con `key`): nunca en cada render del componente que la lee |
| `use(Context)` | leer contexto, incluso dentro de `if` | reemplaza `useContext` |
| `useTransition` | marcar actualizaciones no urgentes, o acciones fuera de `<form>` | `startTransition(async () => {...})` |

**Hacer**

- `<form action={formAction}>` con inputs **no controlados** (`name`, `defaultValue`). **React resetea el form al terminar la acción, haya salido bien o devuelto un error**: un campo escrito vuelve a su `defaultValue`. Para conservar lo escrito cuando la acción devuelve un error, la acción devuelve también los valores enviados en el estado y cada campo toma `defaultValue={state.values.x}` (ejemplo `NameForm` abajo).
- `<Form>` y `fetcher.Form` de React Router **no** borran los campos después de una action; ahí no hace falta devolver los valores. Un formulario de alta que sí debe vaciarse tras el éxito, lo resetea a mano (`formRef.current?.reset()`).
- Campos que dependen unos de otros (elegir un servicio filtra los profesionales) pueden ser controlados (`value` + `onChange`) **dentro de un `<Form>` del router**, que no entra en pelea con un reset.
- Errores **esperables**: devolverlos como estado (`{ status: "error", fieldErrors }`) y pintarlos junto al campo. Son esperables `validation` (422), `conflict` (409: horario ocupado, nombre repetido) y los fallos de conexión (`network`, `timeout`): en todos la persona quiere reintentar **sin perder lo que escribió**. Mandarlos a la boundary borra el formulario.
- Errores **inesperados** (500 y todo lo que no sea esperable): relanzarlos. Llegan a la Error Boundary más cercana. Dentro de una ruta de datos, `forbidden`, `not_found` y `unauthorized` no se relanzan tal cual: `rethrowAsRouteError` los convierte en respuesta de ruta (403/404) o en la redirección al login (ver `routing-with-react-router`). Un widget sin router sí hace `throw error`. En un **login**, `unauthorized` con `code == "invalid_credentials"` y `rate_limited` son esperables (la persona quiere corregir la contraseña o esperar).
- Estado de la acción como **unión discriminada** (`idle | success | error`), siempre el mismo `ActionResult<TData, TValues>` de `src/lib/action-result.ts` (abajo): `useActionState`, la `action` de una ruta y `useFetcher` devuelven la misma forma, y `values` conserva lo escrito.
- `useOptimistic` + callback al padre (`onOrdered`) para que la fuente de verdad se actualice. Si la acción falla, el valor optimista se revierte solo.
- Botón de submit deshabilitado + `aria-busy` mientras está pendiente. La fuente de `pending` depende del formulario:

  | Formulario | Fuente de `pending` |
  |---|---|
  | `<form action={fn}>` | `useFormStatus()` en un componente **hijo**, o el tercer valor de `useActionState` |
  | `<Form method="post">` del router | `useNavigation().state === "submitting"` (también sirve `useFormStatus()` en un hijo) |
  | `fetcher.Form` | `fetcher.state !== "idle"` |

  Las cuatro fuentes funcionan; usar la del tipo de formulario que se tiene.
- `Idempotency-Key` por intento en mutaciones no idempotentes, solo si el servidor deduplica (ver `building-axios-clients`).
- **Dónde vive la mutación decide la herramienta**:

  | Caso | Usar |
  |---|---|
  | Página de una ruta de datos | `action` + `<Form>` del router (revalida los loaders solo) |
  | Fila o widget dentro de una ruta | `action` + `useFetcher` (`fetcher.Form` o `fetcher.submit`) |
  | Widget dentro de una ruta cuya mutación **no cambia datos de ningún loader** (preferencias locales, un buscador, un formulario de contacto) | `useActionState` |
  | Extensión sin ruta propia (un botón dentro de una pantalla ajena) | API directa en `useTransition` + `useRevalidator()` |
  | App sin router de datos | `useActionState` con API directa |

  Si la mutación cambia datos que lee un loader (comprar descuenta el stock del producto), `useActionState` con la API directa deja la pantalla con datos viejos: en una ruta de datos va por `action`. Los dos "Comprar" de abajo y de `routing-with-react-router` son la misma mutación en dos contextos.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `useState(isLoading)` + `onSubmit` + `try/finally` | boilerplate, estados inconsistentes | `useActionState` |
| `useFormStatus` en el mismo componente que el `<form>` | `pending` siempre `false` | componente hijo |
| `<form action>` + error devuelto sin devolver los valores | React resetea el form y la persona pierde lo que escribió | devolver `values` en el estado y usarlos como `defaultValue` |
| `use(fetch(...))` dentro del componente | promesa nueva en cada render → loop infinito | promesa creada una vez por entrada (loader / prop / `useState` dentro de la boundary) |
| `useMemo(() => api.get(...))` (o cualquier cache) **por encima** de la boundary como fuente de la promesa de `use()` | la promesa rechazada sobrevive al fallback y "Reintentar" relanza el mismo rechazo sin pedir nada | la promesa nace en un componente *dentro* de la boundary: "Reintentar" lo desmonta y remonta, y nace otra |
| Setter optimista fuera de una transition | warning y sin rollback automático | llamarlo dentro de la Action |
| Tragar errores inesperados en la acción | la UI queda en estado inválido sin aviso | relanzar → Error Boundary |
| Inputs controlados en forms con action | pelea con el reset automático; renders por tecla | `defaultValue` + `name` |
| `useFormState` (nombre del canary) | API vieja | `useActionState` |

## Ejemplos

`src/lib/action-result.ts`, el resultado único de toda acción de formulario. `expectedActionError` clasifica lo esperable (422, 409, conexión) y devuelve `null` para lo inesperado, que el llamador relanza:

```ts
import { isApiRequestError } from "./http/errors";

/** Resultado de una acción: lo mismo para useActionState, la action de una ruta y useFetcher. */
export type ActionResult<TData = null, TValues extends Record<string, string> = Record<string, string>> =
  | { status: "idle" }
  | { status: "success"; data: TData }
  | { status: "error"; message: string; fieldErrors: Record<string, string>; values: TValues };

export type ActionError<TValues extends Record<string, string> = Record<string, string>> = Extract<
  ActionResult<never, TValues>,
  { status: "error" }
>;

export function actionError<TValues extends Record<string, string>>(
  message: string,
  values: TValues,
  fieldErrors: Record<string, string> = {},
): ActionError<TValues> {
  return { status: "error", message, fieldErrors, values };
}

/** Esperables: validation (422), conflict (409) y fallos de conexión. Lo demás es inesperado → `null`. */
export function expectedActionError<TValues extends Record<string, string>>(
  error: unknown,
  values: TValues,
): ActionError<TValues> | null {
  if (!isApiRequestError(error)) return null;
  const failure = error.error;
  switch (failure.kind) {
    case "validation":
      return actionError(failure.problem?.detail ?? "Revisá los datos", values, failure.fieldErrors);
    case "conflict":
      return actionError(failure.problem?.detail ?? "Revisá los datos", values);
    case "network":
    case "timeout":
      return actionError("Sin conexión. Probá de nuevo.", values);
    default:
      return null;
  }
}
```

Conservar lo escrito tras un error devuelto (la acción devuelve los valores enviados y el campo los usa como `defaultValue`):

```tsx
import { useActionState, type ReactNode } from "react";

import type { ActionResult } from "@/lib/action-result";

type NameFormState = ActionResult<null, { name: string }>;

export function NameForm({ save }: { save: (name: string) => Promise<string | null> }): ReactNode {
  const [state, formAction, pending] = useActionState<NameFormState, FormData>(
    async (_previous, formData) => {
      const name = String(formData.get("name") ?? "");
      const error = await save(name); // null = guardado; texto = error esperable de validación
      // Con error se devuelven los valores para conservarlos; con éxito no hace falta: el form se limpia.
      if (error !== null) return { status: "error", message: error, fieldErrors: {}, values: { name } };
      return { status: "success", data: null };
    },
    { status: "idle" },
  );

  return (
    <form action={formAction}>
      <input name="name" aria-label="name" defaultValue={state.status === "error" ? state.values.name : ""} />
      {state.status === "error" ? <p role="alert">{state.message}</p> : null}
      {state.status === "success" ? <p role="status">Guardado</p> : null}
      <button type="submit" disabled={pending} aria-busy={pending}>Guardar</button>
    </form>
  );
}
```

Formulario con `useActionState` + `useFormStatus` + `useOptimistic` (verificado (test) con `tsc --strict`, `exactOptionalPropertyTypes`). Es para una **app sin router de datos** o para un widget cuya mutación no cambia datos de ningún loader; esta compra sí cambia el stock que lee un loader, así que dentro de una ruta de datos la misma mutación va por `action` + `<Form>` (`routing-with-react-router`). El padre actualiza su fuente de verdad con `onOrdered`:

```tsx
import { useActionState, useOptimistic, type ReactNode } from "react";
import { useFormStatus } from "react-dom";

import type { Product } from "@/features/products";
import { expectedActionError, type ActionResult } from "@/lib/action-result";
import { ordersApi, type Order } from "./api";

type FormState = ActionResult<Order, { quantity: string }>;

const initialState: FormState = { status: "idle" };

/** useFormStatus lee el <form> PADRE: tiene que ser un componente hijo, no el mismo componente. */
function SubmitButton(): ReactNode {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} aria-busy={pending}>
      {pending ? "Comprando…" : "Comprar"}
    </button>
  );
}

interface QuickOrderFormProps {
  product: Product;
  customerEmail: string;
  /** El padre actualiza su fuente de verdad (invalidar cache, refrescar la lista...). */
  onOrdered: (order: Order) => void;
}

export function QuickOrderForm({ product, customerEmail, onOrdered }: QuickOrderFormProps): ReactNode {
  // Mientras la acción corre se muestra el stock ya descontado; al terminar vuelve a product.stock
  // (que el padre habrá actualizado vía onOrdered) o se revierte solo si falló.
  const [optimisticStock, subtractStock] = useOptimistic(
    product.stock,
    (stock: number, quantity: number) => stock - quantity,
  );

  const [state, formAction] = useActionState<FormState, FormData>(async (_previous, formData) => {
    const rawQuantity = String(formData.get("quantity") ?? "");
    const quantity = Number(rawQuantity);
    subtractStock(quantity); // permitido: las acciones de useActionState corren dentro de una transition
    try {
      const order = await ordersApi.placeOrder({
        customer_email: customerEmail,
        product_id: product.id,
        quantity,
      });
      onOrdered(order);
      return { status: "success", data: order };
    } catch (error) {
      // Esperables: se muestran junto al campo y el form conserva la cantidad escrita.
      const expected = expectedActionError(error, { quantity: rawQuantity });
      if (expected) return expected;
      throw error; // inesperado → la ErrorBoundary más cercana
    }
  }, initialState);

  return (
    <form action={formAction}>
      <p>Stock disponible: {optimisticStock}</p>
      <label>
        Cantidad
        <input
          name="quantity"
          type="number"
          min={1}
          max={product.stock}
          defaultValue={state.status === "error" ? state.values.quantity : 1}
          required
        />
      </label>
      {state.status === "error" ? <p role="alert">{state.fieldErrors.quantity ?? state.message}</p> : null}
      {state.status === "success" ? <p role="status">Orden #{state.data.id} creada</p> : null}
      <SubmitButton />
    </form>
  );
}
```

`use(promise)` con Suspense + Error Boundary. La promesa nace **una vez por entrada** y "Reintentar" tiene que crear otra. Por eso se crea en un componente que vive **dentro** de la boundary: cuando la promesa rechaza, la boundary desmonta ese subárbol y "Reintentar" lo vuelve a montar, así que `useState` crea una promesa nueva. Si se memoizara por encima de la boundary (`useMemo` en `ProductStock`), la promesa rechazada sobreviviría al fallback y el reintento relanzaría el mismo rechazo sin pedir nada. La `key` hace lo mismo al cambiar de producto. En desarrollo, `StrictMode` ejecuta el inicializador dos veces y descarta la segunda promesa. Si la pantalla ya tiene un loader, mejor devolver la promesa desde el loader y reintentar con `useRevalidator()`:

```tsx
import { Suspense, use, useState, type ReactNode } from "react";

import { DefaultFallback, ErrorBoundary } from "@/components/ErrorBoundary";
import { productsApi } from "@/features/products";

/** use(promise) suspende hasta que resuelve; si rechaza, la ErrorBoundary lo atrapa. */
function StockValue({ stockPromise }: { stockPromise: Promise<number> }): ReactNode {
  const stock = use(stockPromise);
  return <span>{stock} unidades</span>;
}

/** Vive dentro de la boundary: el inicializador de useState crea la promesa una sola vez por montaje. */
function StockLoader({ productId }: { productId: number }): ReactNode {
  const [stockPromise] = useState(() => productsApi.getProduct(productId).then((product) => product.stock));
  return (
    <Suspense fallback={<span aria-busy="true">…</span>}>
      <StockValue stockPromise={stockPromise} />
    </Suspense>
  );
}

export function ProductStock({ productId }: { productId: number }): ReactNode {
  return (
    <ErrorBoundary scope="product-stock" fallback={DefaultFallback} resetKeys={[productId]}>
      <StockLoader key={productId} productId={productId} />
    </ErrorBoundary>
  );
}
```

Acción fuera de un `<form>` con `useTransition`, para una **extensión sin ruta propia** o una app sin router de datos (`projectsApi` y `navigate` son ilustrativos). Los errores inesperados que lanza una transition async llegan a la Error Boundary más cercana; en una ruta de datos, la misma mutación se envía a la `action` con `useSubmit()` o `fetcher.submit({ intent: "archive" }, { method: "post" })`:

```tsx
const [isPending, startTransition] = useTransition();

const archive = (): void => {
  startTransition(async () => {
    await projectsApi.archive(project.id);   // errores inesperados → Error Boundary
    startTransition(() => navigate("/projects"));
  });
};
```

## Checklist de verificación

- [ ] Ningún formulario de página usa `useState` para `isLoading`/`isSubmitting`. Un componente de extensión sin ruta propia usa `useTransition` junto a `useRevalidator()` (ver `routing-with-react-router`).
- [ ] Toda mutación que cambia datos de un loader va por `action` (`<Form>` o `useFetcher`); `useActionState` queda para widgets cuya mutación no cambia ningún loader y para apps sin router de datos.
- [ ] Todas las acciones devuelven el mismo `ActionResult` (`idle | success | error` con `values`); no hay `{ ok: boolean }` ni `{ fieldErrors }` sueltos.
- [ ] Los botones de submit se deshabilitan mientras está pendiente, con la fuente de `pending` que corresponde a su tipo de formulario (tabla de arriba).
- [ ] Un error esperable devuelto por la acción no borra lo que la persona escribió (`action_keeps_values_after_returned_error`).
- [ ] Los errores 422, 409 y de conexión se muestran junto al campo. Un error 500 simulado termina en la Error Boundary, no en un form congelado.
- [ ] La UI optimista se revierte sola al forzar un fallo de la API (probarlo con la red en "offline").
- [ ] Toda promesa leída con `use()` nace una vez por entrada (loader, prop o `useState` dentro de la boundary), no en cada render ni en un cache por encima de la boundary; "Reintentar" en la boundary crea una promesa nueva y recupera el widget cuando la causa desapareció.
- [ ] `tsc --noEmit` estricto pasa.

## Skills relacionadas

- `handling-react-errors`: dónde terminan los errores relanzados.
- `routing-with-react-router`: `action` + `<Form>` para mutaciones de página, `rethrowAsRouteError` y el login.
- `building-axios-clients`: `ApiRequestError` y `fieldErrors` tipados.
