# Auditoría de la rama FRONTEND

Revisión sobre el commit `54d8c96`. No se tocó nada dentro de `/home/leonel/my_skills` (`git status` limpio al terminar).

Rutas abreviadas: `axios` = `skills/frontend/building-axios-clients/SKILL.md`, `routing` = `routing-with-react-router`, `actions` = `using-react-19-actions`, `errors` = `handling-react-errors`, `arch` = `architecting-react-apps`, `renders` = `optimizing-react-renders`, `ssr` = `choosing-ssr-or-spa`, `vercel` = `skills/frontend/vercel-index.md`, `security` y `docker` = `skills/backend/scaffolding-fastapi-backends/references/{security,docker}.md`, `be-errors` = `skills/backend/handling-fastapi-errors/SKILL.md`.

## Cómo se ejecutó

Todo vive en `/tmp/claude-1000/-home-leonel-my-skills/927a91bb-bc0d-4938-a40b-4a8225428464/scratchpad/audit/frontend/`:

- `repo/`: copia del repo. `npm test` en `tests/snippets/web` da 13/13 en verde.
- `app/`: proyecto armado **con los bloques publicados** (`app/gen.py` los extrae igual que `tests/snippets/extract.py`), con React 19.3.1, React Router 8.5.1, Axios 1.21.0, Vite 8.3.5, `@vitejs/plugin-react` 6.1.2, ESLint 9 y `eslint-plugin-react-hooks` 7.1.1. Los tests de conducta están en `app/t/` (23/23 en verde: afirman el comportamiento observado, incluidos los defectos, y lo imprimen con `console.log`).
- `tpl/`: plantilla real de `npm create vite --template react-ts`.

Límites del arnés, para leer bien los resultados:

- `window.location.assign` se reemplaza por un espía (jsdom no navega), así que no se reproduce la carrera real entre la navegación dura y el router.
- `t/setup.ts` adapta `Request.formData` porque jsdom y `undici` no comparten clases. Una primera corrida sin este adaptador daba resultados falsos en las actions; se descartaron.
- El backend es un adapter falso de Axios, con cuerpos copiados de `be-errors`.

## Lo que se comprobó y está bien (no reportar)

- Todos los bloques de React compilan con `strict`, `exactOptionalPropertyTypes` y `noUncheckedIndexedAccess`, si se les agregan los imports omitidos y los métodos que faltan en `ordersApi` (ver FE-15).
- `vite build` con el config de `renders:133-143`: un chunk por ruta lazy y `memo_cache_sentinel` en la salida.
- Peer deps de `react-router@8.5.1`: React >=19.2.7 y Node >=22.22, como dice `routing:13`.
- `useFormStatus` en un hijo de `<Form>` del router sí pasa a `pending` (`actions:38`). `<Form>` y `fetcher.Form` conservan los valores (`actions:27`).
- `canceled` relanzado no llega a `onError` (`routing:339`).
- El 403 de `requirePermission` se ve dentro del layout. `HydrateFallback` deja el layout visible. Un error de render dentro de `StrictMode` llega una sola vez a `onError`.
- `ProblemDetails` coincide con `be-errors:20` y con `_validation_error`.
- Rutas `/auth/token`, `/auth/refresh`, `/auth/me`, `access_token`, form-data, nginx `/api/` y fallback de la SPA coinciden con `security` y `docker`.
- `trace_id` de 32 hex es consistente con `current_trace_id()`.
- `QuickOrderForm` conserva la cantidad tras un 409.

---

## Hallazgos de severidad alta

### FE-01: Dos dueños de la redirección al expirar la sesión, con distinto `next`

- **Severidad:** alta
- **Tipo:** b, c
- **Evidencia:**
  - `axios:169`: `/** Refresh falló: la sesión terminó (redirigir a /login, limpiar estado). */`
  - `axios:325-329`: `const { pathname, search } = window.location; window.location.assign(\`/login?next=${encodeURIComponent(pathname + search)}\`);`
  - `routing:23`: "sin usuario → `throw redirect("/login?next=...")`, con `next` = `pathname + search` (la pantalla con sus filtros)"
  - `routing:127`: `if (isApiRequestError(error) && error.error.kind === "unauthorized") return null;`
  - `routing:147-149`: `throw redirect(\`/login?next=${encodeURIComponent(url.pathname + url.search)}\`);`
  - `actions:30`: "Errores **inesperados** (500, `forbidden`, `unauthorized`): relanzarlos."
- **Confirmación:** ejecutado (`app/t/session.test.tsx`, con `router.tsx`, `auth.ts`, `lib/http/index.ts` y `client.ts` publicados).
  - Primera visita sin sesión: `assign` y router redirigen los dos.
  - Sesión vencida navegando de `/products` a `/products/7?x=1`: `assign` recibe `/login?next=%2Fproducts`, y el router `/login?next=%2Fproducts%2F7%3Fx%3D1`.
  - Loader hijo con 401: además aparece "Error inesperado" y `onError` recibe `ApiRequestError: unauthorized`.
- **Impacto:** durante una navegación `window.location` todavía es la página anterior, así que la navegación dura lleva un `next` equivocado: tras loguearse, la persona no vuelve adonde iba. Esto contradice la regla de `routing:23`. Cada expiración recarga toda la app, puede mostrar un instante la pantalla de error y genera telemetría de un caso esperable.
- **Plan de corrección:** el canónico es el router, porque es el único que conoce el destino.
  - `axios`, `lib/http/index.ts`: `onSessionExpired` se inyecta desde `main.tsx` y usa `router.navigate("/login?next=" + destino)`, con `destino = router.state.navigation.location ?? router.state.location`. Así `lib/http` no importa `router`.
  - `routing`, `rethrowAsRouteError`: agregar `case "unauthorized"`, que lanza un `redirect` en vez de ir a la boundary. Documentar en un solo lugar quién redirige.
  - `actions:30`: quitar `unauthorized` de los inesperados y remitir a esa regla.
  - Test nuevo en `tests/snippets/web`: `session_expiry_next_keeps_target`.
- **Decisión requerida:** ¿la redirección se hace siempre con el router (sin recarga) o con recarga para limpiar todo el estado en memoria? Recomiendo el router, limpiando el estado de forma explícita.
- **Otros dominios afectados:** ninguno. El contrato de 401 no cambia.

### FE-02: La action de ejemplo de `routing` incumple su propia regla: 409 borra el form y un 422 no muestra nada

