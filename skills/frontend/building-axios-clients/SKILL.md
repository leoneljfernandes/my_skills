---
name: building-axios-clients
description: Use when a React/TypeScript frontend calls an HTTP API with Axios - creating the shared axios instance, attaching auth tokens, refreshing expired access tokens on 401, retrying failed requests with exponential backoff, cancelling requests, mapping API errors (problem+json, 422 field errors) to typed errors - or when several requests trigger multiple refreshes at once, POSTs get duplicated by retries, or components branch on error.response?.status.
domain: frontend
tags: [typescript, axios, http-client, auth, refresh-token, retry, error-handling, react]
triggers: [axios, "axios.create", interceptors, interceptor, "refresh token", "token refresh", "401", retry, backoff, "exponential backoff", AbortController, "Idempotency-Key", "cliente HTTP", "problem+json", AxiosError]
---

# Cliente HTTP profesional con Axios

Una sola instancia configurada en `lib/http`. Resuelve auth, refresh, reintentos y errores **una vez**. El resto de la app recibe datos tipados o un `ApiRequestError` con una unión discriminada exhaustiva, y nunca importa `axios`.

## Contexto y reglas

**Hacer**

- **Factory** `createHttpClient(options)` con dependencias inyectadas (token store, función de refresh, callback de sesión expirada). Es testeable con un adapter falso.
- **Tokens**: access token **en memoria**; refresh token en cookie `httpOnly; Secure; SameSite`, invisible para JS. Nunca en `localStorage`.
- **Refresh single-flight**: N requests que reciben 401 a la vez comparten **una** promesa de refresh y después se reenvían. El refresh usa una instancia **sin interceptores**. Si falla: limpiar el token y `onSessionExpired()`.
- **Retry** solo para errores transitorios (red caída, timeout, 408/429/502/503/504) y solo en métodos idempotentes (`GET`, `HEAD`, `OPTIONS`, `PUT`, `DELETE`). Un `POST`/`PATCH` no se reintenta. **Si el servidor deduplica por `Idempotency-Key`**, se puede enviar la clave y el cliente reintenta ese `POST`; si el backend no la implementa (ninguna skill de backend de esta biblioteca lo hace), enviar la cabecera no protege de nada.
- **Backoff exponencial con full jitter** (`random(0, base·2^n)`) con techo, respetando `Retry-After`. La espera se cancela si se aborta la request.
- **Cancelación**: todas las funciones de `api.ts` aceptan `signal`; loaders pasan `request.signal` y los hooks un `AbortController` por efecto.
- **Mapeo de errores en un solo lugar** (`toApiError`): `AxiosError` → `ApiError` (unión discriminada por `kind`). El cuerpo `problem+json` del backend (ver `handling-fastapi-errors`) da `code`, `trace_id` y `fieldErrors`.
- Opciones por request tipadas con **module augmentation** de `AxiosRequestConfig` (`skipAuth`, `retry`).
- **`switch` sobre `kind`**: exhaustivo (con `assertNever` en el `default`) solo donde la UI da un tratamiento distinto a cada `kind`. Donde la UI maneja solo los `kind` esperables de ese formulario (ver `using-react-19-actions`), mapear esos y relanzar el resto con `throw error` para que lo muestre la boundary de la ruta.
- `timeout` explícito, `baseURL` relativa (`/api/v1`) detrás del mismo origen (proxy en dev, nginx en prod) para evitar CORS.

**Evitar (anti-patrones)**

