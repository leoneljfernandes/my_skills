// Casos del cliente HTTP de building-axios-clients que no publica el SKILL.md (FE-21).
// Los dos que sí publica (refresh compartido y POST sin Idempotency-Key) corren desde
// generated/http-client.published.test.ts, extraídos del SKILL.md.
import { expect, it, vi } from "vitest";

import { ApiRequestError, assertNever, type ApiError } from "../generated/lib/http/errors";
import { auth, client, fakeServer, httpFailure, memoryTokens, networkFailure, timeoutFailure } from "./helpers/http";

async function failure(promise: Promise<unknown>): Promise<ApiRequestError> {
  const error = await promise.catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiRequestError);
  return error as ApiRequestError;
}

it("retries a GET on 503 and returns the eventual success", async () => {
  let attempts = 0;
  const server = fakeServer(() => (++attempts < 3 ? { status: 503 } : { status: 200, data: "ok" }));
  const http = client(server.adapter, { tokens: memoryTokens("valid") });

  const response = await http.get("/a");

  expect(response.data).toBe("ok");
  expect(server.calls).toHaveLength(3);
});

it("retries a POST that carries an Idempotency-Key", async () => {
  let attempts = 0;
  const server = fakeServer(() => (++attempts < 2 ? { status: 503 } : { status: 201, data: "created" }));
  const http = client(server.adapter, { tokens: memoryTokens("valid") });

  const response = await http.post("/orders", {}, { headers: { "Idempotency-Key": "k-1" } });

  expect(response.data).toBe("created");
  expect(server.calls).toHaveLength(2);
});

it("maps a 422 problem+json to fieldErrors and traceId", async () => {
  const problem = {
    title: "Validation error",
    status: 422,
    code: "validation_error",
    trace_id: "abc123",
    errors: [{ type: "missing", loc: ["body", "customer_email"], msg: "Field required" }],
  };
  const server = fakeServer(() => ({ status: 422, data: problem }));
  const http = client(server.adapter, { tokens: memoryTokens("valid") });

  const error = await failure(http.post("/orders", {}));

  expect(error.error).toMatchObject({ kind: "validation", fieldErrors: { customer_email: "Field required" } });
  expect(error.traceId).toBe("abc123");
  expect(server.calls).toHaveLength(1);
});

it("ends the session and reports kind unauthorized when the refresh answers 401", async () => {
  const onSessionExpired = vi.fn();
  const server = fakeServer(() => ({ status: 401 }));
  const http = client(server.adapter, {
    refreshAccessToken: () => Promise.reject(httpFailure(401)),
    onSessionExpired,
  });

  const error = await failure(http.get("/a"));

  expect(error.error.kind).toBe("unauthorized");
  expect(onSessionExpired).toHaveBeenCalledTimes(1);
});

// --- FE-11 (+ BE-09): qué cuenta como "sesión terminada" ---

const alwaysExpired = () => fakeServer(() => ({ status: 401 }));

it.each([
  ["network", networkFailure(), { kind: "network" }],
  ["timeout", timeoutFailure(), { kind: "timeout" }],
  ["server", httpFailure(503, { title: "x", status: 503, code: "http_503", trace_id: "t-1" }), { kind: "server", status: 503 }],
])("refresh_%s_error_keeps_session: no cierra la sesión y el error sale tipado", async (_name, refreshError, expected) => {
  const onSessionExpired = vi.fn();
  const tokens = memoryTokens("old");
  const server = alwaysExpired();
  const http = client(server.adapter, { tokens, refreshAccessToken: () => Promise.reject(refreshError), onSessionExpired });

  const error = await failure(http.post("/orders", {}));

  expect(error.error).toMatchObject(expected);
  expect(onSessionExpired).not.toHaveBeenCalled();
  expect(tokens.getAccessToken()).toBe("old"); // el token sigue ahí: la sesión puede seguir viva
});

it("refresh_network_error_keeps_session: la request siguiente vuelve a intentar el refresh", async () => {
  let online = false;
  const onSessionExpired = vi.fn();
  const server = fakeServer((c) => (auth(c) === "Bearer fresh" ? { status: 200, data: "ok" } : { status: 401 }));
  const http = client(server.adapter, {
    refreshAccessToken: () => (online ? Promise.resolve("fresh") : Promise.reject(networkFailure())),
    onSessionExpired,
  });

  await failure(http.get("/a"));
  online = true;
  const response = await http.get("/a");

  expect(response.data).toBe("ok");
  expect(onSessionExpired).not.toHaveBeenCalled();
});

