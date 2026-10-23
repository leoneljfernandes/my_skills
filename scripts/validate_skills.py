"""Valida el estándar de la biblioteca de skills.

Uso: uv run --with pyyaml python scripts/validate_skills.py
Sale con código 1 si alguna skill no cumple.
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
DOMAINS = {"frontend", "backend", "database", "testing", "observability"}
REQUIRED_KEYS = ("name", "description", "domain", "tags", "triggers")
REQUIRED_SECTIONS = ("## Contexto y reglas", "## Ejemplos", "## Checklist de verificación")
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        raise ValueError("falta frontmatter YAML")
    _, raw, body = text.split("---\n", 2)
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError("frontmatter no es un mapa YAML")
    return data, body


def check_common(path: Path, meta: dict[str, object], body: str, expected_name: str) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in meta:
            errors.append(f"falta la clave '{key}'")
    name = meta.get("name")
    if name != expected_name:
        errors.append(f"name '{name}' != '{expected_name}'")
    if isinstance(name, str) and not NAME_RE.match(name):
        errors.append("name solo admite minúsculas, números y guiones")
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.startswith("Use when"):
        errors.append("description debe empezar con 'Use when'")
    elif len(desc) > 1024:
        errors.append(f"description tiene {len(desc)} caracteres (máx. 1024)")
    if meta.get("domain") not in DOMAINS:
        errors.append(f"domain '{meta.get('domain')}' no es uno de {sorted(DOMAINS)}")
    elif meta["domain"] not in path.parts:
        errors.append(f"domain '{meta['domain']}' no coincide con el directorio")
    for key in ("tags", "triggers"):
        value = meta.get(key)
        if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            errors.append(f"'{key}' debe ser una lista no vacía de strings")
    if body.count("```") % 2:
        errors.append("bloque de código sin cerrar")
    prose = FENCE_RE.sub("", body)  # los links dentro de bloques de código no son links
    for target in LINK_RE.findall(prose):
        if not (path.parent / target.split("#")[0]).exists():
            errors.append(f"link roto: {target}")
    return errors


def main() -> int:
    failures = 0
    skill_files = sorted(SKILLS.glob("*/*/SKILL.md"))
    index_files = sorted(SKILLS.glob("*/*-index.md"))
    for path in skill_files:
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        errors = check_common(path, meta, body, path.parent.name)
        errors += [f"falta la sección '{s}'" for s in REQUIRED_SECTIONS if s not in body]
        failures += report(path, errors, body)
    for path in index_files:
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        failures += report(path, check_common(path, meta, body, path.stem), body)
    print(f"\n{len(skill_files)} skills + {len(index_files)} índices revisados, {failures} con errores")
    return 1 if failures else 0


def report(path: Path, errors: list[str], body: str) -> int:
    rel = path.relative_to(ROOT)
    words = len(body.split())
    if errors:
        print(f"FAIL {rel}")
        for err in errors:
            print(f"     - {err}")
        return 1
    print(f"ok   {rel} ({words} palabras)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
