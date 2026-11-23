# CI/CD: CircleCI + Coveralls

## Pipeline

| Job | Qué prueba | Base de datos |
|---|---|---|
| `lint` | `ruff check`, `mypy app tests` y `lint-imports` (las capas) | — |
| `test-python` | suite E2E + cobertura → Coveralls, resultados JUnit | SQLite en memoria |
| `test-postgres` | la misma suite con `TEST_DB=postgres`: `FOR UPDATE`, JSONB, tipos exactos y tests de concurrencia | PostgreSQL por testcontainers (executor `machine`, con Docker) |
| `migrations` | round-trip completo: `upgrade head` → `check` → `downgrade base` → `upgrade head` sobre Postgres real | contenedor secundario `cimg/postgres` |
| `deploy` (opcional) | despliegue con tracking de releases de CircleCI | — |

Por qué tres jobs de base: los tests rápidos usan `create_all` sobre SQLite. SQLite **sí** tiene índices parciales (`sqlite_where`) y CHECK; lo que no tiene es `FOR UPDATE`, JSONB, `NOT VALID`/`CONCURRENTLY` y la semántica exacta de los tipos de PostgreSQL. `test-postgres` ejerce eso, y es **obligatorio siempre**: los tests de concurrencia llevan `skipif` fuera de PostgreSQL y sin ese job ninguna corrida automática los ejecuta. El job `migrations` garantiza que las migraciones de Alembic producen el mismo esquema que los modelos en Postgres. La versión de PostgreSQL es la misma en compose, en `cimg/postgres` y en el `conftest.py` de `testing-fastapi-endpoints` (hoy 16.15).

## `.circleci/config.yml`

El ejemplo supone el layout monorepo (`backend/` y `frontend/` hermanos). Con el backend en la raíz, quitar los `working_directory`/`backend/` y dejar los comandos como están.

```yaml
version: 2.1

orbs:
  coveralls: coveralls/coveralls@2.2.5

executors:
  py:
    docker:
      - image: cimg/python:3.14        # = requires-python de pyproject.toml y FROM del Dockerfile

commands:
  setup-uv:
    steps:
      - checkout
      - run:
          name: Install uv
          # En un venv: sirve igual en cimg/python y en el machine (donde pip global está bloqueado)
          command: |
            python3 -m venv ~/uv-venv
            ~/uv-venv/bin/pip install "uv==0.12.*"
            echo 'export PATH=~/uv-venv/bin:$PATH' >> "$BASH_ENV"
      - restore_cache:
          keys:
            - uv-{{ checksum "backend/uv.lock" }}
      - run:
          name: Install dependencies
          working_directory: backend
          command: uv sync --locked
      - save_cache:
          key: uv-{{ checksum "backend/uv.lock" }}
          paths:
            - ~/.cache/uv

jobs:
  lint:
    executor: py
    steps:
      - setup-uv
      - run:
          name: Lint, types and layers
          working_directory: backend
          command: |
            uv run ruff check
            uv run mypy app tests
            uv run lint-imports

  test-python:
    executor: py
    environment:
      SECRET_KEY: "clave_secreta_para_tests_circleci_32b+"   # no es secreto real; solo firma tokens de test
      COOKIE_SECURE: "false"
    steps:
      - setup-uv
      - run:
          name: Run tests with coverage
          working_directory: backend
          command: |
            mkdir -p test-results
            uv run coverage run --source=app -m pytest tests/ -v --junitxml=test-results/junit.xml
            uv run coverage lcov -o coverage.lcov
      - coveralls/upload:
          coverage_file: backend/coverage.lcov
      - store_test_results:
          path: backend/test-results

  test-postgres:
    machine:
      image: ubuntu-2404:current        # Testcontainers necesita un Docker real, no el de un contenedor
    environment:
      TEST_DB: postgres
      SECRET_KEY: "clave_secreta_para_tests_circleci_32b+"
      COOKIE_SECURE: "false"
    steps:
      - setup-uv
      - run:
          name: Run tests against PostgreSQL
          working_directory: backend
          command: uv run pytest tests/ -v --junitxml=test-results/junit.xml
      - store_test_results:
          path: backend/test-results

  migrations:
    docker:
      - image: cimg/python:3.14
      - image: cimg/postgres:16.15
        environment:
          POSTGRES_USER: ci
          POSTGRES_PASSWORD: ci
          POSTGRES_DB: ci_db
    environment:
      DB_USER: ci
      DB_PASSWORD: ci
      DB_NAME: ci_db
      DB_HOST: localhost                 # los contenedores secundarios comparten red con el primario
      DB_PORT: "5432"
      SECRET_KEY: "clave_secreta_para_tests_circleci_32b+"
      ERRORS_BASE_URL: "https://errors.test.invalid"
      COOKIE_SECURE: "false"
    steps:
      - setup-uv
      - run:
          name: Wait for Postgres
          working_directory: backend
          command: |
            uv run python - \<<'EOF'
            import socket, time
            for _ in range(30):
                try:
                    socket.create_connection(("localhost", 5432), timeout=1).close()
                    break
                except OSError:
                    time.sleep(1)
            else:
                raise SystemExit("Postgres no respondió")
            EOF
      - run:
          name: Migrations round-trip
          working_directory: backend
          command: |
            uv run alembic upgrade head
            uv run alembic check
            uv run alembic downgrade base
            uv run alembic upgrade head

workflows:
  build-and-test:
    jobs:
      - lint
      - test-python
      - test-postgres
      - migrations
```

