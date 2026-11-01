---
name: architecting-react-apps
description: Use when structuring or extending a React 19 + TypeScript application - folder/feature layout, where data fetching and business logic live, extracting custom hooks, component APIs, composition vs prop drilling, context, compound components - or when components grow past ~150 lines, props are passed through 3+ levels, fetch/axios calls live inside components, or the same logic is copy-pasted across screens.
domain: frontend
tags: [react, react-19, typescript, architecture, custom-hooks, composition, feature-folders]
triggers: [React, "arquitectura frontend", "custom hook", "prop drilling", composition, "compound components", context, "feature folders", "estructura de carpetas", children, slots, "componente gigante", TypeScript]
---

# Arquitectura modular en React 19

Los componentes **pintan**. La lógica vive en hooks, el acceso a datos en módulos `api` por feature y el estado compartido lo más cerca posible de quien lo usa. La composición (`children`, slots, compound components) reemplaza al prop drilling.

## Contexto y reglas

```text
src/
├── main.tsx                 # createRoot + RouterProvider + reporte de errores
├── router.tsx               # árbol de rutas (ver routing-with-react-router)
├── lib/                     # infraestructura sin UI: http/, telemetry.ts, action-result.ts, hooks genéricos
├── components/              # UI reutilizable y agnóstica del dominio (Button, Tabs, ErrorBoundary)
├── features/<feature>/      # todo lo de una capacidad de negocio (products, orders, auth...)
│   ├── api.ts               # funciones tipadas que llaman a la API (nunca axios en componentes)
│   ├── hooks.ts             # (opcional) lógica reutilizable: estado, efectos, derivaciones; si no hace falta, no existe
│   ├── <Componente>.tsx     # presentación
│   └── index.ts             # API pública de la feature
└── routes/                  # módulos de ruta: loader/action/Component (finos, delegan en features)
```

La **sesión** es una feature más: `features/auth/{api.ts, session.ts, index.ts}` (el tipo único `User`, `authApi`, `requireUser`, `usePrivateData`; ver `building-axios-clients` y `routing-with-react-router`). Así un componente de otra feature la importa por `@/features/auth` sin depender de `routes/`.

El `index.ts` es una lista explícita de lo público, p. ej. `features/products/index.ts`: `export { productsApi, type Product } from "./api";`.

**Alias `@/`** en toda la biblioteca: cada import que cruza carpetas de primer nivel es `@/lib/...`, `@/features/x`, `@/routes/...`; solo se usan imports relativos dentro de la misma carpeta (`./api`). Hay que configurarlo en tres lugares, porque cada herramienta resuelve por su cuenta:

```jsonc
// tsconfig.app.json (el que usa `tsc -b`) y también tsconfig.json, para el editor; sin `baseUrl`
{ "compilerOptions": { "paths": { "@/*": ["./src/*"] } } }
```

```ts
// vite.config.ts
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
});
```

La tercera es la regla de ESLint de abajo, que se apoya en que el alias es texto fijo y no necesita resolver nada.

**Hacer**

- **Dirección de dependencias**: `routes → features → components/lib`. Cualquier carpeta (otra feature **y también `routes/`**) importa una feature solo por su `index.ts` (`@/features/x`), nunca por una ruta profunda (`@/features/x/Interna`, `@/features/x/api`). Si necesita algo que no está en el `index.ts`, o lo exporta la feature, o la pieza sube a `components/` o `lib/`. `components/` y `lib/` no importan `features/` ni `routes/`; `features/` no importa `routes/`. ESLint lo hace cumplir (ver el fragmento de abajo).
- **Custom hook** cuando un componente mezcla estado + efectos + derivaciones. El componente queda como función pura de lo que el hook devuelve. Estados asíncronos como **unión discriminada** (`idle | loading | success | error`), nunca 3 booleanos.
- **Server state** (datos de la API): loaders del router para datos de página, y `useFetcher` para datos que se piden al interactuar (buscadores, autocompletar). Un `useEffect` que trae datos solo se justifica **sin router** de datos. Para cache compartido, reintentos e invalidación entre pantallas, una librería de server state (TanStack Query) en lugar de reinventarla en `useEffect`.
- **Composición antes que props**: si un componente intermedio solo reenvía props, pasar `children`/slots (`header`, `actions`) desde arriba.
- **Compound components** (`<Tabs><Tabs.Tab/><Tabs.Panel/></Tabs>`) con context privado, para componentes con partes coordinadas.
- **Context** para valores que cambian poco y muchos leen (sesión, tema, feature flags). Separar contextos por frecuencia de cambio. React 19: `<Context value>` y `use(Context)`.
- **Props tipadas como contrato**: `interface XProps`, callbacks `onX`, sin `any`. Uniones discriminadas en vez de combinaciones de booleanos (`variant: "primary" | "danger"`).
- `ref` como prop común (React 19): sin `forwardRef`.
- Componentes < ~150 líneas, medidas **por componente**, no por archivo (un archivo puede tener varios). Si uno crece, extraer hook o subcomponentes.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `axios.get` dentro del componente | sin tipado central, sin cancelación, imposible de mockear | `features/x/api.ts` + loader o hook |
| `isLoading`, `isError`, `data` como estados separados | combinaciones imposibles (`isLoading && isError`) | unión discriminada |
| Prop drilling de 3+ niveles | componentes intermedios acoplados a datos que no usan | composición o context |
| Un context global gigante | cada cambio re-renderiza toda la app | contextos chicos por dominio y frecuencia |
| `useEffect` para derivar estado de props | render doble, estado desincronizado | calcular en render (o `useMemo` si es caro) |
| Boolean props que se multiplican (`isCompact`, `isInline`, `hasIcon`…) | API combinatoria e inmantenible | `variant` + composición |
| `export default` anónimos | nombres inconsistentes en imports y DevTools | named exports |

