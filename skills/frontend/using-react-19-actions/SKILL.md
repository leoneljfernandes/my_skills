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
| `use(promise)` | leer una promesa dentro de `<Suspense>` | la promesa se crea **fuera** del render (loader, `useMemo`, prop); nunca en el componente que la lee |
| `use(Context)` | leer contexto, incluso dentro de `if` | reemplaza `useContext` |
| `useTransition` | marcar actualizaciones no urgentes, o acciones fuera de `<form>` | `startTransition(async () => {...})` |

**Hacer**

- `<form action={formAction}>` con inputs **no controlados** (`name`, `defaultValue`). **React resetea el form al terminar la acción, haya salido bien o devuelto un error**: un campo escrito vuelve a su `defaultValue`. Para conservar lo escrito cuando la acción devuelve un error, la acción devuelve también los valores enviados en el estado y cada campo toma `defaultValue={state.values.x}` (ejemplo `NameForm` abajo).
- `<Form>` y `fetcher.Form` de React Router **no** borran los campos después de una action; ahí no hace falta devolver los valores. Un formulario de alta que sí debe vaciarse tras el éxito, lo resetea a mano (`formRef.current?.reset()`).
- Campos que dependen unos de otros (elegir un servicio filtra los profesionales) pueden ser controlados (`value` + `onChange`) **dentro de un `<Form>` del router**, que no entra en pelea con un reset.
- Errores **esperables**: devolverlos como estado (`{ status: "error", fieldErrors }`) y pintarlos junto al campo. Son esperables `validation` (422), `conflict` (409: horario ocupado, nombre repetido) y los fallos de conexión (`network`, `timeout`): en todos la persona quiere reintentar **sin perder lo que escribió**. Mandarlos a la boundary borra el formulario.
- Errores **inesperados** (500, `forbidden`, `unauthorized`): relanzarlos. Llegan a la Error Boundary más cercana.
- Estado de la acción como **unión discriminada** (`idle | success | error`).
- `useOptimistic` + callback al padre (`onOrdered`) para que la fuente de verdad se actualice. Si la acción falla, el valor optimista se revierte solo.
- Botón de submit deshabilitado + `aria-busy` mientras está pendiente. La fuente de `pending` depende del formulario:

  | Formulario | Fuente de `pending` |
  |---|---|
  | `<form action={fn}>` | `useFormStatus()` en un componente **hijo**, o el tercer valor de `useActionState` |
  | `<Form method="post">` del router | `useNavigation().state === "submitting"` (también sirve `useFormStatus()` en un hijo) |
  | `fetcher.Form` | `fetcher.state !== "idle"` |

  Las cuatro fuentes funcionan; usar la del tipo de formulario que se tiene.
- `Idempotency-Key` por intento en mutaciones no idempotentes, solo si el servidor deduplica (ver `building-axios-clients`).
- En rutas con React Router, para mutaciones de página preferir `action` + `<Form>` del router (revalida loaders solo). Usar `useActionState` para widgets locales.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `useState(isLoading)` + `onSubmit` + `try/finally` | boilerplate, estados inconsistentes | `useActionState` |
| `useFormStatus` en el mismo componente que el `<form>` | `pending` siempre `false` | componente hijo |
| `<form action>` + error devuelto sin devolver los valores | React resetea el form y la persona pierde lo que escribió | devolver `values` en el estado y usarlos como `defaultValue` |
| `use(fetch(...))` dentro del componente | promesa nueva en cada render → loop infinito | promesa cacheada (loader / `useMemo` / prop) |
| Setter optimista fuera de una transition | warning y sin rollback automático | llamarlo dentro de la Action |
| Tragar errores inesperados en la acción | la UI queda en estado inválido sin aviso | relanzar → Error Boundary |
| Inputs controlados en forms con action | pelea con el reset automático; renders por tecla | `defaultValue` + `name` |
| `useFormState` (nombre del canary) | API vieja | `useActionState` |

## Ejemplos

Conservar lo escrito tras un error devuelto (la acción devuelve los valores enviados y el campo los usa como `defaultValue`):

