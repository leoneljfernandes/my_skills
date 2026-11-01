# Docker: un contenedor por pieza

## Layout

Monorepo con el backend y el frontend como carpetas hermanas. Cada una es su propio contexto de build:

```text
repo/
├── backend/        # Dockerfile, pyproject.toml, uv.lock, app/, alembic/, alembic.ini
├── frontend/       # Dockerfile, nginx.conf, package.json, src/
├── docker-compose.yml
└── .env.example    # el .env real vive en la raíz y lo comparten compose y la app
```

Si el backend vive en la raíz del repo (sin frontend), los ejemplos de abajo valen cambiando `./backend` por `.`.

## Topología

Las piezas de observabilidad (prometheus, alloy, loki, tempo, grafana) se suman **solo si el stack se despliega en contenedores propios**. En una plataforma que trae su propio monitoreo, el stack base es `db → migrate → backend → frontend`.

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

# uv desde la imagen oficial de Astral; fijar la versión estable vigente al construir (nunca :latest)
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

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

## `backend/.dockerignore`

```text
.venv
__pycache__
*.pyc
.git
.env
tests
*.db
```

El contexto es `backend/`, así que `frontend/` y `monitoring/` no entran por construcción. Agregar también un `.dockerignore` en la raíz con `.env*` si algún build usa la raíz como contexto.

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

`frontend/nginx.conf` — sirve la SPA y hace proxy de `/api` al backend (mismo origen → sin CORS en contenedores, y la cookie `SameSite=strict` del refresh viaja):

```nginx
# Límite de intentos de login por IP: frena la adivinación de contraseñas y que una ráfaga
# de logins (Argon2 es caro) sature el backend. 10 por minuto, con ráfaga de 5.
limit_req_zone $binary_remote_addr zone=login:10m rate=10r/m;

server {
    listen 80;
    root /usr/share/nginx/html;

    # DNS interno de Docker. Con el destino en una variable, nginx vuelve a resolver "backend"
    # (cada 10 s) en vez de fijar su IP al arrancar: recrear el backend no deja al proxy apuntando
    # a una IP vieja, y nginx arranca aunque el backend todavía no exista.
    resolver 127.0.0.11 valid=10s ipv6=off;
    set $backend http://backend:8000;

    location = /api/v1/auth/token {
        limit_req zone=login burst=5 nodelay;
        limit_req_status 429;
        proxy_pass $backend;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/ {
        client_max_body_size 3m;   # tope de los uploads de la API (más el sobre multipart)
        # Sin parte de URI en la variable, la ruta original se pasa tal cual (/api/v1/...).
        proxy_pass $backend;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Archivos con hash en el nombre: se cachean para siempre.
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Rutas del router del cliente: cualquier otra ruta devuelve index.html.
    location / {
        add_header Cache-Control "no-cache";
        try_files $uri /index.html;
    }
}
```

El frontend llama a rutas relativas (`/api/...`). En desarrollo con `npm run dev` fuera de Docker, el dev server hace proxy de `/api` al backend (`server.proxy` en `vite.config.ts`), para que el origen sea el mismo.

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
    build: ./backend
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
    build: ./backend
    container_name: backend_app       # nombre fijo: las queries de Loki lo usan
    restart: always
    env_file: [.env]
    environment:
      DB_HOST: db
      DB_PORT: 5432
      # Con observabilidad en contenedores propios, sumar:
      # OTEL_EXPORTER_OTLP_ENDPOINT: http://tempo:4317
    ports:
      - "8000:8000"
    volumes:
      - ./backend/app:/code/app:z     # hot reload en desarrollo
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    depends_on:
      db:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully

  frontend:
    build: ./frontend
    container_name: frontend_app
    restart: always
    ports:
      - "8080:80"
    depends_on:
      - backend

  # Solo con contenedores propios: prometheus, grafana, loki, alloy, tempo, alertmanager →
  # skill defining-grafana-slos (references/stack.md). Con volúmenes prometheus_data, grafana_data,
  # loki_data y tempo_data. Ver observabilidad en Vercel en frontend/vercel-index.md.

volumes:
  pgdata:
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
ERRORS_BASE_URL=https://errors.example.com
COOKIE_SECURE=false   # solo desarrollo local (http)
# GRAFANA_USER / GRAFANA_PASSWORD solo si se levanta el stack de observabilidad
```

## Comandos

```bash
docker compose up --build                               # todo
docker compose up -d db                                 # solo la base (desarrollo local)
docker compose exec backend python -m app.seed          # cargar datos de prueba
docker compose run --rm migrate alembic downgrade -1    # operar migraciones con la imagen
docker compose down        # conserva datos   |   docker compose down -v   # borra datos
```