| Anti-patrón | Consecuencia | En su lugar |
|---|---|---|
| `axios.get` directo en componentes | cada pantalla maneja auth/errores a su manera | instancia central + `features/x/api.ts` |
| Refresh por cada 401 concurrente | N refreshes; con rotación de refresh tokens, sesión invalidada | promesa compartida (single-flight) |
| Refresh con la misma instancia | 401 en el refresh → bucle infinito | instancia "pelada" |
| Reintentar POST sin idempotencia | órdenes/pagos duplicados | solo idempotentes; un POST con `Idempotency-Key` únicamente si el servidor deduplica |
| Backoff fijo o sin jitter | estampida sincronizada contra un servidor que se recupera | exponencial + full jitter |
| `localStorage` para tokens | cualquier XSS los roba | memoria + cookie httpOnly |
| `if (err.response?.status === 422)` en componentes | lógica de transporte repartida, sin tipos | `switch (error.error.kind)` |
| Ignorar `AbortError` como error | toasts de "falló" al navegar | `kind: "canceled"` se ignora |

## Ejemplos

`src/lib/http/errors.ts` (verificado con `tsc --strict` + `exactOptionalPropertyTypes`):

```ts
import { isAxiosError, isCancel } from "axios";

/** RFC 9457 problem+json, tal como lo emite el backend FastAPI. */
export interface ProblemDetails {
  type?: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  instance?: string;
  trace_id?: string;
  errors?: ReadonlyArray<{ type: string; loc: ReadonlyArray<string | number>; msg: string }>;
  [extension: string]: unknown;
}

export type ApiError =
  | { kind: "canceled" }
  | { kind: "timeout" }
  | { kind: "network" }
  | { kind: "unauthorized"; problem: ProblemDetails | null }
  | { kind: "forbidden"; problem: ProblemDetails | null }
  | { kind: "not_found"; problem: ProblemDetails | null }
  | { kind: "conflict"; problem: ProblemDetails | null }
  | { kind: "validation"; problem: ProblemDetails | null; fieldErrors: Record<string, string> }
  | { kind: "rate_limited"; retryAfterMs: number | null }
  | { kind: "server"; status: number; problem: ProblemDetails | null }
  | { kind: "unknown"; status: number | null };

export class ApiRequestError extends Error {
  override readonly name = "ApiRequestError";

  constructor(readonly error: ApiError, options?: { cause?: unknown }) {
    super(`API request failed: ${error.kind}`, options);
  }

  get traceId(): string | undefined {
    return "problem" in this.error ? this.error.problem?.trace_id : undefined;
  }
}

export function isApiRequestError(value: unknown): value is ApiRequestError {
  return value instanceof ApiRequestError;
}

function asProblem(data: unknown): ProblemDetails | null {
  if (typeof data === "object" && data !== null && "status" in data && "code" in data) {
    return data as ProblemDetails;
  }
  return null;
}

function toFieldErrors(problem: ProblemDetails | null): Record<string, string> {
  const result: Record<string, string> = {};
  for (const err of problem?.errors ?? []) {
    const field = err.loc.filter((part) => part !== "body").join(".");
    result[field] ??= err.msg;
  }
  return result;
}

export function parseRetryAfter(header: unknown, now: number = Date.now()): number | null {
  if (typeof header !== "string" || header === "") return null;
  const seconds = Number(header);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);
  const date = Date.parse(header);
  return Number.isNaN(date) ? null : Math.max(0, date - now);
}

/** Traduce cualquier error de axios a la unión tipada. Único lugar que conoce AxiosError. */
export function toApiError(error: unknown): ApiError {
  if (isCancel(error)) return { kind: "canceled" };
  if (!isAxiosError(error)) return { kind: "unknown", status: null };
  if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") return { kind: "timeout" };
  if (!error.response) return { kind: "network" };

  const { status, data, headers } = error.response;
  const problem = asProblem(data);
  switch (status) {
    case 401: return { kind: "unauthorized", problem };
    case 403: return { kind: "forbidden", problem };
    case 404: return { kind: "not_found", problem };
    case 409: return { kind: "conflict", problem };
    case 422: return { kind: "validation", problem, fieldErrors: toFieldErrors(problem) };
    case 429: return { kind: "rate_limited", retryAfterMs: parseRetryAfter(headers["retry-after"]) };
    default: return status >= 500 ? { kind: "server", status, problem } : { kind: "unknown", status };
  }
}
```

`src/lib/http/client.ts`:

