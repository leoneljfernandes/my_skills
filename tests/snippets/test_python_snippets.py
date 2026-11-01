"""Ejecuta el código Python publicado en las skills.

Uso (desde la raíz del repo):
    uv run --with pytest --with pydantic-settings --with fastapi --with 'sqlalchemy>=2.0.40,<2.1' --with pyyaml \
        pytest tests/snippets/test_python_snippets.py -v
"""

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

sys.path.insert(0, str(Path(__file__).parent))
from extract import all_text, block  # noqa: E402

SETTINGS_ENV = {
    "SECRET_KEY": "s" * 40,
    "DB_USER": "app",
    "DB_PASSWORD": "hunter2-pass",
    "DB_HOST": "localhost",
    "DB_NAME": "app_db",
    "ERRORS_BASE_URL": "https://errors.example.com",
}


def load_settings_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **env: str):
    code = block("configuring-fastapi-settings", "class Settings(BaseSettings)")
    mod_file = tmp_path / "skill_config.py"
    mod_file.write_text(code, encoding="utf-8")
    for key in ("APP_ENV", "LOG_LEVEL", *SETTINGS_ENV):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**SETTINGS_ENV, **env}.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("skill_config", mod_file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_repr_hides_password(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch)
    assert "hunter2-pass" not in repr(mod.Settings(_env_file=None))


SETTINGS_READ = re.compile(r"\b(?:get_)?settings(?:\(\))?\.([A-Z][A-Z0-9_]+)\b")


def test_settings_has_every_field_other_skills_read(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch)
    fields = set(mod.Settings.model_fields) | set(mod.Settings.model_computed_fields)
    read: dict[str, set[str]] = {}
    for path, text in all_text().items():  # todos los .md (incluye references/) y templates/*.py
        for name in SETTINGS_READ.findall(text):
            read.setdefault(name, set()).add(path)
    assert read, "el patrón no encontró ninguna lectura: el test no estaría probando nada"
    missing = {n: s for n, s in read.items() if n not in fields}
    assert not missing, f"campos que ninguna Settings define: {missing}"


def test_test_stage_ignores_local_env(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch, APP_ENV="test")
    (tmp_path / ".env").write_text("LOG_LEVEL=DEBUG\n")
    mod.ROOT_DIR = tmp_path
    mod.get_settings.cache_clear()
    assert mod.get_settings().LOG_LEVEL == "INFO"


def test_dev_stage_reads_root_env(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch, APP_ENV="dev")
    (tmp_path / ".env").write_text("LOG_LEVEL=DEBUG\n")
    mod.ROOT_DIR = tmp_path
    mod.get_settings.cache_clear()
    assert mod.get_settings().LOG_LEVEL == "DEBUG"


def test_empty_env_value_uses_default(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch, LOG_LEVEL="")
    assert mod.Settings(_env_file=None).LOG_LEVEL == "INFO"


def test_credentials_have_no_development_default(tmp_path, monkeypatch):
    mod = load_settings_module(tmp_path, monkeypatch)
    monkeypatch.delenv("DB_PASSWORD")
    with pytest.raises(Exception, match="DB_PASSWORD"):
        mod.Settings(_env_file=None)


def test_datetime_keeps_instant_on_sqlite():
    code = block("modeling-postgres-with-sqlalchemy", "class UtcDateTime")
    ns: dict = {}
    exec(code, ns)  # noqa: S102 - bloque propio de la skill

    class Base(DeclarativeBase):
        pass

    class Row(Base):
        __tablename__ = "row"
        id: Mapped[int] = mapped_column(primary_key=True)
        at: Mapped[dt.datetime] = mapped_column(ns["UtcDateTime"])

    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    local = dt.timezone(dt.timedelta(hours=-3))
    with Session(engine) as s:
        s.add(Row(id=1, at=dt.datetime(2026, 1, 1, 12, tzinfo=local)))
        s.commit()
        s.expire_all()
        got = s.get(Row, 1).at
    assert got == dt.datetime(2026, 1, 1, 15, tzinfo=dt.UTC)
    with Session(engine) as s, pytest.raises(Exception):  # noqa: B017 - sin zona se rechaza
        s.add(Row(id=2, at=dt.datetime(2026, 1, 1, 12)))
        s.flush()


# --- TS-01: todo bloque Python (y YAML/TOML/JSON) de las skills tiene que parsear ----------------

from extract import SKILLS, fenced_blocks  # noqa: E402


def _documents() -> list[Path]:
    return sorted(SKILLS.rglob("*.md"))


def _parse_errors() -> list[str]:
    import ast
    import json
    import tomllib

    import yaml

    errors: list[str] = []
    for path in _documents():
        rel = path.relative_to(SKILLS)
        for lang, code, line in fenced_blocks(path.read_text(encoding="utf-8")):
            try:
                if lang == "python":
                    ast.parse(code)
                elif lang == "toml":
                    tomllib.loads(code)
                elif lang == "json":
                    json.loads(code)
                elif lang in {"yaml", "yml"}:
                    list(yaml.safe_load_all(code))
            except (SyntaxError, ValueError, yaml.YAMLError) as exc:  # TOMLDecodeError y JSONDecodeError son ValueError
                errors.append(f"{rel}:{line} ({lang}): {str(exc).splitlines()[0]}")
    return errors


def test_every_python_block_parses():
    """Un bloque que no parsea no se puede copiar: ni `ast.parse` ni el parser de YAML/TOML/JSON."""
    errors = _parse_errors()
    assert not errors, "bloques que no parsean:\n" + "\n".join(errors)