it("session_rotated: espera y reintenta el refresh UNA vez, sin cerrar la sesión", async () => {
  const onSessionExpired = vi.fn();
  const refresh = vi
    .fn<() => Promise<string>>()
    .mockRejectedValueOnce(httpFailure(401, { title: "x", status: 401, code: "session_rotated" }))
    .mockResolvedValue("fresh");
  const server = fakeServer((c) => (auth(c) === "Bearer fresh" ? { status: 200, data: "ok" } : { status: 401 }));
  const http = client(server.adapter, { refreshAccessToken: refresh, onSessionExpired, rotatedRetryDelayMs: 1 });

  const response = await http.get("/a");

  expect(response.data).toBe("ok");
  expect(refresh).toHaveBeenCalledTimes(2);
  expect(onSessionExpired).not.toHaveBeenCalled();
});

it("session_rotated dos veces: la sesión terminó", async () => {
  const onSessionExpired = vi.fn();
  const rotated = () => httpFailure(401, { title: "x", status: 401, code: "session_rotated" });
  const refresh = vi.fn(() => Promise.reject(rotated()));
  const http = client(alwaysExpired().adapter, { refreshAccessToken: refresh, onSessionExpired, rotatedRetryDelayMs: 1 });

  const error = await failure(http.get("/a"));

  expect(error.error.kind).toBe("unauthorized");
  expect(refresh).toHaveBeenCalledTimes(2); // un solo reintento
  expect(onSessionExpired).toHaveBeenCalledTimes(1);
});

it("otro 401 del refresh (no session_rotated) termina la sesión sin reintentar", async () => {
  const onSessionExpired = vi.fn();
  const refresh = vi.fn(() => Promise.reject(httpFailure(401, { title: "x", status: 401, code: "not_authenticated" })));
  const http = client(alwaysExpired().adapter, { refreshAccessToken: refresh, onSessionExpired, rotatedRetryDelayMs: 1 });

  await failure(http.get("/a"));

  expect(refresh).toHaveBeenCalledTimes(1);
  expect(onSessionExpired).toHaveBeenCalledTimes(1);
});

// --- FE-12: `problem` (code, trace_id) sobrevive en todo kind que viene de una respuesta HTTP ---

const problemBody = (status: number, code: string) => ({ title: "t", status, code, trace_id: `trace-${status}` });

it.each([
  [400, "bad_request", "unknown"],
  [401, "not_authenticated", "unauthorized"],
  [403, "permission_denied", "forbidden"],
  [404, "not_found", "not_found"],
  [405, "http_405", "unknown"],
  [409, "conflict", "conflict"],
  [413, "http_413", "unknown"],
  [415, "http_415", "unknown"],
  [422, "validation_error", "validation"],
  [429, "rate_limited", "rate_limited"],
  [500, "internal_error", "server"],
  [503, "http_503", "server"],
])("toApiError_%i: conserva code y trace_id (kind %s -> %s)", async (status, code, kind) => {
  const server = fakeServer(() => ({ status, data: problemBody(status, code), headers: { "retry-after": "2" } }));
  const http = client(server.adapter, { tokens: memoryTokens("valid"), refreshAccessToken: () => Promise.reject(httpFailure(401)) });

  const error = await failure(http.get("/x", { retry: false }));

  expect(error.error.kind).toBe(kind);
  expect(error.traceId).toBe(`trace-${status}`);
  expect(error.error).toMatchObject({ problem: { code } });
  if (status === 429) expect(error.error).toMatchObject({ retryAfterMs: 2000 });
});

it("toApiError: un cuerpo que no es problem+json (HTML de nginx) deja problem en null", async () => {
  const server = fakeServer(() => ({ status: 429, data: "<html>429</html>" }));
  const http = client(server.adapter, { tokens: memoryTokens("valid") });

  const error = await failure(http.get("/x", { retry: false }));

  expect(error.error).toMatchObject({ kind: "rate_limited", problem: null });
  expect(error.traceId).toBeUndefined();
});

it("assertNever: cierra un switch exhaustivo sobre kind (tsc) y lanza si llega un valor no contemplado", () => {
  // Si ApiError suma un `kind` sin su caso, esta función deja de compilar (lo comprueba typecheck.mjs).
  const label = (error: ApiError): string => {
    switch (error.kind) {
      case "canceled":
      case "timeout":
      case "network":
      case "unauthorized":
      case "forbidden":
      case "not_found":
      case "conflict":
      case "validation":
      case "rate_limited":
      case "server":
      case "unknown":
        return error.kind;
      default:
        return assertNever(error);
    }
  };
  expect(label({ kind: "timeout" })).toBe("timeout");
  expect(() => label({ kind: "nuevo" } as never)).toThrow("Caso no contemplado");
});