- **Severidad:** alta
- **Tipo:** a, b
- **Evidencia:**
  - `routing:31`: "**Qué es "esperable" en una action** [...]: `validation` (422), `conflict` (409, p. ej. horario ocupado) y los fallos de conexión [...] porque en todos la persona necesita **conservar lo que escribió**."
  - `routing:231-242`: el `switch` solo tiene `case "validation"`, `case "network"`, `case "timeout"` y `default: break`. Falta `conflict`.
  - `routing:236`: `return { fieldErrors: error.error.fieldErrors };`
  - `routing:262`: `{result?.fieldErrors.quantity ? <p role="alert">...`: solo pinta `quantity`.
  - `routing:215,223`: "garantizado por el middleware requireUser" y `customer_email: user?.email ?? ""` (`privateLoader`, en cambio, lanza en `routing:176`).
  - `routing:22`: "Errores esperables (422)", más estrecho que `routing:31`.
  - Comparar con `actions:151`, que sí maneja `conflict`, y con `actions:154`, que tiene `message`.
- **Confirmación:** ejecutado (`app/t/app.test.tsx`, casos L, M y N, con el módulo de ruta publicado).
  - 409: "Error inesperado", el formulario desaparece y `onError` se llama 1 vez.
  - 422 `business_rule_violated`: `alerts: []`.
  - 422 Pydantic sobre `customer_email`: `alerts: []`.
- **Impacto:** quien copie el ejemplo pierde lo escrito en un 409, justo lo que la regla quiere evitar. En cualquier 422 que no sea de `quantity` el botón parece no hacer nada, sin error alguno.
- **Plan de corrección:** el canónico es `routing:31`, que además coincide con `actions:29`.
  - `routing:230-243`: agregar `case "conflict"` y devolver `{ message, fieldErrors }`, con `message = problem?.detail ?? "Revisá los datos"`.
  - `routing:262`: pintar `result.message` si no hay error de campo.
  - `routing:239`: mover "Sin conexión" de `fieldErrors.quantity` a `message`.
  - `routing:223`: leer `user` con un helper que lance, igual que `privateLoader`.
  - `routing:22`: remitir a `routing:31`.
  - Test: agregar el bloque a `tests/snippets/generate.py` y probar 409 y 422 sin campo.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno. `be-errors` ya emite estas formas.

### FE-03: `NewProductForm` resetea durante el render y borra lo que se está escribiendo

- **Severidad:** alta
- **Tipo:** a, b
- **Evidencia:**
  - `routing:289-290`: `// Alta con éxito: vaciar el formulario. Se hace al detectar el resultado, no en un efecto.` y `if (fetcher.state === "idle" && fetcher.data?.ok) formRef.current?.reset();`
  - `routing:295`: `<button type="submit">Agregar</button>`, sin `disabled`.
  - `actions:33`: "Botón de submit deshabilitado + `aria-busy` mientras está pendiente."
  - `actions:234`: "Los botones de submit se deshabilitan mientras está pendiente".
  - `renders:32`: recomienda `eslint-plugin-react-hooks` y React Compiler.
- **Confirmación:** ejecutado.
  - `app/t/router.test.tsx` caso H: tras un alta exitosa, se escribe "dos" y se re-renderiza el padre: `valor tras re-render del padre: ""`.
  - `eslint-plugin-react-hooks` 7.1.1 `recommended`: `react-hooks/refs: Cannot access refs during render` en esa línea.
- **Impacto:** `fetcher.data.ok` sigue en `true` después del primer éxito, de modo que cada re-render posterior vacía el formulario mientras se carga el siguiente registro. Además falla el linter que `renders:32` recomienda. Sin `disabled`, un doble clic crea dos altas.
- **Plan de corrección:** el canónico es el reset único por resultado, con la regla de `actions:33` para el botón.
  - `routing:286-298`: usar un `useEffect` que dependa de `fetcher.data` y resetee una vez, o bien `key` en el form con un contador de altas. Quitar el comentario "no en un efecto". Agregar `disabled` y `aria-busy`.
  - `actions:27`: remitir a ese ejemplo.
  - Test: agregar el bloque a `generate.py` con el caso "escribir, re-renderizar, conservar".
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### FE-04: Una contraseña mala termina en la Error Boundary según las reglas vigentes

- **Severidad:** alta
- **Tipo:** e
- **Evidencia:**
  - `routing:31`: esperables `validation`, `conflict`, `network`, `timeout`; "Todo lo demás se lanza."
  - `actions:30`: "Errores **inesperados** (500, `forbidden`, `unauthorized`): relanzarlos."
  - `axios:25`: "mapear esos y relanzar el resto con `throw error`".
  - `axios:333`: "un login fallido no se reintenta: cada intento cuenta contra el límite".
  - `be-errors:22`: "el cliente no podría distinguir credenciales malas de token vencido".
  - `security:246`: "contraseña mala (401 [...] `code == "invalid_credentials"`)".
  - `docker:118-120`: `limit_req_status 429` en `/api/v1/auth/token`.
  - `routing:69`: `{ path: "login", lazy: () => import("./routes/login") }`: ninguna skill publica ese módulo.
- **Confirmación:** ejecutado (`app/t/real.test.tsx` caso U).
  - `authApi.login` con 401 da `unauthorized` / `invalid_credentials`, sin refresh ni `onSessionExpired`.
  - Con 429 da `{"kind":"rate_limited","retryAfterMs":null}`.
  - El caso F confirma que lo lanzado desde una action muestra "Error inesperado" y llama a `onError`.
  - La suma de ambos (un login completo) es por lectura, porque no hay módulo publicado.
- **Impacto:** el error más común de un formulario de login se muestra como fallo inesperado, borra el formulario y ensucia la telemetría. Lo mismo pasa con el 429 de nginx.
- **Plan de corrección:** el canónico es el contrato del backend (`invalid_credentials` existe para esto).
  - `routing:31` y `actions:29-30`: agregar la excepción: en login, `unauthorized` con `code === "invalid_credentials"` y `rate_limited` son esperables.
  - `routing`: publicar `routes/login.tsx` con `action`, `authApi.login`, `safeNext` y `redirect`, que hoy nadie muestra aunque `safeNext` se define para eso.
  - Test: agregarlo a `tests/snippets/web`: 401 conserva el email y 429 muestra el aviso.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno. El dato canónico ya está en `be-errors`.

