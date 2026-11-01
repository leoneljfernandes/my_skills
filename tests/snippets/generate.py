"""Escribe en web/generated/ el código TypeScript publicado en las skills (lo corre `npm test`)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import block  # noqa: E402

OUT = Path(__file__).parent / "web" / "generated"

TARGETS = [
    ("building-axios-clients", "export function toApiError", "lib/http/errors.ts"),
    ("building-axios-clients", "export function createHttpClient", "lib/http/client.ts"),
    ("handling-react-errors", "export function setErrorReporter", "lib/telemetry.ts"),
    ("handling-react-errors", "class ErrorBoundary", "components/ErrorBoundary.tsx"),
    ("using-react-19-actions", "export function NameForm", "NameForm.tsx"),
]

for skill, marker, dest in TARGETS:
    path = OUT / dest
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(block(skill, marker), encoding="utf-8")
    except LookupError as exc:
        path.unlink(missing_ok=True)
        print(f"AVISO: {exc}", file=sys.stderr)


# Funciones sueltas que se prueban solas (sin el resto del bloque que las contiene).
def function_source(skill: str, marker: str, dest: str) -> None:
    text = block(skill, marker)
    start = text.index(marker)
    end = text.index("\n}\n", start) + 3
    path = OUT / dest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text[start:end] + "\n", encoding="utf-8")


function_source("routing-with-react-router", "export function safeNext", "safe-next.ts")