```tsx
import { useActionState, type ReactNode } from "react";

interface NameFormState {
  error: string | null;
  saved: boolean;
  values: { name: string };
}

export function NameForm({ save }: { save: (name: string) => Promise<string | null> }): ReactNode {
  const [state, formAction, pending] = useActionState<NameFormState, FormData>(
    async (_previous, formData) => {
      const name = String(formData.get("name") ?? "");
      const error = await save(name); // null = guardado; texto = error esperable de validación
      // Con error se devuelven los valores para conservarlos; con éxito, vacíos (el form se limpia).
      return { error, saved: error === null, values: { name: error === null ? "" : name } };
    },
    { error: null, saved: false, values: { name: "" } },
  );

  return (
    <form action={formAction}>
      <input name="name" aria-label="name" defaultValue={state.values.name} />
      {state.error ? <p role="alert">{state.error}</p> : null}
      {state.saved ? <p role="status">Guardado</p> : null}
      <button type="submit" disabled={pending} aria-busy={pending}>Guardar</button>
    </form>
  );
}
```

Formulario con `useActionState` + `useFormStatus` + `useOptimistic` (verificado con `tsc --strict`, `exactOptionalPropertyTypes`):

```tsx
import { useActionState, useOptimistic, type ReactNode } from "react";
import { useFormStatus } from "react-dom";

import { isApiRequestError } from "../../lib/http/errors";
import { ordersApi, type Order, type Product } from "./api";

type FormState =
  | { status: "idle" }
  | { status: "success"; order: Order }
  | { status: "error"; message: string; fieldErrors: Record<string, string>; values: { quantity: string } };

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
  /** El padre actualiza su fuente de verdad (revalidar loader, invalidar cache...). */
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
      return { status: "success", order };
    } catch (error) {
      if (isApiRequestError(error)) {
        // Esperables: se muestran junto al campo y el form conserva la cantidad escrita.
        switch (error.error.kind) {
          case "validation":
          case "conflict":
            return {
              status: "error",
              message: error.error.problem?.detail ?? "Revisá los datos",
              fieldErrors: error.error.kind === "validation" ? error.error.fieldErrors : {},
              values: { quantity: rawQuantity },
            };
          case "network":
          case "timeout":
            return { status: "error", message: "Sin conexión. Probá de nuevo.", fieldErrors: {}, values: { quantity: rawQuantity } };
          default:
            break;
        }
      }
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
      {state.status === "success" ? <p role="status">Orden #{state.order.id} creada</p> : null}
      <SubmitButton />
    </form>
  );
}
```

`use(promise)` con Suspense + Error Boundary:

```tsx
import { Suspense, use, useMemo, type ReactNode } from "react";

/** use(promise) suspende hasta que resuelve; si rechaza, la ErrorBoundary lo atrapa. */
function StockValue({ stockPromise }: { stockPromise: Promise<number> }): ReactNode {
  const stock = use(stockPromise);
  return <span>{stock} unidades</span>;
}

export function ProductStock({ productId }: { productId: number }): ReactNode {
  // La promesa se crea UNA vez por productId. Crearla en cada render = request infinita.
  const stockPromise = useMemo(
    () => ordersApi.getProduct(productId).then((product) => product.stock),
    [productId],
  );
  return (
    <ErrorBoundary scope="product-stock" fallback={DefaultFallback} resetKeys={[productId]}>
      <Suspense fallback={<span aria-busy="true">…</span>}>
        <StockValue stockPromise={stockPromise} />
      </Suspense>
    </ErrorBoundary>
  );
}
```

Acción fuera de un `<form>` con `useTransition`:

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

- [ ] Ningún formulario de página usa `useState` para `isLoading`/`isSubmitting`. Un componente de extensión sin ruta propia puede usar un `useState(enviando)` junto a `useRevalidator()` (ver `routing-with-react-router`).
- [ ] Los botones de submit se deshabilitan mientras está pendiente, con la fuente de `pending` que corresponde a su tipo de formulario (tabla de arriba).
- [ ] Un error esperable devuelto por la acción no borra lo que la persona escribió (`action_keeps_values_after_returned_error`).
- [ ] Los errores 422, 409 y de conexión se muestran junto al campo. Un error 500 simulado termina en la Error Boundary, no en un form congelado.
- [ ] La UI optimista se revierte sola al forzar un fallo de la API (probarlo con la red en "offline").
- [ ] Toda promesa leída con `use()` se crea fuera del componente que la lee.
- [ ] `tsc --noEmit` estricto pasa.

## Skills relacionadas

- `handling-react-errors`: dónde terminan los errores relanzados.
- `routing-with-react-router`: `action` + `<Form>` para mutaciones de página.
- `building-axios-clients`: `ApiRequestError` y `fieldErrors` tipados.
