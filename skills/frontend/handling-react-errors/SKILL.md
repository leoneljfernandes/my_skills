---
name: handling-react-errors
description: Use when making a React 19 app resilient to runtime errors - Error Boundaries, fallback UI, retry/reset, reporting errors to telemetry (Sentry, OpenTelemetry, custom endpoint), createRoot onUncaughtError/onCaughtError/onRecoverableError, React Router route errors - or when a single error blanks the whole page, errors are reported twice or never, or failures in event handlers and async code go unnoticed.
domain: frontend
tags: [react, react-19, error-boundary, resilience, telemetry, typescript]
triggers: ["Error Boundary", ErrorBoundary, componentDidCatch, getDerivedStateFromError, "pantalla en blanco", "white screen", onUncaughtError, onCaughtError, onRecoverableError, Sentry, telemetría, "fallback UI", react-error-boundary, useRouteError]
---

# Error Boundaries de producción + telemetría

Un error en un widget rompe **ese widget**, no la página. Cada error se reporta **una sola vez**, con contexto (zona, ruta, component stack), desde un único módulo de telemetría intercambiable.

## Contexto y reglas

Mapa de captura (qué atrapa qué y quién reporta):

| Origen del error | Lo atrapa | Reporta |
|---|---|---|
| Render/efectos de un componente dentro de `<ErrorBoundary>` propio | la boundary más cercana | `componentDidCatch` de esa boundary |
| Loader, action o render dentro de una ruta | `ErrorBoundary` de la ruta (React Router) | `<RouterProvider onError>` |
| Render fuera de toda boundary | nadie: React desmonta la app | `createRoot({ onUncaughtError })` |
| Errores de los que React se recupera solo (hydration mismatch) | React | `createRoot({ onRecoverableError })` |
| Event handlers (`onClick`) y código async suelto | **ninguna boundary** | `try/catch` en el handler, o convertirlo en Action (los errores de una Action sí llegan a la boundary) |

**Hacer**

- Un `lib/telemetry.ts` con `reportError(error, context)` y `setErrorReporter(...)`. El resto del código no conoce Sentry/OTel. `reportError` nunca lanza.
- Boundaries **por zona** (layout, sidebar, cada widget independiente, cada ruta) con `scope` para telemetría y `resetKeys` (p. ej. el id de la ruta) para recuperarse al navegar.
- Fallback útil: mensaje claro, botón **Reintentar** (`reset`) y, en dev, el mensaje del error. Nunca stack traces en producción.
- **No** configurar `onCaughtError` para reportar si las boundaries ya reportan: React lo llama también para errores atrapados y se duplicarían.
- Errores de API **esperables** (404, 403, 422) se manejan como estado o como respuesta de ruta. Las boundaries son para lo inesperado.
- Incluir el `trace_id` del backend (`ApiRequestError.traceId`) en el contexto reportado: une el error de frontend con la traza del backend.
- Alternativa lista para usar: `react-error-boundary` (v6), con API equivalente (`FallbackComponent`, `resetKeys`, `onError`).

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| Una sola boundary en la raíz | cualquier error tira la página entera | boundaries por zona/ruta |
| Reportar en `componentDidCatch` **y** en `onCaughtError` | cada error contado dos veces | un punto de reporte por origen (tabla de arriba) |
| Esperar que una boundary atrape errores de `onClick`/`setTimeout`/promesas | error silencioso | `try/catch` + estado, o Action |
| Fallback sin forma de recuperarse | el usuario tiene que recargar | `reset` + `resetKeys` |
| Mostrar `error.message`/stack en producción | filtra detalles internos | mensaje genérico; detalle en telemetría |
| Atrapar y silenciar en la boundary | bug invisible | siempre `reportError` |

## Ejemplos

`src/lib/telemetry.ts` (verificado con `tsc --strict`):

```ts
/** Punto único de reporte de errores del frontend (Sentry, OTel web, endpoint propio...). */
export interface ErrorContext {
  scope: string;
  componentStack?: string | undefined;
  route?: string | undefined;
  extra?: Record<string, unknown>;
}

export type ErrorReporter = (error: unknown, context: ErrorContext) => void;

let reporter: ErrorReporter = (error, context) => {
  console.error(`[${context.scope}]`, error, context);
};

export function setErrorReporter(next: ErrorReporter): void {
  reporter = next;
}

export function reportError(error: unknown, context: ErrorContext): void {
  try {
    reporter(error, context);
  } catch {
    // reportar nunca debe romper la app
  }
}
```

`src/components/ErrorBoundary.tsx`:

