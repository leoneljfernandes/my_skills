# Auth y seguridad: OAuth2 + JWT + Argon2

## Qué sesión elegir

| El cliente es | Usar | Por qué |
|---|---|---|
| Una SPA o app con personas que inician sesión | **Access token JWT corto (15 min) + refresh token opaco rotado en cookie `httpOnly`** | un XSS no puede leer la cookie; un token filtrado vence solo; se puede cerrar una sesión robada |
| Otra máquina (cron, otro servicio) | Solo el JWT, sin refresh ni tabla de sesiones | no hay navegador que guarde una cookie; el cliente pide un token nuevo con sus credenciales |

La skill `building-axios-clients` exige el endpoint `/auth/refresh` con cookie: si el cliente es una SPA, este documento lo implementa. Para una API solo entre máquinas, saltear las secciones "Sesiones" y "Refresh".

## Flujo (SPA)

1. `POST /api/v1/auth/token` recibe **form-data** `username` (= email) + `password` (`OAuth2PasswordRequestForm`). Devuelve `{"access_token", "token_type": "bearer"}` y deja el refresh en una cookie `httpOnly`.
2. Los endpoints protegidos reciben `Authorization: Bearer <jwt>` vía `OAuth2PasswordBearer(auto_error=False)`. El botón *Authorize* de Swagger usa ese mismo flujo.
3. Al vencer el access, el cliente llama `POST /api/v1/auth/refresh`: la cookie viaja sola, el servidor la **rota** (invalida la usada y emite otra) y devuelve un access nuevo.
4. `POST /api/v1/auth/logout` revoca la sesión y borra la cookie. `GET /api/v1/auth/me` devuelve el usuario actual y sus permisos (`{ id: number, email: string, role: string, permissions: string[] }`).

## `app/security.py` (primitivas, sin base de datos)

```python
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.config import Settings

ALGORITHM = "HS256"  # constante: no es configuración, y la lista de abajo la fija

password_hash = PasswordHash((Argon2Hasher(),))
# Se verifica contra este hash cuando el usuario no existe: mismo tiempo de respuesta,
# así la diferencia de tiempo no delata qué emails están registrados.
DUMMY_HASH = password_hash.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain: str, hashed: str) -> tuple[bool, str | None]:
    """(válida, hash_nuevo). hash_nuevo != None → re-guardar con los parámetros actuales."""
    return password_hash.verify_and_update(plain, hashed)


def create_access_token(user_id: int, *, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),  # el id, no el email: el email puede cambiar
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str, *, settings: Settings) -> int | None:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=[ALGORITHM],  # lista fija: rechaza "alg: none" y la confusión de algoritmos
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError:
        return None
    sub = payload["sub"]
    return int(sub) if isinstance(sub, str) and sub.isdigit() else None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)  # opaco: viaja en la cookie


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()  # en la base solo se guarda el hash
```

`pwdlib[argon2]` alcanza en un proyecto nuevo. Agregar `BcryptHasher()` (`pwdlib[argon2,bcrypt]`) **solo si hay hashes bcrypt heredados que migrar**: `verify_and_update` los re-hashea con Argon2 en el primer login.

## Sesiones (tabla)

```python
class Session(Base):
    """Refresh token emitido. Se guarda solo su hash; se rota en cada uso."""

    __tablename__ = "sessions"

    id: Mapped[BigIntPK]
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    replaced_at: Mapped[datetime | None] = mapped_column(UtcDateTime())  # cuándo se rotó
```

(`UtcDateTime` es el tipo de `modeling-postgres-with-sqlalchemy`.)

## Repositorios de auth

`User.role` es una relación `lazy="raise"` (`modeling-postgres-with-sqlalchemy`): quien necesita los permisos carga el rol en la misma query, con `get_with_role`.