```ts
import axios, {
  AxiosError,
  AxiosHeaders,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";

import { ApiRequestError, parseRetryAfter, toApiError } from "./errors";

declare module "axios" {
  interface AxiosRequestConfig {
    /** No adjuntar Authorization ni intentar refresh (login, refresh, endpoints públicos). */
    skipAuth?: boolean;
    /** false desactiva el retry para esta request. */
    retry?: false | { retries?: number };
    /** @internal */ _retryCount?: number;
    /** @internal */ _authRetried?: boolean;
  }
}

export interface TokenStore {
  getAccessToken(): string | null;
  setAccessToken(token: string | null): void;
}

export interface HttpClientOptions {
  baseURL: string;
  tokens: TokenStore;
  /** Pide un access token nuevo (POST /auth/refresh con cookie httpOnly). */
  refreshAccessToken: () => Promise<string>;
  /** Refresh falló: la sesión terminó (redirigir a /login, limpiar estado). */
  onSessionExpired: () => void;
  timeoutMs?: number;
  retries?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
}

/** El refresh falló: la sesión terminó (distingue este caso de un error al reenviar la request). */
class SessionExpiredError extends Error {
  constructor(cause: unknown) {
    super("session expired", { cause });
  }
}

const IDEMPOTENT_METHODS = new Set(["get", "head", "options", "put", "delete"]);
const RETRYABLE_STATUS = new Set([408, 429, 502, 503, 504]);

function sleep(ms: number, signal?: AxiosRequestConfig["signal"]): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener?.("abort", () => {
      clearTimeout(timer);
      reject(new axios.CanceledError());
    });
  });
}

export function createHttpClient(options: HttpClientOptions): AxiosInstance {
  const { tokens, refreshAccessToken, onSessionExpired } = options;
  const maxRetries = options.retries ?? 3;
  const baseDelayMs = options.baseDelayMs ?? 300;
  const maxDelayMs = options.maxDelayMs ?? 10_000;

  const http = axios.create({
    baseURL: options.baseURL,
    timeout: options.timeoutMs ?? 15_000,
    headers: { Accept: "application/json" },
  });

  // Single-flight: N requests con 401 simultáneos comparten UN refresh. Si falla, la sesión
  // expira una sola vez (no una por request), y todas las requests salen como "unauthorized".
  let refreshing: Promise<string> | null = null;
  const refreshOnce = (): Promise<string> => {
    refreshing ??= refreshAccessToken()
      .then((token) => {
        tokens.setAccessToken(token);
        return token;
      })
      .catch((refreshError: unknown) => {
        tokens.setAccessToken(null);
        onSessionExpired();
        throw new SessionExpiredError(refreshError);
      })
      .finally(() => {
        refreshing = null;
      });
    return refreshing;
  };

  http.interceptors.request.use((config) => {
    const token = tokens.getAccessToken();
    if (token && !config.skipAuth) config.headers.set("Authorization", `Bearer ${token}`);
    return config;
  });

  const isRetryable = (error: AxiosError, config: InternalAxiosRequestConfig): boolean => {
    if (config.retry === false || axios.isCancel(error)) return false;
    const method = (config.method ?? "get").toLowerCase();
    // POST/PATCH solo se reintentan si el servidor deduplica por Idempotency-Key.
    if (!IDEMPOTENT_METHODS.has(method) && !config.headers.has("Idempotency-Key")) return false;
    if (!error.response) return true; // red caída / timeout
    return RETRYABLE_STATUS.has(error.response.status);
  };

  const backoffMs = (attempt: number, error: AxiosError): number => {
    const retryAfter = parseRetryAfter(error.response?.headers["retry-after"]);
    if (retryAfter !== null) return Math.min(retryAfter, maxDelayMs);
    const ceiling = Math.min(maxDelayMs, baseDelayMs * 2 ** attempt);
    return Math.random() * ceiling; // "full jitter": evita que todos los clientes reintenten juntos
  };

  http.interceptors.response.use(undefined, async (error: unknown) => {
    if (!(error instanceof AxiosError) || !error.config) {
      throw new ApiRequestError(toApiError(error), { cause: error });
    }
    const config = error.config;

    // 1) 401 → refresh una vez y reintentar la request original.
    if (error.response?.status === 401 && !config.skipAuth && !config._authRetried) {
      config._authRetried = true;
      try {
        const token = await refreshOnce();
        config.headers = AxiosHeaders.from(config.headers).set("Authorization", `Bearer ${token}`);
        return await http.request(config);
      } catch (refreshError) {
        if (refreshError instanceof SessionExpiredError) {
          throw new ApiRequestError(toApiError(error), { cause: refreshError.cause });
        }
        throw refreshError; // falló el replay de la request, no el refresh
      }
    }

    // 2) Errores transitorios → backoff exponencial con jitter.
    const limit = config.retry === false ? 0 : (config.retry?.retries ?? maxRetries);
    const attempt = config._retryCount ?? 0;
    if (attempt < limit && isRetryable(error, config)) {
      config._retryCount = attempt + 1;
      try {
        await sleep(backoffMs(attempt, error), config.signal);
      } catch (abortError) {
        // Abortada durante la espera: sale tipada como "canceled", igual que cualquier otro error.
        throw new ApiRequestError(toApiError(abortError), { cause: abortError });
      }
      return http.request(config);
    }

    // 3) Todo lo demás sale tipado.
    throw new ApiRequestError(toApiError(error), { cause: error });
  });

  return http;
}
```

