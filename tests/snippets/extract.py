"""Extrae bloques de código de las SKILL.md para ejecutarlos.

Uso: python extract.py <skill> <marcador> <destino>
Copia a <destino> el bloque de código de la skill que contiene <marcador>.
"""

import os
import re
import sys
from pathlib import Path

# SKILLS_DIR permite correr los tests contra una copia de las skills (p. ej. con un arreglo revertido
# para ver el test en rojo) sin tocar el repo.
SKILLS = Path(os.environ.get("SKILLS_DIR") or Path(__file__).resolve().parent.parent.parent / "skills")
FENCE = re.compile(r"```\w*\n(.*?)```", re.DOTALL)


def skill_path(name: str, file: str = "SKILL.md") -> Path:
    """Ruta de un archivo de la skill; `file` puede ser `references/security.md`."""
    found = list(SKILLS.glob(f"*/{name}/{file}"))
    if len(found) != 1:
        raise FileNotFoundError(f"archivo no encontrado: {name}/{file}")
    return found[0]


def block(name: str, marker: str, *, nth: int = 0, file: str = "SKILL.md") -> str:
    """Devuelve el bloque que contiene `marker` (el `nth`-ésimo si hay varios).

    `file` permite leer de `references/*.md` en vez de `SKILL.md`.
    """
    text = skill_path(name, file).read_text(encoding="utf-8")
    hits = [b for b in FENCE.findall(text) if marker in b]
    if len(hits) <= nth:
        raise LookupError(f"{name}: ningún bloque contiene {marker!r}")
    return hits[nth]


def all_text() -> dict[str, str]:
    """Todo el texto de las skills, por ruta relativa a `skills/`: cada `.md` y los `templates/*.py`."""
    paths = [*SKILLS.rglob("*.md"), *SKILLS.glob("*/*/templates/*.py")]
    return {str(p.relative_to(SKILLS)): p.read_text(encoding="utf-8") for p in sorted(paths)}


def fenced_blocks(text: str) -> list[tuple[str, str, int]]:
    """Bloques con valla: (lenguaje, código, línea donde empieza el código)."""
    return [
        (m.group(1), m.group(2), text.count("\n", 0, m.start(2)) + 1)
        for m in re.finditer(r"```(\w*)\n(.*?)```", text, re.DOTALL)
    ]


if __name__ == "__main__":
    skill, marker, dest = sys.argv[1:4]
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_text(block(skill, marker), encoding="utf-8")