---

## Hallazgos de severidad media

### FE-05: Dos criterios incompatibles para elegir entre action/`useFetcher`, `useActionState` y API directa

- **Severidad:** media
- **Tipo:** a, b
- **Evidencia:**
  - `routing:301`: "puede mutar con la API directa y refrescar con `useRevalidator()`. Solo en ese caso; en cualquier componente que pertenezca a una ruta, `action` + `useFetcher`."
  - `routing:46`: anti-patrón "Mutar con `fetch` + `navigate` manual | sin revalidación, estado viejo en pantalla".
  - `actions:43`: "para mutaciones de página preferir `action` + `<Form>` del router (revalida loaders solo). Usar `useActionState` para widgets locales."
  - `actions:139`: `QuickOrderForm` llama a `ordersApi.placeOrder` en `useActionState`, la misma mutación que `routing:222`.
  - `actions:122`: `/** El padre actualiza su fuente de verdad (revalidar loader, invalidar cache...). */`
  - `actions:224-226`: `await projectsApi.archive(project.id);` y `startTransition(() => navigate("/projects"));`
- **Confirmación:** por lectura.
- **Impacto:** el mismo "Comprar" tiene dos implementaciones válidas según qué skill se cargue. Un agente puede publicar `useActionState` con API directa dentro de una ruta, justo lo que `routing:301` prohíbe, y el ejemplo de `useTransition` enseña el anti-patrón de `routing:46`.
- **Plan de corrección:** el canónico es `routing:301` para todo componente dentro de una ruta de datos.
  - `actions:43`: reemplazar por una tabla de decisión.
    - Página: `action` + `<Form>`.
    - Fila o widget dentro de una ruta: `action` + `useFetcher`.
    - Extensión sin ruta propia: API directa + `useTransition`/`useRevalidator`.
    - Sin router de datos: `useActionState`.
  - `actions:119-124`: aclarar que `QuickOrderForm` es para el último caso, o reescribirlo con `fetcher.Form`, manteniendo `useOptimistic`.
  - `actions:218-229`: rehacer el ejemplo con `useSubmit`, o marcarlo como "sin router".
  - La verificación es por lectura. Un test de formularios ya cubre `NameForm`.
- **Decisión requerida:** ¿`useActionState` es aceptable dentro de una ruta de datos para widgets que no revalidan nada? Recomiendo sí, solo si la mutación no cambia datos de ningún loader, y que la tabla lo diga expresamente.
- **Otros dominios afectados:** ninguno.

### FE-06: El ESLint que "hace cumplir" la arquitectura no detecta los imports que usan los ejemplos

- **Severidad:** media
- **Tipo:** a, b, d
- **Evidencia:**
  - `arch:31`: "**Dirección de dependencias**: `routes → features → components/lib`. Una feature solo importa de otra por su `index.ts` [...] ESLint lo hace cumplir".
  - `arch:213`: "ESLint (flat config) para hacer cumplir la dirección de dependencias".
  - `arch:223`: `{ group: ["@/features/*/*"], message: "Importar la feature por su index.ts." }`
  - `arch:232`: "`no-restricted-imports` falla ante `@/features/x/Interna`."
  - `routing:196`: `import { ordersApi } from "../features/orders/api";`
  - Ninguna skill configura el alias `@/`: `grep` de `paths`/`alias` en `skills/frontend` no da resultados, y todos los ejemplos usan rutas relativas.
- **Confirmación:** ejecutado (config publicada sobre fixtures).
  - `@/features/x/Interna`: error.
  - `axios`: error.
  - `../features/orders/api`, `src/routes/product-detail.tsx` publicado, `components → routes` y `components → features`: **0 errores**.
- **Impacto:** el checklist pasa en falso. Las importaciones profundas relativas y las inversiones de dirección no se detectan, y el ejemplo de `routing` importa por una ruta profunda.
- **Plan de corrección:** el canónico es la regla de `arch:31`.
  - `arch:213-227`: elegir un mecanismo real. Por ejemplo `import-x/no-restricted-paths` con zonas (`components` y `lib` no importan `features` ni `routes`; `features` no importa `routes`; `features/a` no importa el interior de `features/b`), o `eslint-plugin-boundaries`.
  - `arch:31`: decir explícitamente si `routes/` también debe pasar por `index.ts`.
  - `routing:196`: cambiar a `../features/orders`.
  - Si se opta por alias: publicar `paths` y el alias de Vite, y usar `@/` en todos los ejemplos.
  - Test: fixture con imports buenos y malos en `tests/snippets/web`, y ESLint como parte de `npm test`.
- **Decisión requerida:** ¿alias `@/` en toda la biblioteca o rutas relativas? Recomiendo alias, porque un patrón `no-restricted-imports` sobre relativos no cubre `../orders/api` entre features hermanas. Conviene decidir también si `routes/` queda sujeto al `index.ts`; recomiendo que sí.
- **Otros dominios afectados:** ninguno.

### FE-07: `errors.ts` rompe `npm run build` en un proyecto recién creado con Vite

- **Severidad:** media
- **Tipo:** c
- **Evidencia:**
  - `axios:77`: `constructor(readonly error: ApiError, options?: { cause?: unknown }) {`
  - `ssr:19`: "**SPA** (Vite + React Router *data mode*)".
  - `docker:93`: `RUN npm run build`.
  - Plantilla real de `create-vite` (`tpl/tsconfig.app.json`): `"erasableSyntaxOnly": true` y `"build": "tsc -b && vite build"`.
- **Confirmación:** ejecutado. En `tpl/` con `errors.ts` publicado, `npm run build` da `src/lib/http/errors.ts(32,15): error TS1294: This syntax is not allowed when 'erasableSyntaxOnly' is enabled.`
- **Impacto:** el primer archivo del cliente HTTP rompe el build de la plantilla por defecto, y con él la imagen Docker. Un agente lo arreglará apagando la opción o reescribiendo a mano.
- **Plan de corrección:** el canónico es que el ejemplo compile con la plantilla oficial.
  - `axios:74-79`: declarar `readonly error: ApiError;` y asignarlo en el constructor.
  - `arch:236`: agregar `erasableSyntaxOnly` a la lista de opciones.
  - `tests/snippets/web/tsconfig.json`: agregar la opción (ver FE-21).
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### FE-08: `onError` reporta como errores las respuestas de ruta esperables (404/403), sin `trace_id`