Notas:

- `uv sync --locked`: CI instala exactamente el lock y **falla** si no coincide con `pyproject.toml`. Con `--frozen` un lock viejo se acepta en silencio y el build pasa con una dependencia sin instalar.
- `uv==0.12.*`: la serie de uv fijada, la misma que el `Dockerfile` (`uv:0.12`).
- Sin `PYTHONPATH`: `pythonpath = ["."]` en el `pyproject.toml` hace importable `app` igual en local y en CI.
- El job `test-postgres` y el `machine` no se pudieron ejecutar en CircleCI al escribir esta referencia: el YAML solo está validado como sintaxis.
- `--source=app`: la cobertura mide solo el código de la app, no tests ni dependencias.
- `coverage lcov`: formato que consume el orb de Coveralls.
- `store_test_results`: CircleCI muestra cada test, tiempos y flakies en la UI.
- `\<<` dentro de `command:` escapa el heredoc para el parser de CircleCI.

## Coveralls

1. Entrar a coveralls.io con GitHub y activar el repo.
2. Copiar el *repo token* y cargarlo en CircleCI → *Project Settings → Environment Variables* como `COVERALLS_REPO_TOKEN` (el orb lo lee de ahí; nunca en el YAML).
3. Badges en el README (CircleCI → *Project Settings → Status Badges*; Coveralls → página del repo):

```markdown
[![CircleCI](https://dl.circleci.com/status-badge/img/circleci/<org>/<project>/tree/main.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/circleci/<org>/<project>/tree/main)
[![Coverage Status](https://coveralls.io/repos/github/<usuario>/<repo>/badge.svg?branch=main)](https://coveralls.io/github/<usuario>/<repo>?branch=main)
```

`.gitignore` incluye los artefactos: `.coverage`, `coverage.lcov`, `junit.xml`, `test-results/`, `*.db`, `.pytest_cache/`.

## Deploy (plantilla)

Job con tracking de releases de CircleCI; se agrega al workflow cuando exista destino, condicionado a `main` y a los jobs de test:

```yaml
  deploy:
    docker:
      - image: cimg/base:stable
    steps:
      - run:
          name: Plan deployment
          command: |-
            circleci run release plan deploy \
              --environment-name="default" \
              --component-name="deploy" \
              --target-version="1.0.${CIRCLE_BUILD_NUM}-${CIRCLE_SHA1:0:7}"
      - run:
          name: Deploy
          command: ./deploy.sh
      - run:
          name: Mark running
          command: circleci run release update deploy --status=RUNNING
      - run:
          name: Mark success
          command: circleci run release update deploy --status=SUCCESS
          when: on_success
      - run:
          name: Mark failed
          command: circleci run release update deploy --status=FAILED
          when: on_fail

# en workflows.build-and-test.jobs:
      - deploy:
          requires: [lint, test-python, test-postgres, migrations]
          filters:
            branches:
              only: main
```
