---
name: choosing-ssr-or-spa
description: Use when deciding the rendering architecture of a React frontend - keeping a client-side SPA (Vite + React Router data mode) versus server-side rendering or pre-rendering (React Router framework mode, formerly Remix, or Next.js) - or when facing SEO/indexing problems, poor LCP on mobile, social link previews, a request to "migrate to Next.js", or choosing hosting (static CDN vs Node server vs Vercel).
domain: frontend
tags: [react, ssr, spa, nextjs, react-router, remix, vite, architecture-decision, seo, performance]
triggers: [SSR, SPA, "server-side rendering", "Next.js", Remix, "framework mode", prerender, SSG, SEO, LCP, "Core Web Vitals", "migrar a Next", hydration, "React Server Components", RSC, Vite]
---

# SSR vs SPA: guía de decisión técnica

SSR no es "más moderno": es **un servidor más que operar** a cambio de HTML útil en la primera respuesta. Se elige por requisitos medibles (SEO, LCP, previews sociales) y no por moda. La decisión se documenta como ADR.

## Contexto y reglas

Opciones (de menor a mayor costo operativo):

| Opción | Qué entrega | Infra | Encaja con |
|---|---|---|---|
| **SPA** (Vite + React Router *data mode*) | HTML vacío + JS; datos vía API | estáticos (CDN/nginx) | apps detrás de login, dashboards, backoffice; backend separado (FastAPI) |
| **SPA + pre-render** (RR *framework mode* con `ssr: false` + `prerender`) | HTML estático en build para rutas públicas conocidas | estáticos | landing/pricing/docs + app privada en el mismo repo |
| **SSR** (RR *framework mode* con `ssr: true`) | HTML por request con datos; loaders en servidor | Node (contenedor/serverless) | contenido público dinámico + SEO, migrando desde una SPA con React Router |
| **Next.js** (App Router, RSC) | SSR/streaming/RSC, caché granular | Node / Vercel | greenfield con contenido público grande (e-commerce, media), equipo dispuesto a adoptar RSC |

"Remix" para React es hoy React Router en **framework mode**: Remix v2 se fusionó en React Router v7. Una SPA hecha con loaders/actions de React Router (ver `routing-with-react-router`) migra a framework mode **sin reescribir rutas**: es el camino de menor costo hacia SSR.

Matriz de decisión:

| Pregunta | Sí → | No → |
|---|---|---|
| ¿Las páginas que importan son públicas y necesitan indexarse o previews sociales? | pre-render o SSR | SPA |
| ¿Ese contenido se conoce en build (marketing, docs, catálogo chico)? | pre-render (sin servidor) | SSR |
| ¿LCP p75 en mobile > 2.5 s por culpa del JS (no del backend)? | SSR/streaming ayuda | optimizar bundle/API antes |
| ¿Toda la app está detrás de login? | SPA | (seguir evaluando) |
| ¿El equipo puede operar un runtime Node en producción (logs, escalado, cold starts)? | SSR viable | SPA o pre-render |
| ¿Ya usan React Router con loaders/actions? | RR framework mode | evaluar Next.js |
| ¿Quieren RSC, caché por componente y el ecosistema Vercel? | Next.js | RR framework mode |

```dot
digraph ssr_decision {
  "¿Contenido público que debe indexarse?" [shape=diamond];
  "¿Se conoce en build?" [shape=diamond];
  "¿Ya usan React Router data mode?" [shape=diamond];
  "SPA (Vite + RR data mode)" [shape=box];
  "Pre-render (RR framework, ssr:false + prerender)" [shape=box];
  "SSR con RR framework mode" [shape=box];
  "Next.js (App Router)" [shape=box];

  "¿Contenido público que debe indexarse?" -> "SPA (Vite + RR data mode)" [label="no"];
  "¿Contenido público que debe indexarse?" -> "¿Se conoce en build?" [label="sí"];
  "¿Se conoce en build?" -> "Pre-render (RR framework, ssr:false + prerender)" [label="sí"];
  "¿Se conoce en build?" -> "¿Ya usan React Router data mode?" [label="no"];
  "¿Ya usan React Router data mode?" -> "SSR con RR framework mode" [label="sí"];
  "¿Ya usan React Router data mode?" -> "Next.js (App Router)" [label="no / greenfield"];
}
```

**Hacer**

