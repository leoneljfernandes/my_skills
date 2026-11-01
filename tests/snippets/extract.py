"""Extrae bloques de código de las SKILL.md para ejecutarlos.

Uso: python extract.py <skill> <marcador> <destino>
Copia a <destino> el bloque de código de la skill que contiene <marcador>.
"""

import re
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent / "skills"
FENCE = re.compile(r"```\w*\n(.*?)```", re.DOTALL)


def skill_path(name: str) -> Path:
    found = list(SKILLS.glob(f"*/{name}/SKILL.md"))
    if len(found) != 1:
        raise FileNotFoundError(f"skill no encontrada: {name}")
    return found[0]


def block(name: str, marker: str, *, nth: int = 0) -> str:
    """Devuelve el bloque que contiene `marker` (el `nth`-ésimo si hay varios)."""
    text = skill_path(name).read_text(encoding="utf-8")
    hits = [b for b in FENCE.findall(text) if marker in b]
    if len(hits) <= nth:
        raise LookupError(f"{name}: ningún bloque contiene {marker!r}")
    return hits[nth]


def all_text() -> dict[str, str]:
    return {p.parent.name: p.read_text(encoding="utf-8") for p in SKILLS.glob("*/*/SKILL.md")}


if __name__ == "__main__":
    skill, marker, dest = sys.argv[1:4]
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_text(block(skill, marker), encoding="utf-8")
