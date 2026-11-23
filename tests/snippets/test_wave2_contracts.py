"""Ola 2 (contratos del backend): lo que se comprueba leyendo las skills, sin levantar nada.

Uso (desde la raíz del repo), igual que los demás tests de este directorio:
    uv run --with pytest --with pydantic-settings --with fastapi --with 'sqlalchemy>=2.0.40,<2.1' --with pyyaml \
        pytest tests/snippets/test_wave2_contracts.py -v
"""

import re
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from extract import SKILLS, all_text, block, fenced_blocks  # noqa: E402
from test_python_snippets import load_settings_module  # noqa: E402

SCAF = "scaffolding-fastapi-backends"
REFS = {"file": "references/{}.md"}


def text(rel: str) -> str:
    return (SKILLS / rel).read_text(encoding="utf-8")


def ref(name: str) -> str:
    return text(f"backend/{SCAF}/references/{name}.md")


def toml_block(skill_text: str, table: str) -> dict:
    for lang, code, _ in fenced_blocks(skill_text):
        if lang == "toml" and table in code:
            return tomllib.loads(code)
    raise LookupError(table)


def yaml_blocks(md: str) -> list[dict]:
    return [yaml.safe_load(code) for lang, code, _ in fenced_blocks(md) if lang == "yaml"]


# --- BE-01 · TS-02 · TS-16 -------------------------------------------------------------------------


def test_both_pytest_tables_are_identical_and_importable_without_pythonpath():
    scaffolding = toml_block(text(f"backend/{SCAF}/SKILL.md"), "tool.pytest")["tool"]["pytest"]["ini_options"]
    endpoints = toml_block(text("testing/testing-fastapi-endpoints/SKILL.md"), "tool.pytest")["tool"]["pytest"]["ini_options"]
    assert scaffolding == endpoints
    assert scaffolding["pythonpath"] == ["."]
    assert scaffolding["filterwarnings"] == ["error::sqlalchemy.exc.SAWarning"]
    assert "PYTHONPATH:" not in "".join(code for lang, code, _ in fenced_blocks(ref("ci")) if lang == "yaml")


def test_tests_block_imports_what_it_uses():
    code = block("testing-fastapi-endpoints", "test_place_order_decrements_stock")
    assert "from tests.factories import create_product" in code


# --- BE-02 · TS-10 ---------------------------------------------------------------------------------


def test_bootstrap_has_one_dependency_list_and_the_pyproject_is_a_valid_project():
    skill = text(f"backend/{SCAF}/SKILL.md")
    project = toml_block(skill, "[project]")["project"]
    assert project["name"] and project["version"]  # sin name, `uv lock` falla
    assert "uv init --bare" in skill
    bash = "".join(code for lang, code, _ in fenced_blocks(skill) if lang == "bash")
    assert not re.search(r"^uv add", bash, re.MULTILINE) and "uv sync" in bash  # una sola lista: el pyproject
    deps = " ".join(project["dependencies"])
    assert "email-validator" in deps and "opentelemetry-api" in deps
    assert "coverage" in toml_block(skill, "[project]")["dependency-groups"]["dev"]


# --- BE-04 -----------------------------------------------------------------------------------------


def test_installs_use_locked_not_frozen():
    for rel in (f"backend/{SCAF}/references/ci.md", f"backend/{SCAF}/references/docker.md"):
        commands = re.findall(r"uv sync[^\n`]*", text(rel))
        assert commands and all("--locked" in c for c in commands if "--frozen" not in c.split(":")[0]), (rel, commands)
        assert not any("--frozen" in c and "RUN" in c for c in commands)
    assert "RUN uv sync --locked" in ref("docker")
    assert "command: uv sync --locked" in ref("ci")


# --- BE-12 · BE-17 ---------------------------------------------------------------------------------