`src/lib/http/index.ts`, la instancia de la app:

```ts
import axios from "axios";

import { createHttpClient, type TokenStore } from "./client";

// Access token SOLO en memoria (no localStorage: lo lee cualquier XSS).
// El refresh token vive en una cookie httpOnly + Secure + SameSite que JS no ve.
let accessToken: string | null = null;
export const tokenStore: TokenStore = {
  getAccessToken: () => accessToken,
  setAccessToken: (token) => {
    accessToken = token;
  },
};

const API_BASE_URL = "/api/v1";

export const http = createHttpClient({
  baseURL: API_BASE_URL,
  tokens: tokenStore,
  // Instancia "pelada": si usara `http`, un 401 en el refresh dispararía otro refresh.
  refreshAccessToken: async () => {
    const { data } = await axios.post<{ access_token: string }>(
      `${API_BASE_URL}/auth/refresh`,
      undefined,
      { withCredentials: true, timeout: 10_000 },
    );
    return data.access_token;
  },
  onSessionExpired: () => {
    // pathname + search: volver a la pantalla con sus filtros, no solo a la ruta.
    const { pathname, search } = window.location;
    window.location.assign(`/login?next=${encodeURIComponent(pathname + search)}`);
  },
});
```

Login y logout hablan con los mismos endpoints que el refresh, así que van con `skipAuth` (no hay token todavía) y `retry: false` (un login fallido no se reintenta: cada intento cuenta contra el límite de intentos del servidor). `/auth/token` recibe **form-data**, no JSON:

```ts
export const authApi = {
  /** Guarda el access token en memoria; el refresh token queda en la cookie httpOnly. */
  login: async (email: string, password: string): Promise<void> => {
    const form = new URLSearchParams({ username: email, password });
    const { data } = await http.post<{ access_token: string }>("/auth/token", form, {
      skipAuth: true,
      retry: false,
    });
    tokenStore.setAccessToken(data.access_token);
  },

  /** Si no hay access token (p. ej. tras recargar), el cliente lo renueva con la cookie. */
  me: async (options: { signal?: AbortSignal } = {}): Promise<CurrentUser> => {
    const { data } = await http.get<CurrentUser>("/auth/me", options);
    return data;
  },
};
```

En desarrollo, el dev server hace proxy de `/api` al backend para que el origen sea el mismo (la cookie `SameSite=strict` solo viaja entre requests del mismo sitio). La URL del backend sale de `.env` y la config falla al arrancar si falta, en vez de proxear a ningún lado:

