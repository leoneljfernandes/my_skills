import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // `generated/` hace de `src/` (ver tsconfig.json): el alias `@/` es el que prescriben las skills.
  resolve: { alias: { "@": fileURLToPath(new URL("./generated", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["tests/helpers/setup-request.ts"],
    include: ["tests/**/*.test.{ts,tsx}", "generated/**/*.test.ts"],
  },
});
