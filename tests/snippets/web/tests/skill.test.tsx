import { cleanup, render } from "@testing-library/react";
import { AxiosError } from "axios";
import { useState, type ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { DefaultFallback, ErrorBoundary } from "../generated/components/ErrorBoundary";
import { createHttpClient } from "../generated/lib/http/client";
import { ApiRequestError } from "../generated/lib/http/errors";
import { reportError, setErrorReporter } from "../generated/lib/telemetry";

afterEach(cleanup);

const memoryTokens = () => {
  let token: string | null = "old";
  return { getAccessToken: () => token, setAccessToken: (t: string | null) => (token = t) };
};
const reply = (config: never, status: number) =>
  Promise.reject(
    new AxiosError("x", "ERR", config, {}, { status, data: {}, headers: {}, config, statusText: "" }),
  );

it("session_expires_once", async () => {
  const onSessionExpired = vi.fn();
  const http = createHttpClient({
    baseURL: "/",
    tokens: memoryTokens(),
    refreshAccessToken: () => Promise.reject(new Error("refresh failed")),
    onSessionExpired,
  });
  http.defaults.adapter = (c) => reply(c as never, 401);
  await Promise.allSettled([http.get("/a"), http.get("/b"), http.get("/c")]);
  expect(onSessionExpired).toHaveBeenCalledTimes(1);
});

it("abort_in_backoff_is_typed", async () => {
  const controller = new AbortController();
  const http = createHttpClient({
    baseURL: "/",
    tokens: memoryTokens(),
    refreshAccessToken: () => Promise.resolve("x"),
    onSessionExpired: () => undefined,
    baseDelayMs: 100_000,
    maxDelayMs: 100_000,
  });
  http.defaults.adapter = (c) => reply(c as never, 503);
  const pending = http.get("/a", { signal: controller.signal }).catch((e: unknown) => e);
  await new Promise((r) => setTimeout(r, 30));
  controller.abort();
  const error = (await Promise.race([pending, new Promise((r) => setTimeout(() => r("TIMEOUT"), 500))])) as ApiRequestError;
  expect(error).toBeInstanceOf(ApiRequestError);
  expect(error.error.kind).toBe("canceled");
});

let failing = false;
function Flaky(): ReactNode {
  if (failing) throw new Error("roto");
  return <p>ok</p>;
}

it("boundary_reports_once_on_navigation", () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const reporter = vi.fn();
  setErrorReporter(reporter);
  failing = false;
  const fallback = DefaultFallback;
  const { rerender } = render(
    <ErrorBoundary scope="c" fallback={fallback} resetKeys={["/a"]}><Flaky /></ErrorBoundary>,
  );
  failing = true;
  rerender(<ErrorBoundary scope="c" fallback={fallback} resetKeys={["/b"]}><Flaky /></ErrorBoundary>);
  expect(reporter).toHaveBeenCalledTimes(1);
  vi.restoreAllMocks();
});

it("fallback_with_hooks_renders", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  setErrorReporter(() => undefined);
  failing = true;
  function HookedFallback(): ReactNode {
    const [clicks] = useState(0); // un fallback con hooks debe poder renderizarse
    return <p role="alert">fallback {clicks}</p>;
  }
  const { findByRole } = render(
    <ErrorBoundary scope="c" fallback={HookedFallback}><Flaky /></ErrorBoundary>,
  );
  expect((await findByRole("alert")).textContent).toBe("fallback 0");
  vi.restoreAllMocks();
});

it("reporter_receives_backend_trace_id", () => {
  const reporter = vi.fn();
  setErrorReporter(reporter);
  reportError(Object.assign(new Error("x"), { traceId: "abc123" }), { scope: "s" });
  expect(reporter).toHaveBeenCalledWith(expect.any(Error), expect.objectContaining({ traceId: "abc123" }));
});