```python
class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_with_role(self, user_id: int) -> User | None:
        # lazy="raise": sin esto, user.role.permissions revienta con InvalidRequestError (500).
        stmt = select(User).where(User.id == user_id).options(joinedload(User.role))
        return (await self._session.scalars(stmt)).one_or_none()


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, row: Session) -> None:
        self._session.add(row)

    async def get_by_hash_for_update(self, token_hash: str) -> Session | None:
        # FOR UPDATE: dos refresh simultáneos con el mismo token se serializan; el segundo ya lo ve rotado.
        stmt = select(Session).where(Session.token_hash == token_hash).with_for_update()
        return (await self._session.scalars(stmt)).one_or_none()

    async def revoke_all(self, user_id: int, now: datetime) -> None:
        stmt = update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
        await self._session.execute(stmt.values(revoked_at=now))
```

## `AuthService`

Dueño de su transacción (ver `layering-fastapi-apps`). Los errores son de dominio: `InvalidCredentialsError`, `NotAuthenticatedError` y `SessionRotatedError` (`handling-fastapi-errors`), nunca `HTTPException`.

```python
# Reusar un token recién rotado es normal con dos pestañas que renuevan a la vez o una respuesta
# de refresh perdida: dentro de esta ventana no se lo trata como robo, y se responde 401
# `session_rotated` para que el cliente reintente con la cookie nueva (ver "Contrato con el cliente").
REUSE_GRACE = timedelta(seconds=30)


class AuthService:
    def __init__(self, session: AsyncSession, users: UserRepository,
                 sessions: SessionRepository, settings: Settings) -> None:
        self._session, self._users, self._sessions, self._settings = session, users, sessions, settings

    async def login(self, email: str, password: str) -> tuple[str, str]:
        user = await self._users.get_by_email(email)
        if user is None:
            # Argon2 es CPU y memoria intensivo: en un hilo aparte para no frenar el event loop.
            await asyncio.to_thread(verify_password, password, DUMMY_HASH)
            raise InvalidCredentialsError("Incorrect email or password")
        valid, new_hash = await asyncio.to_thread(verify_password, password, user.password_hash)
        if not valid or not user.is_active:  # mismo mensaje: no revela cuentas desactivadas
            raise InvalidCredentialsError("Incorrect email or password")
        if new_hash:  # hash heredado o con parámetros viejos → re-hashear
            user.password_hash = new_hash
        tokens = self._issue(user.id)
        await self._session.commit()
        return tokens

    async def refresh(self, refresh_token: str) -> tuple[str, str]:
        now = datetime.now(UTC)
        stored = await self._sessions.get_by_hash_for_update(hash_token(refresh_token))
        if stored is None:
            raise NotAuthenticatedError("Invalid session")
        if stored.revoked_at is not None:
            if stored.replaced_at is None:  # cerrada con logout
                raise NotAuthenticatedError("Invalid session")
            if now - stored.replaced_at <= REUSE_GRACE:
                # Rotado hace segundos: la sesión sigue viva y la cookie nueva ya existe.
                raise SessionRotatedError("Session was just rotated; retry with the new cookie")
            # Un token rotado hace rato volvió a usarse: puede estar robado.
            await self._sessions.revoke_all(stored.user_id, now)
            await self._session.commit()
            raise NotAuthenticatedError("Invalid session")
        user = await self._users.get(stored.user_id)
        if stored.expires_at <= now or user is None or not user.is_active:
            raise NotAuthenticatedError("Invalid session")
        stored.revoked_at = stored.replaced_at = now
        tokens = self._issue(user.id)
        await self._session.commit()
        return tokens

    async def user_from_token(self, access_token: str | None) -> User:
        user_id = decode_access_token(access_token, settings=self._settings) if access_token else None
        user = await self._users.get_with_role(user_id) if user_id is not None else None  # el rol viene cargado
        if user is None or not user.is_active:
            raise NotAuthenticatedError("Invalid or expired token")
        return user

    async def logout(self, refresh_token: str) -> None:
        stored = await self._sessions.get_by_hash_for_update(hash_token(refresh_token))
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = datetime.now(UTC)
            await self._session.commit()

    def _issue(self, user_id: int) -> tuple[str, str]:
        refresh = new_refresh_token()
        expires = datetime.now(UTC) + timedelta(days=self._settings.REFRESH_TOKEN_EXPIRE_DAYS)
        self._sessions.add(Session(user_id=user_id, token_hash=hash_token(refresh), expires_at=expires))
        return create_access_token(user_id, settings=self._settings), refresh
```

## Router y dependencias

