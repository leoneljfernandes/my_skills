---
name: vercel-index
description: Use when a task involves the Vercel platform or Vercel-maintained tooling - deploying to Vercel, Vercel CLI, Next.js optimization, AI SDK, Edge Runtime/Functions, Vercel Blob, KV/Redis or Postgres storage, Vercel observability, queues/workflows, feature flags - to pick and install the right official Vercel skill from skills.sh instead of improvising.
domain: frontend
tags: [vercel, nextjs, ai-sdk, deployment, edge, skills-index]
triggers: [Vercel, "vercel deploy", "vercel cli", "Next.js", "AI SDK", "Edge Functions", "Edge Runtime", "Vercel Blob", "Vercel KV", "Vercel Postgres", Upstash, Neon, "skills.sh", "npx skills add"]
---

# Índice de skills oficiales de Vercel

Mapa de las skills publicadas por Vercel en [skills.sh/vercel](https://www.skills.sh/vercel) y cuándo invocar cada una. **Relevado el 2026-10-23 y re-relevado el 2026-11-01** (la organización informa 20 fuentes y 65 skills; 16 nombres no se vieron por estar truncados en la página): el catálogo cambia, así que antes de instalar conviene confirmar en la página de la skill. La organización publica ~20 fuentes y ~60 skills; acá figuran las relevantes para esta biblioteca.

## Contexto y reglas

- Instalar **solo** la skill que el caso de uso necesita: cada skill cargada consume contexto.
- Formato de instalación por skill: `npx skills add https://github.com/<repo> --skill <slug>`. Por fuente completa: `npx skills add vercel/<fuente>`.
- Las skills de Vercel indican verificar APIs contra la documentación instalada (p. ej. `node_modules`) antes que contra la memoria del modelo. Respetarlo.
- Si un caso de uso **no tiene** skill oficial (ver "Vacíos"), no inventar una "oficial": usar la documentación del producto y las skills de esta biblioteca.

## Mapa por caso de uso

| Caso de uso | Skill oficial | Fuente | Instalar | Invocar cuando |
|---|---|---|---|---|
| Deploy y gestión con CLI | `vercel-cli` | vercel/vercel | `npx skills add https://github.com/vercel/vercel --skill vercel-cli` | deploy, env vars, dominios o logs desde terminal. La skill pide `vercel project inspect --non-interactive` antes de acciones con consecuencias |
| Deploy desde Claude Code | `deploy`, `logs`, `setup` | vercel/vercel-deploy-claude-code-plugin | `npx skills add vercel/vercel-deploy-claude-code-plugin` | flujo de despliegue y logs integrado al agente |
| Deployments protegidos | `access-protected-vercel-deployment` | vercel/vercel-plugin | `npx skills add https://github.com/vercel/vercel-plugin --skill access-protected-vercel-deployment` | previews con Deployment Protection |
| Dominios | `domains` | vercel/vercel-plugin | ídem `--skill domains` | alta y configuración de dominios |
| **Edge Functions / Edge Runtime** | `edge-runtime` | vercel/vercel-plugin | ídem `--skill edge-runtime` | funciones con runtime `edge` o Routing Middleware. La skill indica que las "Edge Functions"/"Edge Middleware" standalone están **deprecadas** y recomienda el runtime Node.js cuando sea posible (máx. 300 s en edge) |
| Arquitectura de backend en Vercel | `create-a-backend` | vercel/vercel-plugin | ídem `--skill create-a-backend` | elegir entre Functions, Queues, Workflows, Cron, Daemons y **storage** (ver Blob/KV/Postgres) |
| **AI SDK** | `ai-sdk` | vercel/ai | `npx skills add https://github.com/vercel/ai --skill ai-sdk` | `generateText`, `streamText`, tools, agentes (`ToolLoopAgent`), RAG/`embed`, `useChat`/`useCompletion` |
| Migración AI SDK v6 → v7 | `migrate-ai-sdk-v6-to-v7` | vercel/ai | ídem `--skill migrate-ai-sdk-v6-to-v7` | upgrade de major del AI SDK |
| Next.js: optimización | `next-cache-components-adoption`, `next-cache-components-optimizer`, `next-partial-prefetching-adoption`, `next-partial-prefetching-optimizer`, `next-bundle-optimizer`, `next-browser-initial-load-optimizer`, `next-dev-loop` | vercel/next.js | `npx skills add vercel/next.js` | proyectos Next.js: caché, prefetch, bundle y carga inicial |
| React: performance | `vercel-react-best-practices` | vercel-labs/agent-skills | `npx skills add https://github.com/vercel-labs/agent-skills --skill vercel-react-best-practices` | revisar/escribir componentes con foco en waterfalls, bundle y re-renders (70 reglas priorizadas). Complementa `optimizing-react-renders` |
| React: composición | `vercel-composition-patterns` | vercel-labs/agent-skills | ídem `--skill vercel-composition-patterns` | compound components, state lifting, evitar proliferación de props booleanas. Complementa `architecting-react-apps` |
| Métricas de negocio en Functions | `custom-metrics` | vercel/vercel-plugin | ídem `--skill custom-metrics` | `metric()` de `@vercel/functions` + `vc metrics` |
| Trazas en Vercel | `vercel-tracing` | vercel/vercel-plugin | ídem `--skill vercel-tracing` | OpenTelemetry con `@vercel/otel` + `vercel traces` |
| Trabajo en background | `queues` | vercel/vercel-plugin | ídem `--skill queues` | Vercel Queues (beta pública, entrega at-least-once: handlers idempotentes) |
| Feature flags | `flags-sdk` | vercel/vercel-plugin, vercel/flags | ídem `--skill flags-sdk` | flags en Next.js/SvelteKit |
| Monorepos | `turborepo` | vercel/turborepo | `npx skills add vercel/turborepo` | pipelines y caché de Turborepo |

`vercel-labs/agent-skills` es la organización de "labs" de Vercel, no la org `vercel`. Sus skills son las más instaladas del catálogo React, pero no aparecen en el índice de skills.sh/vercel.

## Vacíos: sin skill oficial (al 2026-10-23)

| Producto | Estado | Qué usar |
|---|---|---|
| **Vercel Blob** | sin skill propia; `create-a-backend` lo recomienda para "archivos y uploads de usuarios" | `create-a-backend` para la decisión + docs de Vercel Blob para la API |
| **Vercel KV** (Redis) | sin skill; `create-a-backend` deriva a "Storage integrations from the Vercel Marketplace" | integración de Redis del Marketplace + su SDK |
| **Python / FastAPI en Vercel** | ninguna skill con ese nombre en el relevamiento del 2026-11-01. `vercel-plugin/create-a-backend` y `vercel-py/iter-coroutine` no se pudieron confirmar (la página no trae descripción) | la documentación de Vercel para FastAPI: la app es una Vercel Function (instancia `app` en `main.py`, `app.py`, `index.py`…, o `[tool.vercel] entrypoint` en `pyproject.toml`). Para el diseño del backend, las skills de `backend/` de esta biblioteca |
| **Vercel Postgres** | sin skill; misma derivación al Marketplace | Postgres del Marketplace. Para el modelado y las migraciones: `modeling-postgres-with-sqlalchemy` y `migrating-with-alembic` si el backend es Python |

## Ejemplos

**Antes de llevar una SPA con backend propio a Vercel, probar tres dependencias** que en contenedores resuelve nginx y que la documentación de Vercel para FastAPI no cubre:

1. **Fallback de la SPA**: toda ruta del router del cliente debe devolver `index.html`.
2. **Proxy de `/api` al backend**: una cookie `SameSite=strict` (el refresh de `scaffolding-fastapi-backends`) solo viaja si la SPA y la API comparten sitio. La documentación no dice si hacen falta *rewrites* en `vercel.json`; confirmarlo con un despliegue de prueba.
3. **Límite de intentos de login**: en contenedores vive en nginx (`limit_req`); en Vercel hay que resolverlo en otra capa.

Estas tres están **sin probar**: se concretan con una prueba de despliegue.

Deploy de la SPA (Vite) del frontend:

```bash
npx skills add https://github.com/vercel/vercel --skill vercel-cli   # una vez
vercel project inspect --non-interactive                             # confirmar proyecto antes de actuar
vercel deploy --prod
```

Feature de chat con IA en un proyecto Next.js:

```bash
npx skills add https://github.com/vercel/ai --skill ai-sdk
npx skills add https://github.com/vercel-labs/agent-skills --skill vercel-react-best-practices
```

## Checklist de verificación

- [ ] La skill instalada corresponde al caso de uso de la tabla (no se instaló la fuente completa sin necesidad).
- [ ] Se confirmó en skills.sh que el slug sigue existiendo antes de instalar.
- [ ] Para Blob/KV/Postgres y Python/FastAPI no se citó una "skill oficial" inexistente.
- [ ] Si se usa Edge Runtime, quedó justificado por qué no alcanza el runtime Node.js.

## Skills relacionadas

- `choosing-ssr-or-spa`: decidir si Next.js/Vercel corresponde.
- `architecting-react-apps`, `optimizing-react-renders`: equivalentes propios de las skills React de Vercel.