- **Severidad:** media
- **Tipo:** a, b
- **Evidencia:**
  - `errors:32`: "Errores de API **esperables** (404, 403, 422) se manejan como estado o como respuesta de ruta. Las boundaries son para lo inesperado."
  - `errors:173-175`: `onRouterError` llama a `reportError` sin filtrar.
  - `errors:228`: "Los errores de API reportados incluyen el `trace_id` del backend."
  - `routing:30`: `rethrowAsRouteError` "convierte `ApiRequestError` esperables (404, 403) en respuestas de ruta. El resto se relanza (→ boundary + telemetría)."
  - `routing:335,344`: la conversión descarta el error original; `// inesperado → boundary + RouterProvider onError → telemetría`.
- **Confirmación:** ejecutado (`t/router.test.tsx` caso E). Un `data(404)` en loader, un `data(403)` en middleware y un `not_found` convertido con `trace_id: "abc"` producen 1 llamada a `onError` cada uno. El reporte tiene `ErrorResponseImpl` y contexto `{"scope":"router","route":...}`, sin `traceId`.
- **Impacto:** cada 404 o 403 de usuario llega a la telemetría como un error, sin la traza que el checklist exige, y las alertas se llenan de ruido.
- **Plan de corrección:** el canónico es `errors:32`.
  - `errors:173-175`: `if (isRouteErrorResponse(error)) return;` antes de reportar.
  - `errors:227`: agregar al checklist "un 404 de ruta no se reporta".
  - Test: generar `main.tsx` y probar con 404, 403 y error inesperado.
- **Decisión requerida:** ¿se quiere contar los 403 como señal de seguridad? Recomiendo no hacerlo desde el navegador, porque el backend ya los registra.
- **Otros dominios afectados:** ninguno.

### FE-09: Un 403/404 en una action se muestra como "Error inesperado", y 403 está clasificado de dos maneras

- **Severidad:** media
- **Tipo:** b, e
- **Evidencia:**
  - `errors:32`: "esperables (404, 403, 422)".
  - `routing:30`: `rethrowAsRouteError` para 404 y 403.
  - `routing:244`: `throw error;` en la action, sin `rethrowAsRouteError`.
  - `actions:30`: "Errores **inesperados** (500, `forbidden`, `unauthorized`)".
- **Confirmación:** ejecutado (caso F). Una action que lanza `forbidden` muestra "Error inesperado" ("Ya lo registramos") y `onError` se llama 1 vez, frente al "Error 403" que da el mismo fallo en un loader.
- **Impacto:** una misma falta de permiso se presenta distinto según venga de loader o de action.
- **Plan de corrección:** el canónico es `errors:32` y `routing:30`.
  - `routing:244`: reemplazar por `rethrowAsRouteError(error)`.
  - `routing:31`: "Todo lo demás pasa por `rethrowAsRouteError`".
  - `actions:30`: quitar `forbidden` de los inesperados y separar la rama "fuera de una ruta" (va a la boundary local, sin `rethrowAsRouteError`).
  - Test: action con `forbidden` y con `not_found`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### FE-10: La regla de `use(promise)` se contradice, y "Reintentar" nunca recupera el widget

- **Severidad:** media
- **Tipo:** a, b
- **Evidencia:**
  - `actions:20`: "la promesa se crea **fuera** del render (loader, `useMemo`, prop)": `useMemo` corre durante el render.
  - `actions:203-207`: `// La promesa se crea UNA vez por productId.` y `const stockPromise = useMemo(`.
  - `actions:209`: `<ErrorBoundary scope="product-stock" fallback={DefaultFallback} resetKeys={[productId]}>`
  - `errors:224`: "'Reintentar' recupera el widget cuando la causa desapareció".
  - `renders:154`: "Si React Compiler está activo, no se agrega memoización manual nueva."
- **Confirmación:** ejecutado (`t/app.test.tsx` caso P). Tras un 404, con la causa resuelta y pulsando "Reintentar": `calls 1` y sigue "Algo salió mal en esta sección".
- **Impacto:** la promesa rechazada queda memoizada; "Reintentar" relanza el mismo rechazo, sin ningún request nuevo, e incumple el checklist de `errors`. Además, un agente con Compiler activo tiene dos reglas opuestas sobre ese `useMemo`, que aquí no es optimización sino semántica.
- **Plan de corrección:** el canónico es `errors:224`.
  - `actions:202-215`: mantener la promesa en estado (`useState` con un contador de intentos) o crearla en un loader, y conectar `onReset` para crear una nueva.
  - `actions:20`, `actions:52`: reescribir como "la promesa se crea una vez por entrada: loader, prop o caché explícita".
  - `renders:154`: exceptuar la identidad semántica, o eliminar `useMemo` del ejemplo.
  - Test: generar `ProductStock` y probar reintento con recuperación.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### FE-11: Un fallo de red durante el refresh cierra la sesión y pierde el formulario

- **Severidad:** media
- **Tipo:** b, e
- **Evidencia:**
  - `axios:19`: "Si falla: limpiar el token y `onSessionExpired()`."
  - `axios:177`: `/** El refresh falló: la sesión terminó`
  - `client.ts`, `axios:218-222`: cualquier rechazo llama a `onSessionExpired()`.
  - `actions:29`: "los fallos de conexión (`network`, `timeout`): en todos la persona quiere reintentar **sin perder lo que escribió**."
  - `routing:31`: la misma regla.
  - `security:131-148` (`AuthService.refresh`): solo una sesión inválida da 401; un 502 o una caída de red no implica sesión terminada.
- **Confirmación:** ejecutado (caso D). `refreshAccessToken` rechaza con `ERR_NETWORK`: `kind unauthorized`, `expired 1`.
- **Impacto:** un corte breve o un reinicio del backend en el momento de renovar el token (cada 15 min) expulsa a la persona, aunque su sesión siga siendo válida, y borra lo que escribía.
- **Plan de corrección:** el canónico es que solo un 401 del refresh signifique sesión terminada.
  - `axios:218-222`: distinguir el 401 (expira) del resto, y en ese caso propagar el error tipado original (`network`, `timeout`, `server`) sin limpiar el token ni redirigir.
  - `axios:19`, `axios:169`, `axios:177`: actualizar el texto.
  - `axios:422`: agregar al checklist.
  - Test: `refresh_network_error_keeps_session` junto a `session_expires_once`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno. `security` ya cumple.