## Ejemplos

Buscador con router: `useFetcher` pide los datos a una ruta de recurso (un `loader` sin UI), cancela la request anterior solo y no necesita efecto ni estado de carga propio. La ruta de recurso (`src/routes/product-search.ts`) va **antes** de `:productId` en el árbol, o `search` se interpretaría como un id (ver `routing-with-react-router`):

```tsx
import type { LoaderFunctionArgs } from "react-router";

import { productsApi, type Product } from "@/features/products";

export async function loader({ request }: LoaderFunctionArgs): Promise<Product[]> {
  const query = new URL(request.url).searchParams.get("q") ?? "";
  return query.length < 2 ? [] : productsApi.searchProducts(query, { signal: request.signal });
}
```

`src/features/products/ProductSearch.tsx`:

```tsx
export function ProductSearch(): ReactNode {
  const fetcher = useFetcher<Product[]>();
  return (
    <>
      <input
        type="search"
        onChange={(e) => {
          const q = e.target.value.trim();
          if (q.length >= 2) void fetcher.load(`/products/search?q=${encodeURIComponent(q)}`);
        }}
      />
      {fetcher.state === "loading" && <Spinner />}
      {fetcher.data && <ProductList items={fetcher.data} />}
    </>
  );
}
```

Sin router de datos (una app que no usa `createBrowserRouter` con loaders), el mismo buscador es un hook con efecto y cancelación. El estado `idle` y el `loading` se **derivan en el render** (a partir de la consulta y del último resultado), no con `setState` síncrono dentro del efecto: es lo que exige `react-hooks/set-state-in-effect`, de la configuración `recommended` de `eslint-plugin-react-hooks` (verificado (test) con `tsc --strict`, `exactOptionalPropertyTypes` y ESLint):

```tsx
type AsyncState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiError };

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/** Resultado de la última búsqueda terminada, con la consulta a la que corresponde. */
interface Settled {
  query: string;
  outcome: { status: "success"; data: Product[] } | { status: "error"; error: ApiError };
}

/** Lógica de datos fuera del componente: el componente solo pinta `state`. */
export function useProductSearch(query: string): AsyncState<Product[]> {
  const debounced = useDebouncedValue(query.trim(), 300);
  const [settled, setSettled] = useState<Settled | null>(null);
  const idle = debounced.length < 2;

  useEffect(() => {
    if (idle) return;
    const controller = new AbortController(); // cancela la búsqueda anterior: sin race conditions
    productsApi
      .searchProducts(debounced, { signal: controller.signal })
      .then((data) => setSettled({ query: debounced, outcome: { status: "success", data } }))
      .catch((error: unknown) => {
        if (isApiRequestError(error) && error.error.kind !== "canceled") {
          setSettled({ query: debounced, outcome: { status: "error", error: error.error } });
        }
      });
    return () => controller.abort();
  }, [debounced, idle]);

  if (idle) return { status: "idle" };
  if (settled?.query !== debounced) return { status: "loading" }; // la consulta cambió: el resultado guardado es viejo
  return settled.outcome;
}
```

El componente solo pinta:

```tsx
export function ProductSearch(): ReactNode {
  const [query, setQuery] = useState("");
  const state = useProductSearch(query);
  return (
    <>
      <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} />
      {state.status === "loading" && <Spinner />}
      {state.status === "error" && <ErrorMessage error={state.error} />}
      {state.status === "success" && <ProductList items={state.data} />}
    </>
  );
}
```

Compound component con context privado (React 19: `use` + `<Context value>`):