```python
REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"  # la cookie viaja solo a /auth: el resto de la API nunca la recibe


def _store_refresh(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE, token, path=REFRESH_COOKIE_PATH,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,  # JS no la lee: un XSS no se la lleva
        secure=settings.COOKIE_SECURE,
        samesite="strict",  # no viaja en requests iniciadas desde otros sitios (CSRF)
    )


@router.post("/token")
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], auth: AuthServiceDep,
                settings: SettingsDep, response: Response) -> TokenRead:
    access, refresh = await auth.login(form.username, form.password)
    _store_refresh(response, refresh, settings)
    return TokenRead(access_token=access)


@router.post("/refresh")
async def refresh(request: Request, auth: AuthServiceDep, settings: SettingsDep, response: Response) -> TokenRead:
    token = request.cookies.get(REFRESH_COOKIE)
    if token is None:
        raise NotAuthenticatedError("Missing refresh cookie")
    access, new_refresh = await auth.refresh(token)  # 401 session_rotated dentro de REUSE_GRACE
    _store_refresh(response, new_refresh, settings)
    return TokenRead(access_token=access)


class MeRead(BaseModel):
    id: int
    email: str
    role: str
    permissions: list[str]


@router.get("/me")
async def me(user: CurrentUser) -> MeRead:  # user_from_token ya cargó el rol
    return MeRead(id=user.id, email=user.email, role=user.role.name, permissions=list(user.role.permissions))
```

**Contrato con el cliente** (lo implementa `building-axios-clients`): ante un 401 de `/auth/refresh` con `code == "session_rotated"` el cliente espera unos 200 ms y reintenta **una sola vez**: la otra pestaña ya dejó la cookie nueva y el navegador la envía. Cualquier otro 401 de `/auth/refresh` termina la sesión, y también un segundo `session_rotated` (la respuesta del refresh se perdió y la cookie nueva nunca llegó).

```python
# api/deps.py
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


async def get_current_user(token: Annotated[str | None, Depends(oauth2_scheme)],
                           auth: AuthServiceDep) -> User:
    return await auth.user_from_token(token)  # el 401 lo lanza el dominio, con su code


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: Permission) -> Callable[[User], Awaitable[User]]:
    async def dependency(user: CurrentUser) -> User:
        if permission not in user.role.permissions:  # el rol viene de get_with_role (lazy="raise")
            raise PermissionDeniedError(f"Missing permission {permission.value}")
        return user
    return dependency
```

`SameSite=strict` exige **mismo sitio**: el navegador solo envía la cookie si la SPA y la API comparten dominio. En desarrollo, proxy del dev server (`/api` → backend); en producción, un proxy inverso (nginx) o rewrites. Ver `docker.md`.

Permisos: un `Role` con lista de permisos y `require_permission(...)` por endpoint. Un booleano `is_admin` solo sirve si hay **un único** rol privilegiado; apenas aparece un segundo rol con permisos parciales, se queda corto.

## Primer usuario (bootstrap)

El registro abierto es una opción explícita, no el default: una instalación privada no debe aceptar altas anónimas. El primer usuario se crea con un comando que lee `OWNER_EMAIL` y `OWNER_PASSWORD` de `get_settings()` (son campos de `Settings`; `OWNER_PASSWORD` es `SecretStr`; sin ellos, `SystemExit` con mensaje) y **solo crea si todavía no hay usuarios**:

```bash
docker compose run --rm migrate python -m app.bootstrap
```

El comando es un entrypoint de línea de comandos: usa `print` para informar y `SystemExit` con mensaje para los errores de configuración. Los demás usuarios los da de alta quien tiene el permiso para hacerlo.

## Checklist de hardening