### FE-12: `toApiError` descarta `code` y `trace_id` en 400, 405, 413, 415 y 429

- **Severidad:** media
- **Tipo:** c, e
- **Evidencia:**
  - `axios:23`: "El cuerpo `problem+json` del backend [...] da `code`, `trace_id` y `fieldErrors`."
  - `axios:70,72`: `{ kind: "rate_limited"; retryAfterMs: number | null }` y `{ kind: "unknown"; status: number | null }`, sin `problem`.
  - `axios:82`: `return "problem" in this.error ? this.error.problem?.trace_id : undefined;`
  - `axios:130`: `default: return status >= 500 ? { kind: "server", status, problem } : { kind: "unknown", status };`
  - `be-errors:75-76`: base `AppError` con 400 `bad_request`.
  - `be-errors:156-158`: `http_{status}` para 405/413/415, con `trace_id`.
  - `errors:228`: "Los errores de API reportados incluyen el `trace_id` del backend."
- **Confirmación:** ejecutado (caso K). 400, 405, 413, 415 y 429 dan `traceId: undefined`; 422 y 500 lo conservan.
- **Impacto:** esos errores llegan a la boundary sin forma de unirlos con la traza, y sin `code` para que la UI los distinga.
- **Plan de corrección:** el canónico es `axios:23`.
  - `axios:70,72`: agregar `problem: ProblemDetails | null` a `rate_limited` y a `unknown`.
  - `axios:129-130`: pasarlo.
  - Test: tabla por status en `tests/snippets/web` (el mismo caso K).
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno. Con nginx, el 429 llega como HTML y `problem` queda `null`, algo que el tipo ya contempla.

### FE-13: El BFF de SSR "reenvía la cookie", pero esa cookie no llega ni autentica

- **Severidad:** media
- **Tipo:** c, e
- **Evidencia:**
  - `ssr:62`: "un BFF delgado que reenvía cookies/tokens".
  - `ssr:74`: "Tokens en `localStorage` con SSR | el servidor no los ve y el SSR renderiza como anónimo | cookie httpOnly".
  - `ssr:106`, `ssr:114`: "BFF delgado que reenvía la cookie" y `headers: { cookie: request.headers.get("cookie") ?? "" },`
  - `security:164`: `REFRESH_COOKIE_PATH = "/api/v1/auth"  # la cookie viaja solo a /auth: el resto de la API nunca la recibe`
  - `security:15`: los endpoints protegidos reciben `Authorization: Bearer <jwt>`.
  - `axios:18`: access token **en memoria**.
- **Confirmación:** ejecutado en la parte de la cookie: con `tough-cookie` (`Path=/api/v1/auth`), hay 0 cookies para `/products/1` y `/api/v1/products/1`, y 1 para `/api/v1/auth/refresh`. La parte de que el backend solo lee Bearer es por lectura. El bloque de framework mode no se compiló (pendiente conocido, DIAGNOSTICO §8).
- **Impacto:** un agente que elige SSR cree que tiene datos autenticados, pero `request.headers.get("cookie")` llega vacío y el backend nunca lo leería. La página se renderiza como anónima, justo lo que `ssr:74` dice evitar con esa cookie.
- **Plan de corrección:** el canónico es `security`, que ya está probado para la SPA.
  - `ssr:62,106,114`: el loader de SSR es solo para contenido público; quitar el reenvío de cookie.
  - `ssr:74`: cambiar la alternativa: "la app privada sigue en SPA (`ssr:61`), o definir antes una sesión de servidor".
  - Si se quiere SSR autenticado, hace falta un diseño propio en `security`.
- **Decisión requerida:** ¿la biblioteca soporta SSR autenticado? Recomiendo que no por ahora: `ssr:61` ya separa sitio público (SSR) y app privada (SPA).
- **Otros dominios afectados:** backend (`security.md`) solo si se decide soportarlo: habría que agregar un mecanismo de sesión para BFF. Con la recomendación, ningún cambio.

### FE-14: El patrón prescrito para `NotifyButton` deja el error sin reportar ni mostrar

- **Severidad:** media
- **Tipo:** b
- **Evidencia:**
  - `routing:313-318`: `try { await ordersApi.notify(orderId); await revalidate(); } finally { setSending(false); }`, sin `catch`.
  - `errors:23`: "Event handlers (`onClick`) y código async suelto | **ninguna boundary** | `try/catch` en el handler, o convertirlo en Action".
  - `errors:42`: "Esperar que una boundary atrape errores de `onClick`/`setTimeout`/promesas | error silencioso".
  - `actions:22`: "`useTransition` | marcar actualizaciones no urgentes, o acciones fuera de `<form>`".
  - `actions:233`: admite `useState(enviando)` en este caso.
- **Confirmación:** ejecutado (`t/notify.test.tsx`). `W reportes 0`, `unhandled ['Error: boom-notify']`, la pantalla sigue en "Notificar".
- **Impacto:** el fallo solo aparece como rechazo no manejado; la persona no ve nada y `reportError` no se llama. El `useState(enviando)` es una excepción documentada; la ausencia del `catch` no lo es.
- **Plan de corrección:** el canónico es `errors:23`.
  - `routing:303-325`: usar `useTransition` (los errores llegan a la boundary), o agregar `catch` con `reportError` y un aviso.
  - `actions:233`: alinear la excepción.
  - Test: generar el bloque y probar el rechazo.
- **Decisión requerida:** ¿`useTransition` o `try/catch`? Recomiendo `useTransition`: elimina también el `useState`.
- **Otros dominios afectados:** ninguno.

### FE-15: `ordersApi` se usa con métodos que no existen en ningún lado, y `Product` no tiene dueño claro

- **Severidad:** media
- **Tipo:** b, c, d
- **Evidencia:**
  - `axios:374-386`: `ordersApi` publica solo `getProduct` y `placeOrder`.
  - `arch:61`: `ordersApi.searchProducts(query, { signal: request.signal })`
  - `arch:83`: "el mismo buscador [...] (verificado con `tsc --strict`, `exactOptionalPropertyTypes`)".
  - `arch:113-114`: `ordersApi.listProducts({ signal: controller.signal })`
  - `routing:314`: `ordersApi.notify(orderId)`
  - `arch:64`: `// features/products/ProductSearch.tsx`, frente a `routing:196` y `actions:100`, donde `Product` y `ordersApi` viven en `features/orders`.
  - `arch:117`: filtra `page.items` en el cliente, y `skills/backend/layering-fastapi-apps/SKILL.md:102-105` define `Page` con `limit`.
