// @vitest-environment node
// El vite.config.ts publicado en building-axios-clients: proxy desde FRONTEND_API_PROXY_TARGET, alias
// @/ y plugin de React. loadEnv lee también process.env, así que el test fija la variable ahí.
import { afterEach, expect, it, vi } from "vitest";
import type { ConfigEnv, UserConfig } from "vite";

import viteConfig from "@/vite.config";

const resolveConfig = (env: Partial<ConfigEnv>): UserConfig =>
  (viteConfig as (env: ConfigEnv) => UserConfig)({ command: "serve", mode: "development", ...env } as ConfigEnv);

afterEach(() => {
  vi.unstubAllEnvs();
});

it("vite_config_proxies_api_to_FRONTEND_API_PROXY_TARGET", () => {
  vi.stubEnv("FRONTEND_API_PROXY_TARGET", "http://localhost:8000");
  const config = resolveConfig({});
  expect(config.server?.proxy).toEqual({ "/api": { target: "http://localhost:8000", changeOrigin: true } });
  expect(config.resolve?.alias).toMatchObject({ "@": expect.stringMatching(/\/src$/) });
  expect(config.plugins?.length).toBeGreaterThan(0);
});

it("vite_config_fails_at_startup_without_the_target (dev server); build y tests no lo necesitan", () => {
  vi.stubEnv("FRONTEND_API_PROXY_TARGET", "");
  expect(() => resolveConfig({})).toThrow("Falta FRONTEND_API_PROXY_TARGET");
  expect(resolveConfig({ command: "build", mode: "production" }).server?.proxy).toEqual({});
  expect(resolveConfig({ mode: "test" }).server?.proxy).toEqual({});
});
