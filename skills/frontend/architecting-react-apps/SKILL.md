---
name: architecting-react-apps
description: Use when structuring or extending a React 19 + TypeScript application - folder/feature layout, where data fetching and business logic live, extracting custom hooks, component APIs, composition vs prop drilling, context, compound components - or when components grow past ~200 lines, props are passed through 3+ levels, fetch/axios calls live inside components, or the same logic is copy-pasted across screens.
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
├── lib/                     # infraestructura sin UI: http/, telemetry.ts, hooks genéricos
├── components/              # UI reutilizable y agnóstica del dominio (Button, Tabs, ErrorBoundary)
├── features/<feature>/      # todo lo de una capacidad de negocio
│   ├── api.ts               # funciones tipadas que llaman a la API (nunca axios en componentes)
│   ├── hooks.ts             # lógica: estado, efectos, derivaciones
│   ├── <Componente>.tsx     # presentación
│   └── index.ts             # API pública de la feature
└── routes/                  # módulos de ruta: loader/action/Component (finos, delegan en features)
```

**Hacer**

- **Dirección de dependencias**: `routes → features → components/lib`. Una feature no importa internals de otra; si lo necesita, la pieza sube a `components/` o `lib/`.
- **Custom hook** cuando un componente mezcla estado + efectos + derivaciones. El componente queda como función pura de lo que el hook devuelve. Estados asíncronos como **unión discriminada** (`idle | loading | success | error`), nunca 3 booleanos.
- **Server state** (datos de la API): loaders del router para datos de página. Para cache compartido, reintentos e invalidación entre pantallas, una librería de server state (TanStack Query) en lugar de reinventarla en `useEffect`.
- **Composición antes que props**: si un componente intermedio solo reenvía props, pasar `children`/slots (`header`, `actions`) desde arriba.
- **Compound components** (`<Tabs><Tabs.Tab/><Tabs.Panel/></Tabs>`) con context privado, para componentes con partes coordinadas.
- **Context** para valores que cambian poco y muchos leen (sesión, tema, feature flags). Separar contextos por frecuencia de cambio. React 19: `<Context value>` y `use(Context)`.
- **Props tipadas como contrato**: `interface XProps`, callbacks `onX`, sin `any`. Uniones discriminadas en vez de combinaciones de booleanos (`variant: "primary" | "danger"`).
- `ref` como prop común (React 19): sin `forwardRef`.
- Componentes < ~150 líneas. Si crece, extraer hook o subcomponentes.

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

Hook que encapsula datos + cancelación (verificado con `tsc --strict`, `exactOptionalPropertyTypes`):

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

/** Lógica de datos fuera del componente: el componente solo pinta `state`. */
export function useProductSearch(query: string): AsyncState<Product[]> {
  const debounced = useDebouncedValue(query.trim(), 300);
  const [state, setState] = useState<AsyncState<Product[]>>({ status: "idle" });

  useEffect(() => {
    if (debounced.length < 2) {
      setState({ status: "idle" });
      return;
    }
    const controller = new AbortController(); // cancela la búsqueda anterior: sin race conditions
    setState({ status: "loading" });
    ordersApi
      .listProducts({ signal: controller.signal })
      .then((page) => {
        const needle = debounced.toLowerCase();
        setState({ status: "success", data: page.items.filter((p) => p.name.toLowerCase().includes(needle)) });
      })
      .catch((error: unknown) => {
        if (isApiRequestError(error) && error.error.kind !== "canceled") {
          setState({ status: "error", error: error.error });
        }
      });
    return () => controller.abort();
  }, [debounced]);

  return state;
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

## Checklist de verificación

- [ ] `grep -rn "from \"axios\"" src/features src/components src/routes` no devuelve nada: solo `lib/http` importa axios.
- [ ] Ninguna feature importa archivos internos de otra feature.
- [ ] Los estados asíncronos son uniones discriminadas, no grupos de booleanos.
- [ ] No hay props que atraviesen 3+ componentes sin usarse.
- [ ] `tsc --noEmit` pasa con `strict`, `noUncheckedIndexedAccess` y `exactOptionalPropertyTypes`.
- [ ] Ningún componente supera ~150 líneas sin una razón documentada.

## Skills relacionadas

- `optimizing-react-renders`: cuándo memoizar (y cuándo no).
- `using-react-19-actions`: formularios y mutaciones.
- `building-axios-clients`: el `lib/http` que usan los `api.ts`.
- `routing-with-react-router`: loaders/actions como capa de datos de página.
- Skill oficial de Vercel `vercel-composition-patterns`: ver `vercel-index`.