- **Confirmación:** ejecutado. Contra el `ordersApi` publicado, `tsc` da `TS2339` en `listProducts`, `searchProducts` y `notify`.
- **Impacto:** un agente que combina `arch` con `axios` obtiene errores de compilación o inventa métodos. La variante con hook solo filtra la primera página y no es "el mismo buscador". `features/products` necesita depender de `features/orders` para algo que es de productos.
- **Plan de corrección:** el canónico es un solo `api.ts` por feature.
  - `axios:374`: publicar `productsApi` en `features/products/api.ts` (`getProduct`, `searchProducts`), y dejar `ordersApi` en `features/orders/api.ts` (`placeOrder`, `notify`).
  - `arch`, `routing`, `actions`, `ssr`: renombrar en los ejemplos.
  - `arch:113-117`: usar `searchProducts` en el hook.
  - Test: compilar los bloques contra los `api.ts` publicados.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend (`layering-fastapi-apps`) no publica `GET /products?q=`; `searchProducts` necesita ese endpoint o una aclaración de que es ilustrativo.

### FE-16: Comprar con éxito lleva a un 404, y el buscador cae en `:productId`

- **Severidad:** media
- **Tipo:** c
- **Evidencia:**
  - `routing:52`: "`src/router.tsx` (verificado: `tsc --strict` y `vite build`...)".
  - `routing:227`: `return redirect(\`/orders/${order.id}\`);`
  - `routing:63-100`: el árbol no declara `orders`.
  - `arch:73`: `fetcher.load(\`/products/search?q=...\`)`
  - `routing:81-89`: bajo `products` solo hay `index` y `:productId`.
  - `routing:353`: `<p>{typeof error.data === "string" ? error.data : error.statusText}</p>`
  - `errors:44`: "Mostrar `error.message`/stack en producción | filtra detalles internos".
- **Confirmación:** ejecutado (caso T, con `router.tsx` publicado).
  - `/orders/1`: "No encontrado — Error: No route matches URL "/orders/1"", sin la navegación del layout.
  - `/products/search?q=ab`: "No encontrado — Id inválido".
- **Impacto:** al combinar los ejemplos, la compra exitosa termina en una pantalla de error sin layout, y el buscador nunca llega a su loader. Además, el texto interno del router se muestra al usuario.
- **Plan de corrección:** el canónico es que el árbol publicado incluya lo que las skills usan.
  - `routing:78-96`: agregar `orders/:orderId`, y `products/search` antes de `:productId`.
  - `routing:64-68`: agregar una ruta `*` hija del layout, para que los 404 queden dentro.
  - `routing:353`: mostrar `error.data` solo si no viene del router (404 sin ruta): usar texto fijo para ese caso.
  - Test: generar `router.tsx`, navegar a esas rutas.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### FE-17: La sesión del frontend tiene dos implementaciones y queda fuera de la estructura de carpetas

- **Severidad:** media
- **Tipo:** b, e
- **Evidencia:**
  - `arch:16-26`: el árbol no contiene `src/auth.ts`.
  - `arch:22`: `api.ts # funciones tipadas que llaman a la API`.
  - `axios:348-351`: `me: async (...) : Promise<CurrentUser>` con `http.get<CurrentUser>("/auth/me", options)`.
  - `routing:105-124`: `src/auth.ts` define `User` y llama a `http.get<User>("/auth/me", { signal })`.
  - `routing:181-183`: `usePrivateData` vive en `src/routes/private.ts`.
  - `routing:26`: "los componentes lo leen con `useRouteLoaderData(PRIVATE_ROUTE)`".
  - `arch:31`: `routes → features → components/lib`.
  - `axios:333`: "Login y logout [...] van con `skipAuth`", pero el bloque publica `login` y `me`, sin `logout`.
  - `security:17`: "`GET /api/v1/auth/me` devuelve el usuario actual y sus permisos", sin esquema publicado.
- **Confirmación:** por lectura.
- **Impacto:** dos tipos y dos llamadas para el mismo endpoint. Un componente de `features/` que necesite el usuario debe importar de `routes/`, invirtiendo la dirección, y ESLint no lo detecta (FE-06). El `logout` queda a criterio de cada agente, y la forma de `User` no se puede verificar contra el backend.
- **Plan de corrección:** el canónico es `arch`: los datos en `features/<x>/api.ts`.
  - Crear `features/auth/{api.ts,session.ts,index.ts}`: `authApi.me`, `authApi.logout`, tipo único `User`, `requireUser`, `userContext`, `usePrivateData`, `PRIVATE_ROUTE`.
  - `routing:103-184`: importar desde allí.
  - `arch:16-26`: agregar `features/auth` como ejemplo.
  - `axios:335-352`: agregar `logout`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** backend (`security.md`): publicar el esquema de `/auth/me`. El frontend espera `{ id: number, email: string, role: string, permissions: string[] }`, y las cadenas de permisos del tipo `"admin.manage"` (`routing:93`) deben coincidir con `Permission.value`.

### FE-18: Cuatro formas distintas para el resultado de una action

- **Severidad:** media
- **Tipo:** a, b
- **Evidencia:**
  - `actions:31`: "Estado de la acción como **unión discriminada** (`idle | success | error`)."
  - `arch:37`: "Uniones discriminadas en vez de combinaciones de booleanos".
  - `actions:65-69`: `error: string | null; saved: boolean; values: { name: string }`.
  - `actions:102-105`: unión con `status`.
  - `routing:219,236`: `{ fieldErrors: ... }`.
  - `routing:274,287`: `useFetcher<{ ok: boolean }>()`, sin lugar para los errores que `routing:31` manda devolver.
- **Confirmación:** por lectura.
- **Impacto:** un agente no tiene una forma canónica. `ProductRow` no puede mostrar errores esperables con su tipo. `NameForm`, el ejemplo citado por la regla, incumple la regla que tiene al lado.
- **Plan de corrección:** el canónico es `actions:31`.
  - Publicar un único `ActionResult<T>` en `lib/` (`idle | success | error`, con `message`, `fieldErrors` y `values` opcionales).
  - Reescribir `actions:65-79`, `routing:219-239`, `routing:274,287`.
  - Actualizar `tests/snippets/web/tests/actions.test.tsx` si cambia `NameForm`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### FE-19: El diagrama de `ssr` contradice su propia matriz

