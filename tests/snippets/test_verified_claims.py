"""D01: toda mención "verificado" de las skills está registrada y dice lo que respalda."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import SKILLS  # noqa: E402
from verified_claims import CLAIMS, MANUAL, TEST  # noqa: E402

HERE = Path(__file__).parent
MENTION = re.compile(r"\bverificad[oa]s?\b", re.IGNORECASE)
LABEL = {
    TEST: re.compile(r"\bverificad[oa]s? \(test\)", re.IGNORECASE),
    MANUAL: re.compile(r"\bverificad[oa]s? a mano \(\d{4}-\d{2}-\d{2}, [^)]+\)", re.IGNORECASE),
}


def mentions() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(SKILLS.rglob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if MENTION.search(line):
                found.append((str(path.relative_to(SKILLS)), number, line))
    return found


def test_verified_claims_are_registered():
    problems: list[str] = []
    used: set[int] = set()
    for rel, number, line in mentions():
        matches = [i for i, c in enumerate(CLAIMS) if c.file == rel and c.anchor in line]
        if len(matches) != 1:
            problems.append(f"{rel}:{number}: mención sin registrar (o registrada dos veces) en verified_claims.py")
            continue
        used.add(matches[0])
        claim = CLAIMS[matches[0]]
        if not LABEL[claim.kind].search(line):
            expected = "`verificado (test)`" if claim.kind == TEST else "`verificado a mano (AAAA-MM-DD, herramienta)`"
            problems.append(f"{rel}:{number}: el texto debería usar la etiqueta {expected}")
    for i, claim in enumerate(CLAIMS):
        if i not in used:
            problems.append(f"{claim.file}: la entrada {claim.anchor!r} no corresponde a ninguna mención")
        for test_file, needle in claim.evidence:
            target = HERE / test_file
            if not target.is_file() or needle not in target.read_text(encoding="utf-8"):
                problems.append(f"{claim.file}: {claim.anchor!r} cita {test_file} con {needle!r}, que no existe")
    assert not problems, "\n".join(problems)
