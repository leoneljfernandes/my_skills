# Docker: un contenedor por pieza

## Topología

```text
db (postgres, healthcheck) ──healthy──► migrate (alembic upgrade head, termina)
                                            │ completed_successfully
                                            ▼
                            frontend ──/api──► backend (FastAPI) ──OTLP──► tempo
                                                   ▲ /metrics
                                               prometheus     alloy ──logs──► loki
                                                         └─────► grafana ◄────┘
```

Por qué separados: cada pieza escala, se reinicia y se actualiza sola; la base sobrevive a reconstrucciones del backend; el frontend se sirve como estáticos sin Python.

## `Dockerfile` (backend)

```dockerfile
FROM python:3.14-slim

# uv desde la imagen oficial de Astral; fijar la versión estable vigente (nunca :latest)
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /code

# 1) Solo los archivos de dependencias → esta capa se cachea mientras no cambien
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 2) Código
COPY app/ ./app
COPY alembic/ ./alembic
COPY alembic.ini ./

ENV PATH="/code/.venv/bin:$PATH"

# Usuario sin privilegios
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- `PYTHONUNBUFFERED=1`: los logs salen al instante por stdout → Alloy/Loki los ven en tiempo real.
- `--frozen`: instala exactamente `uv.lock`; si el lock está desactualizado, el build falla.
- La misma imagen sirve para `backend`, `migrate` y el seed.

## `.dockerignore`

```text
.venv
__pycache__
*.pyc
.git
.gitignore
.env
tests
frontend
monitoring
*.db
```

## `frontend/Dockerfile` (SPA, p. ej. Vite + React/Vue)

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

`frontend/nginx.conf` — sirve la SPA y hace proxy de `/api` al backend (mismo origen → sin CORS en contenedores):

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        try_files $uri /index.html;   # rutas del router del cliente
    }
}
```

El frontend llama a rutas relativas (`/api/...`). En desarrollo con `npm run dev` fuera de Docker, el origen del dev server va en `CORS_ORIGINS` del backend.

## `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: postgres_db
    restart: always
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: ${DB_NAME}
    ports:
      - "${DB_PORT:-5432}:5432"       # expuesto para correr alembic/seed/tests desde el host
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 5s
      timeout: 5s
      retries: 5

  migrate:
    build: .
    container_name: migrate
    env_file: [.env]
    environment:
      DB_HOST: db                     # dentro de la red de compose
      DB_PORT: 5432
    command: ["alembic", "upgrade", "head"]
    depends_on:
      db:
        condition: service_healthy

  backend:
    build: .
    container_name: backend_app       # nombre fijo: las queries de Loki lo usan
    restart: always
    env_file: [.env]
    environment:
      DB_HOST: db
      DB_PORT: 5432
      OTEL_EXPORTER_OTLP_ENDPOINT: http://tempo:4317
      OTEL_SERVICE_NAME: my-api
    ports:
      - "8000:8000"
    volumes:
      - ./app:/code/app:z             # hot reload en desarrollo
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    depends_on:
      db:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
      tempo:
        condition: service_started

  frontend:
    build: ./frontend
    container_name: frontend_app
    restart: always
    ports:
      - "8080:80"
    depends_on:
      - backend

  # prometheus, grafana, loki, alloy, tempo → ver observability.md

volumes:
  pgdata:
  prometheus_data:
  grafana_data:
  loki_data:
  tempo_data:
```

Decisiones:

- **Orden garantizado**: `db` healthy → `migrate` termina OK → `backend`. Si la migración falla, el backend no arranca.
- **`env_file: .env`** + `environment` que sobreescribe `DB_HOST`/`DB_PORT` para la red interna. El mismo `.env` sirve desde el host (`DB_HOST=localhost`).
- **Volúmenes nombrados** para datos (sobreviven a `down`; `down -v` los borra). Bind mounts `:ro` para config.
- **`:z` en bind mounts**: requerido en hosts con SELinux (Fedora/RHEL); inocuo en el resto.
- `--reload` + bind mount de `./app` solo para desarrollo; en producción, la imagen tal cual (sin volumen de código, sin `--reload`).

## `.env` de ejemplo (versionar como `.env.example`, nunca `.env`)

```ini
DB_USER=app
DB_PASSWORD=cambiar
DB_NAME=app_db
DB_HOST=localhost
DB_PORT=5432
SECRET_KEY=generar-con-secrets.token_urlsafe-32
GRAFANA_USER=admin
GRAFANA_PASSWORD=admin
```

## Comandos

```bash
docker compose up --build                               # todo
docker compose up -d db                                 # solo la base (desarrollo local)
docker compose exec backend python -m app.seed          # cargar datos de prueba
docker compose run --rm migrate alembic downgrade -1    # operar migraciones con la imagen
docker compose down        # conserva datos   |   docker compose down -v   # borra datos
```