def test_scaffolding_and_layering_publish_the_same_import_contracts():
    scaf = toml_block(text(f"backend/{SCAF}/SKILL.md"), "tool.importlinter")["tool"]
    lay = toml_block(text("backend/layering-fastapi-apps/SKILL.md"), "tool.importlinter")["tool"]
    assert scaf["importlinter"] == lay["importlinter"]
    assert "ruff" in scaf and scaf["ruff"]["lint"]["select"]
    forbidden = [c for c in scaf["importlinter"]["contracts"] if c["type"] == "forbidden"]
    assert any(c["source_modules"] == ["app.api"] and "app.crud" in c["forbidden_modules"] for c in forbidden)
    ci = yaml_blocks(ref("ci"))[0]
    lint = " ".join(step["run"]["command"] for step in ci["jobs"]["lint"]["steps"] if isinstance(step, dict) and "run" in step)
    assert all(tool in lint for tool in ("ruff check", "mypy app", "lint-imports"))


def test_layering_table_lets_the_composition_root_import_crud_and_services_import_observability():
    layering = text("backend/layering-fastapi-apps/SKILL.md")
    api_row = next(line for line in layering.splitlines() if line.startswith("| `api/`"))
    services_row = next(line for line in layering.splitlines() if line.startswith("| `services/`"))
    assert "Solo `api/deps.py`" in api_row and "`crud`" in api_row and "`database`" in api_row
    assert "`observability`" in services_row and "`security`" in services_row


# --- BE-23 · DB-16 · OB-25 -------------------------------------------------------------------------

POSTGRES_IMAGE = re.compile(r"(?<![\w/])postgres:([\w.\-]+)")
CIMG_POSTGRES = re.compile(r"cimg/postgres:([\w.\-]+)")


def test_postgres_tag_is_exact_and_identical_in_compose_ci_and_conftest():
    compose = next(y for y in yaml_blocks(ref("docker")) if y and "services" in y and "db" in y["services"])
    in_compose = compose["services"]["db"]["image"]
    in_ci = next(i["image"] for job in yaml_blocks(ref("ci"))[0]["jobs"].values() for i in job.get("docker", []) if "postgres" in i["image"])
    in_conftest = re.search(r'PostgresContainer\("([^"]+)"', text("testing/testing-fastapi-endpoints/SKILL.md")).group(1)
    versions = {
        POSTGRES_IMAGE.search(in_compose).group(1).split("-")[0],
        CIMG_POSTGRES.search(in_ci).group(1),
        POSTGRES_IMAGE.search(in_conftest).group(1).split("-")[0],
    }
    assert len(versions) == 1, (in_compose, in_ci, in_conftest)
    (version,) = versions
    assert re.fullmatch(r"\d+\.\d+", version), f"tag no exacto: {version}"


def test_no_floating_postgres_tag_anywhere():
    floating = []
    for rel, body in all_text().items():
        for tag in POSTGRES_IMAGE.findall(body) + CIMG_POSTGRES.findall(body):
            if not re.match(r"\d+\.\d+(-alpine)?$", tag):
                floating.append(f"{rel}: {tag}")
    assert not floating, floating


def test_uv_is_pinned_to_the_same_series_in_docker_and_ci():
    series = re.search(r"astral-sh/uv:(\d+\.\d+)", ref("docker")).group(1)
    assert f'uv=={series}.*' in ref("ci")


PIN = "sqlalchemy[asyncio]>=2.0.40,<2.1"
PIN_SHAPE = re.compile(r"sqlalchemy(?:\[\w+\])?(?:[<>=!~]=?\d[\w.]*,?)+")  # sin espacios: la forma de un pin nuestro