```tsx
import { Component, type ErrorInfo, type ReactNode } from "react";

import { reportError } from "../lib/telemetry";

export interface FallbackProps {
  error: Error;
  reset: () => void;
}

interface ErrorBoundaryProps {
  /** Identifica la zona en telemetría ("checkout", "sidebar"...). */
  scope: string;
  fallback: (props: FallbackProps) => ReactNode;
  /** Si alguna cambia (p. ej. el id de la ruta), la boundary se resetea sola. */
  resetKeys?: ReadonlyArray<unknown>;
  onReset?: () => void;
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

const changed = (a: ReadonlyArray<unknown> = [], b: ReadonlyArray<unknown> = []): boolean =>
  a.length !== b.length || a.some((item, i) => !Object.is(item, b[i]));

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    reportError(error, { scope: this.props.scope, componentStack: info.componentStack ?? undefined });
  }

  override componentDidUpdate(prevProps: ErrorBoundaryProps): void {
    if (this.state.error && changed(prevProps.resetKeys, this.props.resetKeys)) this.reset();
  }

  reset = (): void => {
    this.props.onReset?.();
    this.setState({ error: null });
  };

  override render(): ReactNode {
    const { error } = this.state;
    return error ? this.props.fallback({ error, reset: this.reset }) : this.props.children;
  }
}

export function DefaultFallback({ error, reset }: FallbackProps): ReactNode {
  return (
    <div role="alert">
      <p>Algo salió mal en esta sección.</p>
      {import.meta.env.DEV ? <pre>{error.message}</pre> : null}
      <button type="button" onClick={reset}>Reintentar</button>
    </div>
  );
}
```

`src/main.tsx`, con los puntos de reporte de la raíz y del router:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import type { ClientOnErrorFunction } from "react-router";
import { RouterProvider } from "react-router/dom";

import { reportError } from "./lib/telemetry";
import { router } from "./router";

// Errores de loaders/actions/render dentro de rutas (los atrapa el router).
const onRouterError: ClientOnErrorFunction = (error, { location, pattern }) => {
  reportError(error, { scope: "router", route: pattern, extra: { path: location.pathname } });
};

const container = document.getElementById("root");
if (!container) throw new Error("#root not found");

createRoot(container, {
  // Errores que ninguna boundary atrapó (la app se desmonta): siempre se reportan.
  onUncaughtError: (error, info) =>
    reportError(error, { scope: "react-uncaught", componentStack: info.componentStack }),
  // Errores de los que React se recuperó solo (p. ej. hydration mismatch).
  onRecoverableError: (error, info) =>
    reportError(error, { scope: "react-recoverable", componentStack: info.componentStack }),
  // onCaughtError no se usa: cada boundary ya reporta en componentDidCatch (evita duplicados).
}).render(
  <StrictMode>
    <RouterProvider router={router} onError={onRouterError} />
  </StrictMode>,
);
```

Conectar el proveedor real una vez (ejemplo con Sentry):

```ts
import * as Sentry from "@sentry/react";
import { isApiRequestError } from "./lib/http/errors";

setErrorReporter((error, { scope, componentStack, route, extra }) => {
  Sentry.captureException(error, {
    tags: { scope, route },
    extra: { ...extra, componentStack, backendTraceId: isApiRequestError(error) ? error.traceId : undefined },
  });
});
```

Errores en event handlers (no los atrapa ninguna boundary):

```tsx
const onExport = async (): Promise<void> => {
  try {
    await reportsApi.export(filters);
  } catch (error) {
    reportError(error, { scope: "reports.export" });
    setNotice("No pudimos exportar. Probá de nuevo.");
  }
};
```

## Checklist de verificación

- [ ] Forzar `throw` en un widget: solo ese widget muestra el fallback; el resto de la página sigue usable.
- [ ] "Reintentar" recupera el widget cuando la causa desapareció; navegar a otra ruta resetea la boundary (`resetKeys`).
- [ ] Cada error forzado aparece **exactamente una vez** en la telemetría, con `scope` y `componentStack`/`route`.
- [ ] Un loader que lanza un error inesperado muestra el `ErrorBoundary` de la ruta y llega vía `onError`.
- [ ] Los errores de API reportados incluyen el `trace_id` del backend.
- [ ] En el build de producción el fallback no muestra mensajes internos.

## Skills relacionadas

- `routing-with-react-router`: `ErrorBoundary` de ruta y `rethrowAsRouteError`.
- `building-axios-clients`: `ApiRequestError` con `traceId`.
- `using-react-19-actions`: errores relanzados desde Actions.
