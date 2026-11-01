// ESLint sobre lo que publican las skills:
//  1. La configuración de arquitectura de architecting-react-apps contra imports buenos y malos
//     (lint-fixtures/): los `good-*` no dan errores; cada `bad-*` da `no-restricted-imports`.
//  2. La configuración `recommended` de eslint-plugin-react-hooks sobre todos los bloques de React
//     generados: 0 errores (incluye `set-state-in-effect` y `refs`).
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

const here = (path) => fileURLToPath(new URL(path, import.meta.url));
const problems = [];

// 1) arquitectura
const architecture = new ESLint({
  cwd: here("./lint-fixtures"),
  overrideConfigFile: here("./generated/eslint.config.js"),
});
const results = await architecture.lintFiles(["src/**/*.{ts,tsx}"]);
const seen = results.map((r) => r.filePath.split("lint-fixtures/")[1]);
for (const result of results) {
  const name = result.filePath.split("lint-fixtures/")[1];
  const base = name.split("/").at(-1);
  const rules = result.messages.map((m) => m.ruleId);
  if (result.messages.some((m) => m.fatal)) problems.push(`${name}: no parsea (${result.messages[0].message})`);
  else if (base.startsWith("bad-") && !rules.includes("no-restricted-imports")) problems.push(`${name}: debería violar no-restricted-imports y pasa`);
  else if (!base.startsWith("bad-") && result.messages.length) problems.push(`${name}: debería pasar y da ${rules.join(", ")}`);
}
if (seen.length < 15) problems.push(`solo se analizaron ${seen.length} fixtures`);
console.log(`arquitectura: ${seen.length} fixtures (${seen.filter((n) => n.includes("bad-")).length} malos)`);

// 2) react-hooks recommended sobre los bloques
const hooks = new ESLint({
  cwd: here("./"),
  overrideConfigFile: true,
  overrideConfig: [
    { files: ["generated/**/*.{ts,tsx}"], languageOptions: { parser: tseslint.parser }, plugins: {} },
    { ...reactHooks.configs.flat.recommended, files: ["generated/**/*.{ts,tsx}"] },
  ],
});
const hookResults = await hooks.lintFiles(["generated/**/*.{ts,tsx}"]);
let checked = 0;
for (const result of hookResults) {
  checked += 1;
  for (const m of result.messages) problems.push(`${result.filePath.split("web/")[1]}:${m.line} ${m.ruleId ?? "parse"}: ${m.message}`);
}
console.log(`react-hooks recommended: ${checked} archivos generados`);

if (problems.length) {
  console.error(`ESLint:\n${problems.join("\n")}`);
  process.exit(1);
}
