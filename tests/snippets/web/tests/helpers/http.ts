// Ayudas que los tests publicados en building-axios-clients usan sin definirlas:
// `fakeServer`, `client`, `auth` y `memoryTokens`.
import { AxiosError, AxiosHeaders, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";

import { createHttpClient, type HttpClientOptions } from "../../generated/lib/http/client";

export interface FakeReply {
  status: number;
  data?: unknown;
  headers?: Record<string, string>;
  /** Sin respuesta del servidor (red caída): el adapter rechaza con ERR_NETWORK. */
  network?: true;
  /** Demora la respuesta (ms): para que llegue después de que la app terminó de arrancar. */
  delayMs?: number;
}

export function fakeServer(handler: (config: InternalAxiosRequestConfig) => FakeReply) {
  const calls: InternalAxiosRequestConfig[] = [];
  const adapter: AxiosAdapter = async (config) => {
    calls.push(config);
    const reply = handler(config);
    if (reply.delayMs) await new Promise((resolve) => setTimeout(resolve, reply.delayMs));
    if (reply.network) return Promise.reject(new AxiosError("Network Error", "ERR_NETWORK", config));
    const response: AxiosResponse = {
      status: reply.status,
      statusText: "",
      data: reply.data ?? {},
      headers: reply.headers ?? {},
      config,
    };
    if (reply.status >= 200 && reply.status < 300) return Promise.resolve(response);
    return Promise.reject(new AxiosError(`HTTP ${reply.status}`, "ERR_BAD_RESPONSE", config, {}, response));
  };
  return { adapter, calls };
}

export function memoryTokens(initial: string | null = "old") {
  let token = initial;
  return { getAccessToken: () => token, setAccessToken: (t: string | null) => (token = t) };
}

export function auth(config: InternalAxiosRequestConfig): string | undefined {
  const value = config.headers.get("Authorization");
  return typeof value === "string" ? value : undefined;
}

/** Cliente sobre el adapter falso, con backoff mínimo para que los reintentos no demoren la suite. */
export function client(adapter: AxiosAdapter, overrides: Partial<HttpClientOptions> = {}) {
  const http = createHttpClient({
    baseURL: "/",
    tokens: memoryTokens(),
    refreshAccessToken: () => Promise.resolve("fresh"),
    onSessionExpired: () => undefined,
    baseDelayMs: 1,
    maxDelayMs: 2,
    ...overrides,
  });
  http.defaults.adapter = adapter;
  return http;
}

/** El error que lanza axios (la instancia "pelada" del refresh) ante una respuesta HTTP no 2xx. */
export function httpFailure(status: number, data: unknown = {}, headers: Record<string, string> = {}): AxiosError {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
  const response: AxiosResponse = { status, statusText: "", data, headers, config };
  return new AxiosError(`HTTP ${status}`, "ERR_BAD_RESPONSE", config, {}, response);
}

export const networkFailure = (): AxiosError => new AxiosError("Network Error", "ERR_NETWORK");
export const timeoutFailure = (): AxiosError => new AxiosError("timeout", "ECONNABORTED");
