#!/usr/bin/env bash
# Arma el proyecto desde las SKILL.md y corre pytest + mypy --strict.
# TEST_DB=postgres (con Docker) corre la misma suite contra PostgreSQL 16 por testcontainers.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
uv run python build_ref.py
uv run pytest -q "$@"
uv run mypy project/app project/tests
