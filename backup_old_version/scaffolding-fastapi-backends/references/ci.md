# CI/CD: CircleCI + Coveralls

## Pipeline

| Job | Qué prueba | Base de datos |
|---|---|---|
| `test-python` | suite E2E + cobertura → Coveralls, resultados JUnit | SQLite en memoria |
| `migrations` | `upgrade head` → `check` → `downgrade base` sobre Postgres real | contenedor secundario `cimg/postgres` |
| `deploy` (opcional) | despliegue con tracking de releases de CircleCI | — |

Por qué dos jobs de base: los tests usan `create_all` sobre SQLite (rápido); el job `migrations` garantiza que las migraciones de Alembic producen el mismo esquema que los modelos en Postgres.

## `.circleci/config.yml`

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
          command: pip install uv
      - restore_cache:
          keys:
            - uv-{{ checksum "uv.lock" }}
      - run:
          name: Install dependencies
          command: uv sync --frozen
      - save_cache:
          key: uv-{{ checksum "uv.lock" }}
          paths:
            - ~/.cache/uv

jobs:
  test-python:
    executor: py
    environment:
      SECRET_KEY: "clave_secreta_para_tests_circleci_32b+"   # no es secreto real; solo firma tokens de test
      PYTHONPATH: "."
    steps:
      - setup-uv
      - run:
          name: Run tests with coverage
          command: |
            mkdir -p test-results
            uv run coverage run --source=app -m pytest tests/ -v --junitxml=test-results/junit.xml
            uv run coverage lcov -o coverage.lcov
      - coveralls/upload:
          coverage_file: coverage.lcov
      - store_test_results:
          path: test-results

  migrations:
    docker:
      - image: cimg/python:3.14
      - image: cimg/postgres:16.4
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
    steps:
      - setup-uv
      - run:
          name: Wait for Postgres
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
          command: |
            uv run alembic upgrade head
            uv run alembic check
            uv run alembic downgrade base
            uv run alembic upgrade head

workflows:
  build-and-test:
    jobs:
      - test-python
      - migrations
```

Notas:

- `uv sync --frozen`: CI instala exactamente el lock; un `uv.lock` desactualizado rompe el build en vez de instalar otra cosa.
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
          requires: [test-python, migrations]
          filters:
            branches:
              only: main
```