| Medida | Cómo | Por qué |
|---|---|---|
| Hash Argon2id | `pwdlib` con `Argon2Hasher` | resistente a GPU; bcrypt solo si hay hashes heredados |
| Argon2 fuera del event loop | `asyncio.to_thread(verify_password, ...)` | verifica en ~100 ms de CPU: en `async def` directo frena todas las requests |
| Mensaje de login genérico | `"Incorrect email or password"` para inexistente, contraseña mala **y cuenta desactivada** | no revela qué emails existen ni cuáles están bloqueados |
| Tiempo constante | verificar contra `DUMMY_HASH` cuando el usuario no existe | sin esto, la diferencia de tiempo delata emails registrados |
| Usuario desactivado | `is_active` en login, refresh y `user_from_token` | bloquear una cuenta corta también las sesiones abiertas |
| `sub` = id del usuario (string) | `create_access_token(user.id)` | el email puede cambiar; el id no |
| Claims obligatorios | `options={"require": ["exp", "sub"]}` + `algorithms=[ALGORITHM]` | rechaza tokens sin expiración y la confusión de algoritmos |
| Access corto | 15 min por defecto (`ACCESS_TOKEN_EXPIRE_MINUTES`) | limita el daño de un token filtrado |
| Refresh rotado | token opaco, solo su `sha256` en la base, reemplazado en cada uso | una filtración de la base no entrega sesiones |
| Detección de reuso | revocar todas las sesiones si un token rotado vuelve después de `REUSE_GRACE`; dentro de la gracia, 401 `session_rotated` sin revocar | delata un token robado sin expulsar a la segunda pestaña |
| Refresh serializado | `get_by_hash_for_update` (`FOR UPDATE`) | dos refresh simultáneos no rotan el mismo token dos veces |
| Cookie | `httponly`, `secure` (salvo desarrollo local), `samesite="strict"`, `path` restringido | un XSS no la lee; no viaja entre sitios |
| `SECRET_KEY` fuerte | `SecretStr`, 32+ bytes, solo desde `.env` / variables de CI | HS256 con clave corta es atacable por fuerza bruta |
| Política de contraseñas | schema `UserCreate`: mínimo 8, al menos un dígito y una mayúscula | se valida antes de llegar al dominio (422) |
| Respuestas filtradas | `response_model` sin `password_hash` | el ORM tiene el hash; la API nunca lo expone |
| Ownership | 404 si no existe o el usuario no puede verlo; 403 solo si lo ve pero no puede hacer esa acción | un usuario no lee ni modifica recursos ajenos, y un 403 no confirma que el id existe |
| Límite de intentos de login | `limit_req` en nginx (ver `docker.md`) o `slowapi` | frena la adivinación de contraseñas |
| CORS | `CORS_ORIGINS` explícito desde `Settings` | `"*"` + credenciales expone la API a cualquier sitio |
| Secretos fuera de la imagen | `.env` en `.gitignore` y `.dockerignore` | la imagen se puede publicar sin filtrar credenciales |

Tokens de un solo uso (reset de contraseña, verificación de email): `secrets.token_urlsafe(32)` al usuario, `sha256` en la base, `expires_at`, se borran al usarse.

## Tests de auth obligatorios

Ver la skill `testing-fastapi-endpoints`.

- Login OK (200 + `token_type == "bearer"` + cookie `refresh_token` `httponly`), contraseña mala (401 + `WWW-Authenticate: Bearer` + `code == "invalid_credentials"`), usuario inexistente (401, mismo mensaje), **usuario desactivado (401, mismo mensaje)**.
- Endpoint protegido sin token (401 `not_authenticated`), token inválido o expirado (401), recurso ajeno (404), acción sin permiso sobre un recurso visible (403) y endpoint con permiso faltante (403). El permiso concedido da 200 y el faltante 403, **con la sesión limpia** (`expire_all()` antes de la request): así se detecta un rol sin cargar.
- **El refresh rota la cookie**: el token viejo deja de servir y el nuevo sí.
- **Reusar un token rotado después de `REUSE_GRACE` revoca todas las sesiones** del usuario; reusarlo **dentro** de la gracia no las revoca y responde 401 con `code == "session_rotated"`.
- Con PostgreSQL (`TEST_DB=postgres`): dos `/auth/refresh` simultáneos con la misma cookie dan un 200 y un 401 `session_rotated`, nunca dos 200.
- **Un usuario desactivado no puede renovar** (401 en `/auth/refresh`).
- Email duplicado (409 con `code` estable), contraseña débil (422).
- `test_password_offload`: `verify_password` se ejecuta en un hilo aparte, no en el event loop (parchar `asyncio.to_thread` y comprobar que se llama).