- Medir antes de decidir: Lighthouse/PageSpeed (LCP, INP, CLS en mobile, p75 de RUM si existe), Search Console (páginas no indexadas), tamaño del bundle inicial.
- Agotar primero las optimizaciones de SPA cuando el problema es rendimiento: code-splitting por ruta, loaders en paralelo, imágenes, caché HTTP de la API.
- Separar **sitio público** (pre-render/SSR) de **app privada** (SPA) cuando conviven: requisitos opuestos.
- Con SSR, mantener el backend FastAPI como fuente de verdad. Los loaders de servidor son un BFF delgado que reenvía cookies/tokens, no un segundo backend con reglas de negocio.
- Registrar la decisión: contexto, opción elegida, costo operativo aceptado. Con **métricas** si la decisión se toma por rendimiento o SEO. Si **todo el producto está detrás de login**, la matriz ya lo resuelve (SPA) sin medir nada: alcanza con registrar ese motivo. El registro puede vivir en un ADR o en cualquier documento de decisiones versionado en el repo.
- Si la elección involucra Vercel (Next.js, Edge, despliegue), cargar las skills oficiales correspondientes desde `vercel-index`.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| Migrar a Next.js "porque sí" | reescritura, servidor nuevo y problemas reales sin resolver | matriz + métricas |
| SSR para un dashboard detrás de login | costo de servidor sin beneficio de SEO | SPA |
| Lógica de negocio duplicada en loaders de servidor y en FastAPI | dos fuentes de verdad | loader = proxy delgado a la API |
| Acceder a `window`/`localStorage` durante el render en SSR/pre-render | errores de hidratación o crash en build | efectos o `clientLoader` |
| Tokens en `localStorage` con SSR | el servidor no los ve y el SSR renderiza como anónimo | cookie httpOnly |
| SSR sin caché ni límites | TTFB alto, servidor saturado | caché HTTP/CDN y streaming |

## Ejemplos

SPA actual (Vite + data mode): ver `routing-with-react-router`. Primer paso hacia framework mode sin servidor, el "SPA Mode", que pre-renderiza el shell en build:

```ts
// react-router.config.ts (framework mode)
import type { Config } from "@react-router/dev/config";

export default {
  ssr: false,                                 // sin servidor en runtime: se sirve como estáticos
  prerender: ["/", "/pricing", "/docs"],      // HTML estático para las rutas públicas
} satisfies Config;
```

Con `ssr: false`, los loaders que llaman a la API desde el navegador pasan a `clientLoader`:

```tsx
// app/routes/product-detail.tsx (framework mode)
import type { Route } from "./+types/product-detail";

export async function clientLoader({ params, request }: Route.ClientLoaderArgs) {
  return ordersApi.getProduct(Number(params.productId), { signal: request.signal });
}

export default function ProductDetail({ loaderData }: Route.ComponentProps) {
  return <h1>{loaderData.name}</h1>;
}
```

Cuando las métricas lo justifiquen, `ssr: true` y `loader` de servidor (BFF delgado que reenvía la cookie):

```tsx
import { data } from "react-router";
import type { Route } from "./+types/product-detail";

export async function loader({ params, request }: Route.LoaderArgs) {
  const response = await fetch(`${process.env.API_URL}/api/v1/products/${params.productId}`, {
    headers: { cookie: request.headers.get("cookie") ?? "" },
    signal: request.signal,
  });
  if (response.status === 404) throw data("No encontrado", { status: 404 });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return (await response.json()) as Product;
}
```

Plantilla de ADR:

```markdown
# ADR-00X: Arquitectura de renderizado del frontend
- Contexto: <app privada / sitio público>, métricas actuales (LCP p75 mobile, páginas indexadas, bundle inicial).
- Decisión: <SPA | pre-render | SSR RR framework | Next.js>.
- Alternativas descartadas y por qué.
- Costo aceptado: <servidor Node, caché, observabilidad del runtime, cold starts>.
- Criterio de revisión: <métrica y umbral que reabre la decisión>.
```

## Checklist de verificación

- [ ] Si la decisión es por rendimiento o SEO, cita métricas reales (LCP/INP p75, indexación, bundle), no preferencias. Si todo está detrás de login, registra ese motivo y no necesita métricas.
- [ ] Si se elige SPA, las rutas públicas que necesitan SEO están cubiertas con pre-render o con un sitio aparte.
- [ ] Si se elige SSR, hay plan de operación del runtime (logs JSON, métricas, trazas, escalado, caché).
- [ ] Ningún render accede a APIs de navegador fuera de efectos o `clientLoader`.
- [ ] La lógica de negocio sigue en el backend; los loaders de servidor solo orquestan.
- [ ] La decisión está registrada en un documento versionado en el repo (ADR o equivalente).

## Skills relacionadas

- `routing-with-react-router`: la base de data mode que hace barata la migración.
- `vercel-index`: skills oficiales de Vercel (Next.js, despliegue, Edge, AI SDK).
- `optimizing-react-renders`: rendimiento del lado cliente antes de cambiar de arquitectura.