def test_sqlalchemy_pin_has_one_form_in_the_skills():
    seen: dict[str, set[str]] = {}
    for rel, body in all_text().items():
        for found in PIN_SHAPE.findall(body):
            seen.setdefault(found.rstrip(","), set()).add(rel)
    assert set(seen) <= {PIN}, {pin: sorted(files) for pin, files in seen.items() if pin != PIN}
    files = " ".join(seen[PIN])
    assert "scaffolding-fastapi-backends/SKILL.md" in files
    assert "tracing-with-opentelemetry/SKILL.md" in files
    assert "configuring-sqlalchemy-sessions/SKILL.md" in files


def test_tracing_cites_both_instrumentation_versions():
    assert "0.66b1 y 0.66b2" in text("observability/tracing-with-opentelemetry/SKILL.md")


# --- BE-06 · BE-14 · BE-15 · BE-16 · BE-22 ---------------------------------------------------------


def _env_example_keys() -> tuple[dict[str, str], set[str]]:
    code = next(c for lang, c, _ in fenced_blocks(text("backend/configuring-fastapi-settings/SKILL.md")) if lang == "ini" and "SECRET_KEY" in c)
    active, commented = {}, set()
    for line in code.splitlines():
        if m := re.match(r"([A-Z][A-Z0-9_]+)=([^#\n]*)", line):
            active[m.group(1)] = m.group(2).strip()
        elif m := re.match(r"# ([A-Z][A-Z0-9_]+)=", line):
            commented.add(m.group(1))
    return active, commented


NOT_SETTINGS = {"FRONTEND_API_PROXY_TARGET", "GRAFANA_USER", "GRAFANA_PASSWORD"}


def test_env_example_lists_every_settings_field(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch)
    active, commented = _env_example_keys()
    listed = (set(active) | commented) - NOT_SETTINGS
    assert listed == set(mod.Settings.model_fields)
    assert NOT_SETTINGS <= set(active) | commented
    assert "APP_ENV" in commented and "APP_ENV" not in active  # no elige stage desde el archivo
    assert active["SECRET_KEY"] == ""  # D2: el ejemplo no pasa la validación


