// `tsc --noEmit` con "xfail estricto": los errores de KNOWN_TS_ERRORS se esperan (hallazgo de la
// auditoría todavía sin corregir en la skill); cualquier otro error falla, y si uno esperado
// desaparece también falla: quien arregló la skill borra la entrada.
import { spawnSync } from "node:child_process";

/** archivo (en generated/) + código TS -> ID del hallazgo que lo corrige. */
const KNOWN_TS_ERRORS = [
  // Sin entradas: FE-07 (`constructor(readonly error)` y erasableSyntaxOnly) se corrigió en la skill.
];

const run = spawnSync("npx", ["tsc", "--noEmit", "--pretty", "false"], { encoding: "utf8" });
const lines = `${run.stdout}${run.stderr}`.split("\n").filter((l) => /error TS\d+:/.test(l));
const unexpected = [];
const seen = new Set();
for (const line of lines) {
  const known = KNOWN_TS_ERRORS.find((k) => line.startsWith(`${k.file}(`) && line.includes(`error ${k.code}:`));
  if (known) seen.add(known);
  else unexpected.push(line);
}
const fixed = KNOWN_TS_ERRORS.filter((k) => !seen.has(k));
for (const k of KNOWN_TS_ERRORS.filter((k) => seen.has(k))) console.log(`xfail ${k.code} ${k.file} (${k.finding})`);
if (unexpected.length) console.error(`Errores de tipos:\n${unexpected.join("\n")}`);
for (const k of fixed) console.error(`XPASS ${k.code} ${k.file}: ya no falla; borrar la entrada de typecheck.mjs (${k.finding})`);
process.exit(unexpected.length || fixed.length ? 1 : 0);