```tsx
interface TabsContextValue {
  active: string;
  select: (value: string) => void;
  baseId: string;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabs(): TabsContextValue {
  const ctx = use(TabsContext); // React 19: use() lee contexto (también condicionalmente)
  if (!ctx) throw new Error("Tabs.* must be rendered inside <Tabs>");
  return ctx;
}

function Tabs({ defaultValue, children }: { defaultValue: string; children: ReactNode }): ReactNode {
  const [active, select] = useState(defaultValue);
  const baseId = useId();
  // React 19: <Context value> reemplaza a <Context.Provider value>
  return <TabsContext value={{ active, select, baseId }}>{children}</TabsContext>;
}

function Tab({ value, children }: { value: string; children: ReactNode }): ReactNode {
  const { active, select, baseId } = useTabs();
  return (
    <button type="button" role="tab" id={`${baseId}-tab-${value}`} aria-selected={active === value}
      aria-controls={`${baseId}-panel-${value}`} onClick={() => select(value)}>
      {children}
    </button>
  );
}

function Panel({ value, children }: { value: string; children: ReactNode }): ReactNode {
  const { active, baseId } = useTabs();
  if (active !== value) return null;
  return <div role="tabpanel" id={`${baseId}-panel-${value}`} aria-labelledby={`${baseId}-tab-${value}`}>{children}</div>;
}

Tabs.Tab = Tab;
Tabs.Panel = Panel;
export { Tabs };

// Uso: sin props de estado entre las partes
<Tabs defaultValue="details">
  <Tabs.Tab value="details">Detalle</Tabs.Tab>
  <Tabs.Tab value="orders">Órdenes</Tabs.Tab>
  <Tabs.Panel value="details"><ProductDetail /></Tabs.Panel>
  <Tabs.Panel value="orders"><OrderList /></Tabs.Panel>
</Tabs>
```

Prop drilling → composición:

```tsx
// ❌ Layout recibe `user` solo para pasárselo a Header → Avatar
<Layout user={user}><Dashboard /></Layout>

// ✅ El que tiene el dato arma la pieza; Layout solo ubica slots
<Layout header={<Header actions={<Avatar user={user} />} />}>
  <Dashboard />
</Layout>
```

ESLint (flat config) para hacer cumplir la dirección de dependencias. Como el alias `@/` es texto fijo, alcanza `no-restricted-imports` por grupo de carpetas, sin plugins ni resolver. Cada grupo repite la lista completa porque en flat config una regla se **reemplaza**, no se mezcla:

```js
// eslint.config.js
import tseslint from "typescript-eslint";

const axiosOnlyInLibHttp = { group: ["axios"], message: "Solo lib/http habla con axios." };
// Entre carpetas se usa el alias; el relativo solo sirve dentro de la misma carpeta.
const noRelativeUp = { group: ["../*"], message: "Importar con el alias @/ (o ./ dentro de la misma carpeta)." };
// Cualquiera (otra feature o routes/) entra a una feature por su index.ts.
const featureByIndexOnly = { group: ["@/features/*/*"], message: "Importar la feature por su index.ts (@/features/x)." };
const noFeatures = { group: ["@/features", "@/features/*"], message: "components/ y lib/ no dependen de features/." };
const noRoutes = { group: ["@/routes", "@/routes/*"], message: "Solo routes/ y router.tsx importan routes/." };

const restrict = (...patterns) => ({ "no-restricted-imports": ["error", { patterns }] });
const sources = ["src/**/*.{ts,tsx}"];

export default [
  { files: sources, languageOptions: { parser: tseslint.parser } },
  { files: sources, rules: restrict(axiosOnlyInLibHttp, noRelativeUp, featureByIndexOnly) },
  { files: ["src/components/**", "src/lib/**"], rules: restrict(axiosOnlyInLibHttp, noRelativeUp, featureByIndexOnly, noFeatures, noRoutes) },
  { files: ["src/features/**"], rules: restrict(axiosOnlyInLibHttp, noRelativeUp, featureByIndexOnly, noRoutes) },
  // Al final: es la excepción de lib/ (el único lugar que importa axios).
  { files: ["src/lib/http/**"], rules: restrict(noRelativeUp, featureByIndexOnly, noFeatures, noRoutes) },
];
```

## Checklist de verificación

- [ ] `grep -rn "from \"axios\"" src/features src/components src/routes` no devuelve nada: solo `lib/http` importa axios.
- [ ] Ni otra feature ni `routes/` importan archivos internos de una feature: `npx eslint src` falla ante `@/features/x/Interna`, ante `../features/x/api` y ante un import de `@/routes` desde `lib/` o `features/`.
- [ ] Ningún `useEffect` trae datos cuando existe el router de datos (`grep -rn "useEffect" src/features` revisado).
- [ ] Los estados asíncronos son uniones discriminadas, no grupos de booleanos.
- [ ] No hay props que atraviesen 3+ componentes sin usarse.
- [ ] `tsc --noEmit` pasa con `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes` y `erasableSyntaxOnly` (la plantilla de `npm create vite` la activa: nada de `constructor(readonly x)`, `enum` ni `namespace`).
- [ ] `eslint-plugin-react-hooks` con la configuración `recommended` completa, sin errores (incluidos `set-state-in-effect` y `refs`).
- [ ] Ningún componente supera ~150 líneas sin una razón documentada (se mide por componente).

## Skills relacionadas

- `optimizing-react-renders`: cuándo memoizar (y cuándo no).
- `using-react-19-actions`: formularios, mutaciones y `lib/action-result.ts`.
- `building-axios-clients`: el `lib/http` que usan los `api.ts` y `features/auth/api.ts`.
- `routing-with-react-router`: loaders/actions como capa de datos de página.
- Skill oficial de Vercel `vercel-composition-patterns`: ver `vercel-index`.
