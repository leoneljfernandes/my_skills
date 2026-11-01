"""Marca como xfail(strict=True) las pruebas que hoy fallan por un hallazgo de la auditoría.

Cada entrada lleva el ID del hallazgo. Al corregir la skill el test pasa, `strict` lo vuelve
rojo (XPASS) y quien arregló borra la entrada: así el arreglo activa la prueba.

Uso: pytest -p xfail_plugin   (ya está en `addopts` del pyproject).
"""

import pytest

# fragmento del node id -> motivo (ID del hallazgo)
KNOWN_FAILURES: dict[str, str] = {
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        for fragment, reason in KNOWN_FAILURES.items():
            if fragment in item.nodeid:
                item.add_marker(pytest.mark.xfail(reason=reason, strict=True))
