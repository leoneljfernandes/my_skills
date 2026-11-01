---
name: optimizing-react-renders
description: Use when a React 19 app re-renders too much or feels slow, or when deciding whether to use useMemo, useCallback, React.memo, useRef or useEffectEvent - typing lag, slow lists, effects re-subscribing on every render, stale closures in intervals/listeners, or code wrapped in memoization "just in case" - and when evaluating React Compiler.
domain: frontend
tags: [react, react-19, performance, useMemo, useCallback, useRef, react-compiler, memo]
triggers: [useMemo, useCallback, useRef, "React.memo", memo, useEffectEvent, "re-render", rerender, "React Compiler", performance, rendimiento, "stale closure", Profiler, "lista lenta", virtualization]
---

# Rendimiento en React: memoización quirúrgica

Primero se **mide** (React DevTools Profiler), después se optimiza el cuello de botella real. La memoización tiene costo (memoria + comparación + complejidad) y solo paga en casos concretos. Con **React Compiler** activo, la mayoría de la memoización manual sobra.

## Contexto y reglas

| Herramienta | Usar cuando | No usar cuando |
|---|---|---|
| `useRef` | valor mutable que **no** debe re-renderizar: ids de timers, instancias (map, editor), nodo DOM, último valor guardado | el valor se muestra en pantalla (eso es estado) |
| `useMemo` | cómputo **medido** como caro (filtrar/ordenar miles de filas, parseo), o identidad estable de un objeto pasado a un hijo `memo` o a deps de un effect | operaciones triviales (`a + b`, `.map` de 10 ítems) |
| `useCallback` | la función va a un hijo envuelto en `memo` o a deps de un effect/hook | se pasa a elementos DOM (`<button onClick>`) o a hijos sin `memo` |
| `memo(Component)` | hijo caro que re-renderiza con las mismas props porque el padre cambia por otra razón | hijo barato, o props que cambian siempre |
| `useEffectEvent` (19.2) | un effect necesita leer el último valor de props/estado **sin** re-suscribirse | lógica que debe re-ejecutarse cuando ese valor cambia |
| `useTransition` / `useDeferredValue` | actualización cara que puede esperar (filtrar una lista mientras se tipea) | actualizaciones urgentes (el texto del input) |

**Hacer**

- Medir con el Profiler (*Highlight updates* + flamegraph) antes y después de cada optimización.
- Bajar el estado: si solo un subárbol usa un estado, moverlo a ese subárbol evita re-renderizar al resto. Suele ganarle a cualquier `memo`.
- Pasar contenido como `children`: un `children` creado arriba no se re-renderiza cuando cambia el estado del contenedor.
- `memo` + `useCallback`/`useMemo` van **juntos**. Un callback estable hacia un hijo no memoizado no ahorra nada.
- `key` estable y única (id de dominio), nunca el índice en listas que se reordenan.
- Listas de cientos+ de filas: virtualización (`@tanstack/react-virtual`).
- **React Compiler** (estable desde 1.0): en proyectos nuevos, activarlo y **no** escribir memoización manual. En existentes, activarlo por directorio y quitar `useMemo`/`useCallback` redundantes con el linter (`eslint-plugin-react-hooks`).

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `useCallback` en todo handler | más código, cero beneficio sin `memo` en el hijo | solo con hijo memoizado o deps |
| `useMemo` para valores triviales | la comparación de deps cuesta más que el cálculo | calcular en render |
| Deps incompletas para "evitar renders" | stale closures: bugs sutiles con datos viejos | deps completas + `useEffectEvent` |
| Objeto/array literal como prop de un hijo `memo` | `memo` nunca acierta (identidad nueva en cada render) | `useMemo` o constante fuera del componente |
| Estado derivado en `useState` + `useEffect` | doble render y desincronización | derivar en render |
| `useRef` para algo que se muestra | la UI no se actualiza | `useState` |
| Optimizar sin medir | complejidad sin ganancia demostrada | Profiler primero |

## Ejemplos

Verificados con `tsc --strict` (React 19.3, `@types/react` 19.3):