```ts
// vite.config.ts
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, ENV_DIR, ""); // ENV_DIR: la raíz del repo, donde vive el .env
  const apiTarget = env.FRONTEND_API_PROXY_TARGET; // p. ej. http://localhost:8000
  if (command === "serve" && mode !== "test" && !apiTarget) {
    throw new Error("Falta FRONTEND_API_PROXY_TARGET en .env (p. ej. http://localhost:8000)");
  }
  return {
    server: { proxy: apiTarget ? { "/api": { target: apiTarget, changeOrigin: true } } : {} },
  };
});
```

Consumo tipado en una feature:

```ts
export const ordersApi = {
  async getProduct(id: number, options: { signal?: AbortSignal } = {}): Promise<Product> {
    const { data } = await http.get<Product>(`/products/${id}`, options);
    return data;
  },

  // Un POST no se reintenta solo. Si el servidor deduplica, agregar el parámetro
  // `idempotencyKey` y la cabecera `Idempotency-Key`: el cliente reintentará ese POST.
  async placeOrder(input: PlaceOrderInput): Promise<Order> {
    const { data } = await http.post<Order>("/orders", input);
    return data;
  },
};

// En la UI: mapear los `kind` esperables del formulario y relanzar el resto (ver using-react-19-actions).
```

Tests del cliente con un adapter falso (vitest, 7 casos verificados):

```ts
it("shares ONE refresh across concurrent 401s and replays every request", async () => {
  const refresh = vi.fn(async () => "fresh");
  const server = fakeServer((c) => (auth(c) === "Bearer fresh" ? { status: 200, data: c.url } : { status: 401 }));
  const http = client(server.adapter, { refreshAccessToken: refresh });

  const results = await Promise.all([http.get("/a"), http.get("/b"), http.get("/c")]);

  expect(results.map((r) => r.data)).toEqual(["/a", "/b", "/c"]);
  expect(refresh).toHaveBeenCalledTimes(1);
});

it("does NOT retry a POST without Idempotency-Key", async () => {
  const server = fakeServer(() => ({ status: 503 }));
  const http = client(server.adapter, { tokens: memoryTokens("valid") });

  const error = await http.post("/orders", {}).catch((e: unknown) => e);

  expect((error as ApiRequestError).error).toMatchObject({ kind: "server", status: 503 });
  expect(server.calls).toHaveLength(1);
});
```

Casos cubiertos por la suite: refresh single-flight, sesión expirada si el refresh falla, retry de GET ante 503, POST sin `Idempotency-Key` no se reintenta, POST con key sí, 422 → `fieldErrors` + `traceId`, y abort durante el backoff → `canceled`.

## Checklist de verificación

- [ ] `grep -rn "from \"axios\"" src | grep -v "src/lib/http"` no devuelve nada.
- [ ] Test: 3 requests concurrentes con 401 → exactamente 1 refresh. Con el refresh fallido → `onSessionExpired` se llama **una** sola vez (no una por request).
- [ ] Test: si el refresh falla, se llama `onSessionExpired` y el error es `kind: "unauthorized"`.
- [ ] Test: GET con 503 se reintenta; un POST no.
- [ ] Test: abortar durante la espera del reintento sale como `ApiRequestError` con `kind: "canceled"`.
- [ ] Test: 422 problem+json → `fieldErrors` por campo y `traceId`.
- [ ] Ningún token en `localStorage`/`sessionStorage`.
- [ ] Los `switch (error.error.kind)` que dan un tratamiento a cada `kind` terminan en `assertNever`; los que manejan solo los esperables relanzan el resto.

## Skills relacionadas

- `handling-fastapi-errors`: el formato problem+json que este cliente tipa.
- `routing-with-react-router`: `request.signal` y conversión de errores a respuestas de ruta.
- `handling-react-errors`: reporte del `traceId`.