- **Severidad:** media
- **Tipo:** a
- **Evidencia:**
  - `ssr:36`: "¿Quieren RSC, caché por componente y el ecosistema Vercel? | Next.js | RR framework mode".
  - `ssr:22`: Next.js para "greenfield con contenido público grande [...], equipo dispuesto a adoptar RSC".
  - `ssr:34`: "¿El equipo puede operar un runtime Node [...]? | SSR viable | SPA o pre-render".
  - `ssr:53`: `"¿Ya usan React Router data mode?" -> "Next.js (App Router)" [label="no / greenfield"];`
- **Confirmación:** por lectura.
- **Impacto:** un proyecto nuevo sin interés en RSC va a Next.js por el diagrama y a RR framework por la matriz. El diagrama tampoco tiene la salida "no se puede operar Node".
- **Plan de corrección:** el canónico es la matriz.
  - `ssr:38-55`: agregar los nodos "¿Pueden operar Node?" y "¿Quieren RSC?" antes de elegir.
- **Decisión requerida:** para greenfield sin preferencia, ¿el default es RR framework o Next.js? Recomiendo RR framework, porque es coherente con la matriz y con `routing`.
- **Otros dominios afectados:** ninguno.

---

## Hallazgos de severidad baja

### FE-20: `RouteError` manda a recargar, algo que `errors` nombra como anti-patrón

- **Severidad:** baja
- **Tipo:** b
- **Evidencia:**
  - `routing:360`: `<p>Ya lo registramos. Probá recargar la página.</p>`
  - `errors:30`: "Fallback útil: mensaje claro, botón **Reintentar**".
  - `errors:43`: "Fallback sin forma de recuperarse | el usuario tiene que recargar | `reset` + `resetKeys`".
- **Confirmación:** por lectura.
- **Impacto:** las boundaries de ruta quedan sin recuperación, mientras que las de zona sí la tienen.
- **Plan de corrección:** `routing:357-362`: agregar un botón con `useRevalidator().revalidate()` o un enlace al inicio. Comprobar que `revalidate` limpia el error de la ruta.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### FE-21: Bloques marcados "verificado" sin test en el repo

- **Severidad:** baja
- **Tipo:** d
- **Evidencia:**
  - `README.md:66`: "Un bloque que el texto marca como **verificado** tiene su test en `tests/snippets/`."
  - Sin bloque en `generate.py` ni test: `arch:83`, `actions:93`, `renders:48`, `renders:131`, `routing:52` (solo `safeNext` se extrae).
  - `axios:391`: "7 casos verificados" y `axios:416` enumera 7; `tests/snippets/web/tests/skill.test.tsx` tiene 2 del cliente (`session_expires_once`, `abort_in_backoff_is_typed`). `fakeServer`, `client` y `auth` no existen en el repo.
  - `axios:43`: "`tsc --strict` + `exactOptionalPropertyTypes`": `tests/snippets/web/tsconfig.json` no tiene esa opción y `package.json` no corre `tsc`.
  - `tests/snippets/web/package.json`: `@vitejs/plugin-react ^5`, frente al 6 que afirma `renders:131`.
  - Relacionado: DIAGNOSTICO §8 ("Proyectos de referencia fuera del repo").
- **Confirmación:** ejecutado. `npx tsc --noEmit` en `tests/snippets/web` da `generated/components/ErrorBoundary.tsx(63,20): error TS2339: Property 'env' does not exist on type 'ImportMeta'.`, y `npm test` no se entera. En mi proyecto `app/`, los bloques sí compilan y el build de Vite 8 funciona: las afirmaciones son ciertas en lo sustancial salvo `arch:83` (FE-15), pero el repo no las respalda.
- **Impacto:** un cambio futuro puede romper estos bloques sin aviso.
- **Plan de corrección:** el canónico es `README:66`.
  - Agregar los bloques a `generate.py`, con los stubs mínimos.
  - `tsconfig.json`: agregar `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`, `erasableSyntaxOnly` y `vite/client`; cambiar el script de test a `tsc --noEmit && vitest run`.
  - Portar los 5 casos del cliente que faltan.
  - Lo que no se porte: cambiar "verificado" por el alcance real.
- **Decisión requerida:** ¿portar todo o rebajar las afirmaciones? Recomiendo portar los 5 tests del cliente y compilar los bloques de React; `renders:131` puede quedar como verificación manual con fecha.
- **Otros dominios afectados:** testing, solo si adopta el mismo criterio.

### FE-22: "Todas las funciones de `api.ts` aceptan `signal`", salvo las publicadas

- **Severidad:** baja
- **Tipo:** a
- **Evidencia:** `axios:22`: "todas las funciones de `api.ts` aceptan `signal`"; `axios:382`: `async placeOrder(input: PlaceOrderInput): Promise<Order> {`; `axios:338`: `login: async (email: string, password: string)`; `routing:44`: anti-patrón "Ignorar `request.signal`".
- **Confirmación:** por lectura.
- **Impacto:** no queda claro si una mutación debe cancelarse; las acciones no pueden pasar `request.signal`.
- **Plan de corrección:** `axios:22`: "todas las de lectura; las mutaciones, solo si cancelar es seguro", y explicar que abortar un POST no deshace lo hecho en el servidor. O agregar `options` a `placeOrder`.
- **Decisión requerida:** recomiendo la primera opción.
- **Otros dominios afectados:** ninguno.

### FE-23: El linter y la adopción de Compiler no hacen lo que el texto dice

- **Severidad:** baja
- **Tipo:** a, d
- **Evidencia:**
  - `renders:32`: "En existentes, activarlo por directorio y quitar `useMemo`/`useCallback` redundantes con el linter (`eslint-plugin-react-hooks`)."
  - `renders:145`: "Adopción gradual [...] `compilationMode: "annotation"`, que solo compila los componentes marcados con `"use memo"`": por componente, no por directorio.
  - `renders:151`: "sin warnings de `exhaustive-deps`".
  - `arch:108`: `setState({ status: "idle" })` síncrono dentro del efecto.
