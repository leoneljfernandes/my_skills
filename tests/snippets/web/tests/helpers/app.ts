// Arranca la app publicada (router.tsx + features/auth + lib/http) sobre un servidor falso.
// Cada llamada reinicia los módulos de la app: el router y el cliente HTTP son singletons.
import axios from "axios";
import { vi } from "vitest";

import { fakeServer, type FakeReply } from "./http";
import type { InternalAxiosRequestConfig } from "axios";

export const ME = { id: 1, email: "ana@example.com", role: "admin", permissions: ["admin.manage"] };

export const problem = (status: number, code: string, extra: Record<string, unknown> = {}) => ({
  title: code,
  status,
  code,
  trace_id: `trace-${status}`,
  ...extra,
});

export async function bootApp(url: string, handler: (config: InternalAxiosRequestConfig) => FakeReply) {
  vi.resetModules();
  window.history.pushState({}, "", url);
  const lib = await import("@/lib/http");
  const server = fakeServer(handler);
  lib.http.defaults.adapter = server.adapter;
  axios.defaults.adapter = server.adapter; // el refresh usa axios "pelado"
  lib.tokenStore.setAccessToken("token");
  const { router } = await import("@/router");
  const { redirectToLogin } = await import("@/features/auth");
  lib.setSessionExpiredHandler(() => redirectToLogin(router)); // lo mismo que hace main.tsx
  return { router, server, lib };
}

/** Como lo usa main.tsx: el `onError` publicado de handling-react-errors. */
export async function publishedOnError(reporter: (error: unknown, context: unknown) => void) {
  const telemetry = await import("@/lib/telemetry");
  telemetry.setErrorReporter(reporter);
  return (await import("@/on-router-error")).onRouterError;
}

export const isUrl = (config: InternalAxiosRequestConfig, suffix: string): boolean => (config.url ?? "").endsWith(suffix);