```tsx
import { memo, useCallback, useEffect, useEffectEvent, useMemo, useRef, useState, type ReactNode, type Ref } from "react";

interface Row {
  id: number;
  name: string;
  total: number;
}

// 1) useRef: valores que NO deben provocar render (ids de timers, instancias, DOM).
export function AutoSave({ draft, save }: { draft: string; save: (text: string) => Promise<void> }): ReactNode {
  const lastSaved = useRef(draft);
  const onTick = useEffectEvent(() => {
    // useEffectEvent (React 19.2): lee siempre el `draft` actual sin re-suscribir el intervalo
    if (draft !== lastSaved.current) {
      lastSaved.current = draft;
      void save(draft);
    }
  });
  useEffect(() => {
    const id = setInterval(onTick, 5_000);
    return () => clearInterval(id);
  }, []);
  return null;
}

// 2) ref como prop (React 19): sin forwardRef.
export function SearchInput({ ref, ...props }: { ref?: Ref<HTMLInputElement>; placeholder: string }): ReactNode {
  return <input ref={ref} type="search" {...props} />;
}

// 3) memo + useCallback: SOLO juntos tienen efecto.
const RowItem = memo(function RowItem({ row, onSelect }: { row: Row; onSelect: (id: number) => void }): ReactNode {
  return (
    <li>
      <button type="button" onClick={() => onSelect(row.id)}>{row.name}</button>
    </li>
  );
});

export function Report({ rows, filter }: { rows: ReadonlyArray<Row>; filter: string }): ReactNode {
  const [selected, setSelected] = useState<number | null>(null);

  // 4) useMemo para cómputo CARO medido (miles de filas); no para `a + b`.
  const visible = useMemo(
    () => rows.filter((r) => r.name.includes(filter)).toSorted((a, b) => b.total - a.total),
    [rows, filter],
  );

  const handleSelect = useCallback((id: number) => setSelected(id), []);

  return (
    <>
      <p>Seleccionado: {selected ?? "—"}</p>
      <ul>
        {visible.map((row) => <RowItem key={row.id} row={row} onSelect={handleSelect} />)}
      </ul>
    </>
  );
}
```

Bajar el estado en vez de memoizar:

```tsx
// ❌ Cada tecla re-renderiza <ExpensiveChart/>
function Page(): ReactNode {
  const [text, setText] = useState("");
  return (<><input value={text} onChange={(e) => setText(e.target.value)} /><ExpensiveChart /></>);
}

// ✅ El estado vive donde se usa; ExpensiveChart no se entera
function SearchBox(): ReactNode {
  const [text, setText] = useState("");
  return <input value={text} onChange={(e) => setText(e.target.value)} />;
}
function Page(): ReactNode {
  return (<><SearchBox /><ExpensiveChart /></>);
}
```

React Compiler en Vite 8 + `@vitejs/plugin-react` 6. La opción `babel` del plugin ya no existe: el compilador va por `@rolldown/plugin-babel`. Verificado con `vite build`; la salida contiene el cache del compilador (`react.memo_cache_sentinel`):

```ts
// vite.config.ts
// npm i -D @rolldown/plugin-babel @babel/core babel-plugin-react-compiler
import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), babel({ presets: [reactCompilerPreset()] })],
});
```

Adopción gradual en un proyecto existente: `reactCompilerPreset({ compilationMode: "annotation" })`, que solo compila los componentes marcados con `"use memo"`. Existe además `react({ compiler: true })` (port en Rust, `oxc-transform-react`), todavía **experimental**.

## Checklist de verificación

- [ ] Cada `useMemo`/`useCallback`/`memo` se justifica con una medición del Profiler, o con la regla "hijo memo / deps de effect".
- [ ] Ningún `useCallback` se pasa solo a elementos DOM o a hijos sin `memo`.
- [ ] `eslint-plugin-react-hooks` sin warnings de `exhaustive-deps`.
- [ ] Ninguna `key` usa el índice en listas reordenables o filtrables.
- [ ] Listas de > ~300 filas están virtualizadas.
- [ ] Si React Compiler está activo, no se agrega memoización manual nueva.

## Skills relacionadas

- `architecting-react-apps`: colocación de estado y composición.
- Skill oficial `vercel-react-best-practices` (reglas de performance priorizadas): ver `vercel-index`.