- **Confirmación:** ejecutado. `eslint-plugin-react-hooks` 7.1.1 `recommended` sobre `src/features/demo/renders.tsx`, con `useMemo`, `useCallback` y `memo`: 0 mensajes (no detecta redundancia). Sobre `useProductSearch`: `react-hooks/set-state-in-effect` error en `arch:108`. El tipo de `sources` existe en `babel-plugin-react-compiler` (por directorio es posible, pero la skill no lo muestra).
- **Impacto:** el agente buscará una función del linter que no existe, y el hook "verificado" falla la configuración recomendada de ese mismo plugin.
- **Plan de corrección:**
  - `renders:32`: "quitarlos a mano y comprobar con el Profiler"; mostrar `sources` para la activación por directorio.
  - `renders:151`: ampliar a toda la configuración `recommended`.
  - `arch:106-112`: derivar `idle` en render.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### FE-24: `ssr` promete una migración "sin reescribir rutas" y mantiene un ADR con métricas obligatorias

- **Severidad:** baja
- **Tipo:** a
- **Evidencia:**
  - `ssr:24`: "migra a framework mode **sin reescribir rutas**".
  - `ssr:91-104`: `loader` pasa a `clientLoader`, `Component` a `export default`, `useLoaderData` a `loaderData`.
  - `ssr:11`: "La decisión se documenta como ADR", frente a `ssr:63`: "puede vivir en un ADR o en cualquier documento".
  - `ssr:127`: la plantilla pide "métricas actuales", frente a `ssr:136`: "Si todo está detrás de login, registra ese motivo y no necesita métricas".
- **Confirmación:** por lectura.
- **Impacto:** subestima el costo de la migración en una guía que se usa precisamente para decidir. La plantilla pide lo que la regla ya no exige.
- **Plan de corrección:** `ssr:24`: "sin rehacer el diseño de rutas, adaptando cada módulo (ver abajo)". `ssr:11`: "se registra". `ssr:127`: "métricas actuales, si la decisión es por rendimiento o SEO".
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

### FE-25: `vercel-index` y DIAGNOSTICO no coinciden en conteos, fechas ni en `create-a-backend`

- **Severidad:** baja
- **Tipo:** a, d
- **Evidencia:**
  - `vercel:11`: "la organización informa 20 fuentes y 65 skills [...] La organización publica ~20 fuentes y ~60 skills".
  - `vercel:43`: "Vacíos: sin skill oficial (al 2026-10-23)", frente a `vercel:49`: "en el relevamiento del 2026-11-01".
  - `vercel:29,47-48`: describe y cita `create-a-backend`, frente a `vercel:49`: "`vercel-plugin/create-a-backend` y `vercel-py/iter-coroutine` no se pudieron confirmar (la página no trae descripción)".
  - `DIAGNOSTICO.md:173`: "Relevado el 2026-10-23", sin el re-relevamiento.
- **Confirmación:** por lectura. No se consultó skills.sh, así que no sé cuál de los valores es el correcto.
- **Impacto:** no se sabe si `create-a-backend` está confirmada, y es la recomendación para Blob, KV y Postgres.
- **Plan de corrección:** al re-relevar, dejar una sola cifra y una sola fecha. `vercel:49`: aclarar que lo no confirmado es si cubre Python, o quitar `create-a-backend` de las filas que lo citan. Actualizar `DIAGNOSTICO.md:173`.
- **Decisión requerida:** ninguna.
- **Otros dominios afectados:** ninguno.

---

## Dudosos (no los cuento como hallazgos)

1. **`/auth/me` en cada navegación.** Medido en `router.tsx`: 3 navegaciones dan `/auth/me` ×3. Por lectura (no medido), lo mismo valdría para cada `fetcher.load` bajo la rama privada: el buscador de `arch:73` no tiene debounce, de modo que cada tecla haría 2 requests, aunque `arch:83` lo llama "el mismo buscador" que la versión con 300 ms. Es un costo de diseño, y ninguna regla lo contradice de forma directa.
2. **`react-error-boundary` "con API equivalente" (`errors:34`).** La v6.1.6 usa `resetErrorBoundary` y `error: unknown`, frente a `reset` y `error: Error`, y no tiene `scope`. Son equivalentes en concepto, no intercambiables.
3. **"SPA Mode" en `ssr:79`,** aplicado a una config con `prerender`. No lo verifiqué contra la documentación de framework mode.
4. **"Ya lo registramos" (`routing:360`).** Con el reporter por defecto (`console.error`, `errors:65-67`) es falso. Además, ninguna skill de `observability` ni de `backend` define un destino para errores del navegador (`grep` sin resultados) y el único proveedor con ejemplo es Sentry, que no está en el stack del README. Nada promete lo contrario, salvo el "custom endpoint" de la `description` de `errors`.
5. **`useProductSearch` se traga lo que no sea error de API (`arch:119-123`).** Ejecutado (caso V): un `TypeError` deja `{"status":"loading"}` para siempre, sin reporte. Roza `errors:45`.
6. **`withCredentials` solo en el refresh (`axios:321`).** Login y logout no lo llevan. Funciona porque la decisión es mismo origen, pero `ssr:19` ofrece "CDN" sin avisar de ese requisito (lo avisan `vercel:57` y `security:203`).
7. **`arch:49` "(o `useMemo` si es caro)"** es incondicional, mientras que `renders:32` dice que en proyectos nuevos no se escribe memoización manual.
8. **`assertNever`** (`axios:25,427`) se exige, pero ningún bloque lo define.
9. **`toSorted` (`renders:95`)** no compila con `lib: ES2022`, que es lo que usa `tests/snippets/web/tsconfig.json`. La plantilla de Vite usa ES2023, y ahí compila.
10. **"el paquete no existe" (`routing:43`).** `react-router-dom` sigue en npm con `latest` 7.18.5: un `npm i` no falla, instala v7. La regla y el `grep` del checklist siguen siendo correctos.

Para el auditor de backend, fuera de mi alcance: `security:235,247` dice 403 para un recurso ajeno y `be-errors:41` dice 404. El frontend tolera ambos.

## Lo que no se pudo verificar

- Comportamiento en un navegador real: carrera entre `window.location.assign` y el router, `SameSite` y envío real de cookies. Se usó jsdom y `tough-cookie`.
- Frontend contra backend real y nginx real. Los contratos se cruzaron por lectura y con un adapter falso.
- Bloques de framework mode de `ssr` (pendiente de DIAGNOSTICO §8), integración con Sentry y `react({ compiler: true })`.
- Catálogo de skills.sh: no se consultó.
