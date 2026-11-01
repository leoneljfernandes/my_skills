"""Registro de las menciones "verificado" de las skills (decisión D01 del plan de 2026-11-01).

Una mención tiene una de dos etiquetas:

- `verificado (test)`: hay un test en el repo que lo ejerce. `evidence` nombra dónde: pares
  (archivo bajo tests/snippets, texto que debe aparecer en él).
- `verificado a mano (AAAA-MM-DD, herramienta)`: corrida única, sin test; vale por su fecha.

`test_verified_claims_are_registered` falla si una skill menciona "verificado" sin una entrada
acá, si la entrada no coincide con la etiqueta del texto o si la evidencia dejó de existir.
Para agregar una mención nueva: escribirla con su etiqueta y registrarla acá.
"""

from dataclasses import dataclass

TEST = "test"
MANUAL = "manual"


@dataclass(frozen=True)
class Claim:
    file: str  # relativo a skills/
    anchor: str  # fragmento de la línea que contiene la mención (único dentro del archivo)
    kind: str  # TEST o MANUAL
    evidence: tuple[tuple[str, str], ...] = ()  # solo para TEST


PY = "test_python_snippets.py"
REF = "reference/build_ref.py"
W3 = "test_wave3_database.py"
WEB = "web/tests"

CLAIMS: tuple[Claim, ...] = (
    # --- con test ---
    Claim("backend/configuring-fastapi-settings/SKILL.md", "`app/config.py` (verificado", TEST,
          ((PY, "def test_settings_repr_hides_password"), (REF, "app/config.py"))),
    Claim("testing/unit-testing-fastapi-services/SKILL.md", "`tests/unit/test_order_service.py` (verificado", TEST,
          ((REF, "tests/unit/test_order_service.py"),)),
    Claim("database/modeling-postgres-with-sqlalchemy/SKILL.md", "`app/models/base.py`, verificado", TEST,
          ((PY, "def test_datetime_keeps_instant_on_sqlite"), (REF, "app/models/base.py"))),
    Claim("testing/testing-fastapi-endpoints/SKILL.md", "`tests/conftest.py` (verificado", TEST,
          ((REF, "tests/conftest.py"),)),
    Claim("testing/testing-fastapi-endpoints/SKILL.md", "`tests/test_product_factory.py` (opcional", TEST,
          ((REF, "tests/test_product_factory.py"), ("test_wave4_project.py", "def test_polyfactory_without_ignore"))),
    Claim("database/configuring-sqlalchemy-sessions/SKILL.md", "`app/database.py` async (verificado", TEST,
          ((REF, "app/database.py"),)),
    Claim("frontend/handling-react-errors/SKILL.md", "`src/lib/telemetry.ts` (verificado", TEST,
          ((f"{WEB}/skill.test.tsx", "reporter_receives_backend_trace_id"), ("web/typecheck.mjs", "tsc"))),
    Claim("frontend/building-axios-clients/SKILL.md", "`src/lib/http/errors.ts` (verificado", TEST,
          ((f"{WEB}/http-client.test.ts", "maps a 422 problem+json"), ("web/typecheck.mjs", "tsc"))),
    Claim("frontend/building-axios-clients/SKILL.md", "Tests del cliente con un adapter falso", TEST,
          ((f"{WEB}/http-client.test.ts", "retries a GET on 503"), ("generate.py", "http-client.published.test.ts"))),
    Claim("frontend/architecting-react-apps/SKILL.md", "set-state-in-effect`", TEST,
          (("generate.py", "export function useProductSearch"), ("web/typecheck.mjs", "tsc"),
           ("web/lint.mjs", "reactHooks.configs.flat.recommended"))),
    Claim("frontend/using-react-19-actions/SKILL.md", "Formulario con `useActionState`", TEST,
          ((f"{WEB}/quick-order-form.test.tsx", "quick_order_keeps_typed_quantity"), ("web/typecheck.mjs", "tsc"))),
    Claim("frontend/optimizing-react-renders/SKILL.md", "Verificados (test) con `tsc --strict`", TEST,
          (("generate.py", "export function AutoSave"), ("web/typecheck.mjs", "tsc"))),
    Claim("database/migrating-with-alembic/SKILL.md", "`SET NOT NULL` sobre una tabla grande, en tres revisiones", TEST,
          ((W3, "def test_set_not_null_skips_the_scan_after_a_validated_check"),)),
    # --- a mano (sin test; vale por su fecha y herramienta) ---
    Claim("frontend/optimizing-react-renders/SKILL.md", "Verificado a mano (2026-11-01, `vite build`)", MANUAL),
    Claim("frontend/routing-with-react-router/SKILL.md", "`src/router.tsx` (verificado", MANUAL),
    Claim("backend/layering-fastapi-apps/SKILL.md", "Flujo completo de un caso de uso", MANUAL),
    Claim("backend/handling-fastapi-errors/SKILL.md", "`app/errors.py` (verificado", MANUAL),
    Claim("database/modeling-postgres-with-sqlalchemy/SKILL.md", "SAVEPOINT por fila", MANUAL),
    Claim("database/migrating-with-alembic/SKILL.md", "`alembic/env.py` (verificado", MANUAL),
    Claim("database/migrating-with-alembic/SKILL.md", "Tres revisiones escritas a mano", MANUAL),
    Claim("database/configuring-sqlalchemy-sessions/SKILL.md", "Variante síncrona", MANUAL),
    Claim("observability/defining-grafana-slos/SKILL.md", "orders-api-slo.yml` (verificado", MANUAL),
    Claim("observability/defining-grafana-slos/SKILL.md", "alertmanager.yml` (verificado", MANUAL),
    Claim("observability/defining-grafana-slos/references/stack.md", "Versiones verificadas", MANUAL),
    Claim("observability/logging-json-to-loki/SKILL.md", "`app/observability/logging.py` (verificado", MANUAL),
    Claim("observability/exposing-prometheus-metrics/SKILL.md", "`app/observability/metrics.py` (verificado", MANUAL),
    Claim("observability/tracing-with-opentelemetry/SKILL.md", "`app/observability/tracing.py` (verificado", MANUAL),
)