def test_env_example_is_a_usable_dotenv_once_the_secret_is_generated(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch)
    for key in ("SECRET_KEY", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME", "ERRORS_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    code = next(c for lang, c, _ in fenced_blocks(text("backend/configuring-fastapi-settings/SKILL.md")) if lang == "ini" and "SECRET_KEY" in c)
    (tmp_path / ".env").write_text(code, encoding="utf-8")
    with pytest.raises(Exception, match="SECRET_KEY"):
        mod.Settings(_env_file=tmp_path / ".env")  # tal cual: falla
    (tmp_path / ".env").write_text(code.replace("SECRET_KEY=", "SECRET_KEY=" + "k" * 40, 1), encoding="utf-8")
    settings = mod.Settings(_env_file=tmp_path / ".env")
    assert settings.DOCS_ENABLED is True and settings.COOKIE_SECURE is False and settings.METRICS_ENABLED is False


def _stage(tmp_path, monkeypatch, files: dict[str, str], **env: str):
    mod = load_settings_module(tmp_path, monkeypatch, **env)
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    mod.ROOT_DIR = tmp_path
    mod.get_settings.cache_clear()
    return mod


def test_case_a_app_env_in_dotenv_does_not_choose_the_stage(tmp_path, monkeypatch):
    mod = _stage(tmp_path, monkeypatch, {".env": "APP_ENV=staging\n", ".env.staging": "LOG_LEVEL=DEBUG\n"})
    with pytest.raises(RuntimeError, match="export APP_ENV"):
        mod.get_settings()


def test_case_b_app_env_test_in_dotenv_does_not_skip_the_dotenv(tmp_path, monkeypatch):
    mod = _stage(tmp_path, monkeypatch, {".env": "APP_ENV=test\nLOG_LEVEL=DEBUG\n"})
    with pytest.raises(RuntimeError, match="export APP_ENV"):
        mod.get_settings()


def test_case_c_app_env_prod_in_dotenv_does_not_apply_dev_values(tmp_path, monkeypatch):
    mod = _stage(tmp_path, monkeypatch, {".env": "APP_ENV=prod\n", ".env.dev": "LOG_LEVEL=DEBUG\n"})
    with pytest.raises(RuntimeError, match="export APP_ENV"):
        mod.get_settings()


def test_exported_stage_loads_its_file(tmp_path, monkeypatch):
    mod = _stage(tmp_path, monkeypatch, {".env.staging": "LOG_LEVEL=DEBUG\n"}, APP_ENV="staging", COOKIE_SECURE="true")
    assert mod.get_settings().LOG_LEVEL == "DEBUG"


@pytest.mark.parametrize("key", ["test-secret-key-not-for-production-32b+", "changeme" * 5, "generar-con-secrets-token-urlsafe-32"])
def test_staging_and_prod_reject_example_secret_keys(tmp_path, monkeypatch, key):
    mod = load_settings_module(tmp_path, monkeypatch, APP_ENV="staging", SECRET_KEY=key, COOKIE_SECURE="true")
    with pytest.raises(Exception, match="example value"):
        mod.Settings(_env_file=None)
    assert load_settings_module(tmp_path, monkeypatch, SECRET_KEY=key).Settings(_env_file=None)  # dev: sí vale


def test_flags_and_owner_fields_exist_and_is_prod_is_gone(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch)
    settings = mod.Settings(_env_file=None)
    assert settings.DOCS_ENABLED is False and settings.METRICS_ENABLED is False
    assert settings.OWNER_EMAIL is None and settings.OWNER_PASSWORD is None
    assert mod.Settings.model_fields["OWNER_PASSWORD"].annotation == mod.SecretStr | None
    assert not hasattr(settings, "is_prod")
    assert "is_prod" not in " ".join(all_text().values())


def test_only_the_settings_and_conftest_blocks_read_the_environment():
    allowed = {"backend/configuring-fastapi-settings/SKILL.md", "testing/testing-fastapi-endpoints/SKILL.md"}
    offenders = []
    for rel, body in all_text().items():
        if rel in allowed:
            continue
        for lang, code, line in fenced_blocks(body):
            if lang == "python" and re.search(r"os\.(environ|getenv)", code):
                offenders.append(f"{rel}:{line}")
    assert not offenders, offenders
    assert "get_settings()" in ref("security").split("## Primer usuario")[1].split("##")[0]


def test_settings_skill_points_to_the_conftest_instead_of_repeating_it():
    settings = text("backend/configuring-fastapi-settings/SKILL.md")
    assert 'setdefault("DB_HOST"' not in settings
    assert "testing-fastapi-endpoints" in settings and "test-db.invalid" in settings
    conftest = block("testing-fastapi-endpoints", "def _sqlite_memory_engine")
    assert '"test-db.invalid"' in conftest
    assert "tests" not in next(line for line in ref("docker").splitlines() if ":5432" in line and "ports" not in line and "DB_PORT:-5432" in line)


def test_product_resource_is_published_with_the_integrity_error_pattern():
    """C1/C2: el recurso producto es bloque publicado (no pegamento) y usa el patrón de handling."""
    service = block("layering-fastapi-apps", "class ProductService")
    fragment = block("handling-fastapi-errors", "except IntegrityError as exc:")
    assert all(line.strip() in service for line in fragment.splitlines() if line.strip())
    order = block("layering-fastapi-apps", "class OrderService")
    assert "class InsufficientStockError(BusinessRuleError)" in order and "from app.errors import BusinessRuleError" in order
    assert "class InsufficientStockError" not in block("handling-fastapi-errors", "class AppError")
    build = (Path(__file__).parent / "reference" / "build_ref.py").read_text(encoding="utf-8")
    for marker in ("class ProductService", "class ProductCreate(BaseModel)", 'router = APIRouter(prefix="/products"'):
        assert f"block('layering-fastapi-apps','{marker}')" in build, marker


def test_step_markers_leave_a_valid_app_at_steps_2_and_3():
    """C3: sin las líneas `# paso 4`, main.py no incluye api_router y deps.py solo compone la salud."""
    import ast

    from test_wave2_project import strip_steps

    main = block("layering-fastapi-apps", "def create_app")
    deps = block("layering-fastapi-apps", "def get_order_service")
    router = block("layering-fastapi-apps", "api_router = APIRouter()")
    for step in (2, 3):
        assert "api_router" not in strip_steps(main, step)
        assert "orders" not in strip_steps(router, step) and "products" not in strip_steps(router, step)
    step3 = strip_steps(deps, 3)
    ast.parse(step3)
    assert "HealthRepoDep" in step3 and "Order" not in step3 and "Product" not in step3
    assert "# paso 8" not in main  # observabilidad es el paso 9 desde que el frontend es el 7


def test_env_fixture_is_the_published_one_and_the_reference_uses_it():
    """C6: el fixture `env` publicado (cache_clear antes y después) es el que corre la referencia."""
    code = block("configuring-fastapi-settings", "def env(monkeypatch")
    fixture = "@pytest.fixture\n" + code.split("@pytest.fixture\n", 1)[1].split("\n\n\n", 1)[0]
    assert fixture.count("get_settings.cache_clear()") == 2
    wave2 = (Path(__file__).parent / "reference" / "wave2_tests" / "test_wave2_app.py").read_text(encoding="utf-8")
    assert fixture in wave2
    assert "monkeypatch.setenv" not in text("backend/configuring-fastapi-settings/SKILL.md")  # sin el snippet suelto


# --- BE-05 · BE-19 · BE-24 · BE-09 -----------------------------------------------------------------


def test_foreign_resource_is_404_in_both_skills():
    security, handling = ref("security"), text("backend/handling-fastapi-errors/SKILL.md")
    assert "recurso ajeno (404)" in security and "recurso ajeno (403)" not in security
    assert re.search(r"Ownership \| 404 si no existe o el usuario no puede verlo; 403 solo si", security)
    assert "ajeno sin permiso de ver | `NotFoundError` | 404" in handling


def test_error_body_description_matches_what_the_handlers_send():
    handling = text("backend/handling-fastapi-errors/SKILL.md")
    assert "`detail` solo si hay un mensaje específico" in handling
    assert "no saben nada de HTTP" not in handling
    assert "declara su traducción HTTP" in handling


def test_session_rotated_contract_is_documented_on_both_sides():
    handling, security = text("backend/handling-fastapi-errors/SKILL.md"), ref("security")
    assert 'code = "session_rotated"' in handling and "class SessionRotatedError(NotAuthenticatedError)" in handling
    assert "SessionRotatedError" in security and "Contrato con el cliente" in security
    assert "una sola vez" in security and "get_by_hash_for_update" in security
    assert "{ id: number, email: string, role: string, permissions: string[] }" in security


# --- BE-13 · BE-21 · BE-11 -------------------------------------------------------------------------


def test_compose_publishes_only_the_frontend_and_the_override_adds_the_dev_ports():
    docker = ref("docker")
    compose, override = (y for y in yaml_blocks(docker) if y and "services" in y)
    published = {name for name, svc in compose["services"].items() if "ports" in svc}
    assert published == {"frontend"}
    assert "volumes" not in compose["services"]["backend"] or compose["services"]["backend"]["volumes"] == []
    assert "command" not in compose["services"]["backend"]
    assert set(override["services"]) == {"db", "migrate", "backend"}
    assert "--reload" in override["services"]["backend"]["command"] and override["services"]["backend"]["ports"]
    # A1: el stage se exporta en compose (prod) y el override lo baja a dev; el .env de la raíz es de desarrollo.
    for service in ("migrate", "backend"):
        assert compose["services"][service]["environment"]["APP_ENV"] == "prod"
        assert override["services"][service]["environment"]["APP_ENV"] == "dev"
    assert "**solo de desarrollo**" in docker and "El mismo `.env` sirve desde el host" not in docker
    # A2: TLS termina delante de nginx, que reenvía el esquema del terminador.
    assert "X-Forwarded-Proto $scheme" not in docker and "X-Forwarded-Proto $http_x_forwarded_proto" in docker
    assert all("container_name" not in svc for svc in compose["services"].values())
    assert "backend_app" not in " ".join(all_text().values())


def test_ci_has_a_mandatory_postgres_job_and_a_lint_job():
    ci = yaml_blocks(ref("ci"))[0]
    assert {"lint", "test-python", "test-postgres", "migrations"} <= set(ci["jobs"])
    postgres = ci["jobs"]["test-postgres"]
    assert "machine" in postgres and postgres["environment"]["TEST_DB"] == "postgres"
    in_workflow = ci["workflows"]["build-and-test"]["jobs"]
    assert {"lint", "test-python", "test-postgres", "migrations"} <= set(in_workflow)
    assert "| `test-postgres` |" in ref("ci") and "obligatorio siempre" in ref("ci")


# --- Plan 2026-11-22, T-A --------------------------------------------------------------------------


def test_multiworker_cmd_runs_the_metrics_recipe():
    """A4: el CMD de varios workers invoca lo mismo que la receta de exposing-prometheus-metrics."""
    cmd = next(line for line in ref("docker").splitlines() if line.startswith("CMD") and "gunicorn" in line)
    recipe = block("exposing-prometheus-metrics", "gunicorn app.main:app")
    recipe_line = next(line for line in recipe.splitlines() if line.startswith("PROMETHEUS_MULTIPROC_DIR="))
    for flag in re.findall(r"(?:gunicorn \S+|-[kw] \S+)", recipe_line):
        assert flag in cmd, flag
    assert "-c gunicorn.conf.py" in cmd and "-b 0.0.0.0:8000" in cmd and "exec gunicorn" in cmd
    assert 'rm -rf \\"$PROMETHEUS_MULTIPROC_DIR\\" && mkdir -p' in cmd
    assert "COPY gunicorn.conf.py ./" in ref("docker") and "ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus" in ref("docker")


def test_build_order_has_the_frontend_step_and_the_published_mypy_config():
    """A5 · A6 · A7 · A12."""
    skill = text(f"backend/{SCAF}/SKILL.md")
    rows = {m.group(1): m.group(2) for m in re.finditer(r"^\| (\d+) \| ([^|]+) \|", skill, re.MULTILINE)}
    assert [rows[str(n)].strip() for n in range(7, 11)] == ["Frontend", "Docker", "Observabilidad", "CI"]
    assert "docker compose up -d db" in skill and "uv python pin 3.14" in skill
    mypy = toml_block(skill, "[tool.mypy]")["tool"]["mypy"]
    assert mypy["mypy_path"] == "." and mypy["explicit_package_bases"] is True


# --- DB-10 -----------------------------------------------------------------------------------------


def test_models_init_reexports_every_name_the_skills_import():
    init = block("modeling-postgres-with-sqlalchemy", "from app.models.base import Base, BigIntPK")
    exported = set(re.search(r"__all__ = \[(.*?)\]", init, re.DOTALL).group(1).replace('"', "").replace(" ", "").split(","))
    imported: set[str] = set()
    for body in all_text().values():
        for m in re.finditer(r"^from app\.models import ([^\n(]+)$", body, re.MULTILINE):
            imported |= {n.strip() for n in m.group(1).split("#")[0].split(",")}
    imported -= {"Session", "User", "Permission", "Role"}  # auth: lo agrega security.md, no el __init__ base
    assert imported <= exported, imported - exported
    assert "modelo nuevo = línea nueva" in text("database/modeling-postgres-with-sqlalchemy/SKILL.md")
