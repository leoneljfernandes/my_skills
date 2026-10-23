# Auth y seguridad: OAuth2 + JWT + Argon2

## Flujo

1. `POST /api/users/` registra (contraseña validada por el schema, guardada como hash Argon2).
2. `POST /api/users/token` recibe **form-data** `username` (= email) + `password` (`OAuth2PasswordRequestForm`) y devuelve `{"access_token", "token_type": "bearer"}`.
3. Endpoints protegidos reciben `Authorization: Bearer <jwt>` vía `OAuth2PasswordBearer`. El botón *Authorize* de Swagger usa ese mismo flujo.

Por qué OAuth2 password flow: es el estándar que FastAPI integra con Swagger y lo que cualquier cliente OAuth2 entiende; el JWT es stateless (no requiere tabla de sesiones).

## `app/auth.py`

```python
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.config import settings
from app.database import DbSession
from app.models import User

# Argon2id para hashes nuevos; bcrypt solo para verificar hashes heredados
password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))
DUMMY_HASH = password_hash.hash("dummy-password-for-timing")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/token")

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain: str, hashed: str) -> tuple[bool, str | None]:
    """Devuelve (válida, hash_nuevo). hash_nuevo != None → re-guardar (migra bcrypt → argon2)."""
    return password_hash.verify_and_update(plain, hashed)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": subject, "iat": now, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=[settings.ALGORITHM],      # lista fija: evita ataques de "alg: none"
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError:
        return None
    return payload["sub"]


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: DbSession) -> User:
    sub = decode_access_token(token)
    if sub is None or not sub.isdigit():
        raise CREDENTIALS_ERROR
    user = await db.get(User, int(sub))
    if user is None or not user.is_active:
        raise CREDENTIALS_ERROR
    return user


def get_current_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not authorized to access this resource")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]


# Tokens de un solo uso (reset de contraseña, verificación de email)
def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)          # se envía al usuario

def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()  # se guarda en la base
```

## Endpoint de login

```python
INCORRECT_LOGIN = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "Incorrect email or password", headers={"WWW-Authenticate": "Bearer"}
)


@router.post("/token", response_model=Token)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession):
    user = await get_user_by_email(db, form.username)
    if user is None:
        verify_password(form.password, DUMMY_HASH)   # mismo tiempo de respuesta exista o no
        raise INCORRECT_LOGIN
    valid, new_hash = verify_password(form.password, user.password_hash)
    if not valid:
        raise INCORRECT_LOGIN
    if new_hash:                                      # hash heredado → re-hashear con Argon2
        user.password_hash = new_hash
        await db.commit()
    return Token(access_token=create_access_token(str(user.id)), token_type="bearer")

```

## Checklist de hardening

| Medida | Cómo | Por qué |
|---|---|---|
| Hash Argon2id | `pwdlib` con `Argon2Hasher` primero | ganador de la Password Hashing Competition, resistente a GPU; bcrypt queda solo para verificar legado |
| Mensaje de login genérico | `"Incorrect email or password"` para usuario inexistente y contraseña mala | no revela qué emails están registrados |
| Tiempo constante | verificar contra `DUMMY_HASH` cuando el usuario no existe | sin esto, la diferencia de tiempo delata emails registrados |
| `sub` = id del usuario (string) | `create_access_token(str(user.id))` | el email puede cambiar; el id no |
| Claims obligatorios | `options={"require": ["exp", "sub"]}` + `algorithms=[...]` fijo | rechaza tokens sin expiración y la confusión de algoritmos |
| Expiración corta | 30 min por defecto, configurable | limita el daño de un token filtrado |
| `SECRET_KEY` fuerte | `SecretStr`, 32+ bytes, solo desde `.env` / variables de CI | HS256 con clave corta es atacable por fuerza bruta |
| Política de contraseñas | schema `UserCreate`: mínimo 8, al menos un dígito y una mayúscula | se valida antes de llegar al dominio (422) |
| Respuestas filtradas | `response_model=UserResponse` sin `password_hash` | el ORM tiene el hash; la API nunca lo expone |
| Ownership | 404 si no existe, 403 si no es del usuario | un usuario no lee ni modifica recursos ajenos |
| Usuarios desactivados | `is_active` chequeado en `get_current_user` | permite bloquear cuentas sin borrarlas |
| Tokens de reset | `token_urlsafe(32)` al usuario, `sha256` en la base, `expires_at`, se borran al usarse | una filtración de la base no permite resetear cuentas |
| CORS | `CORS_ORIGINS` explícito desde `Settings` | `"*"` + credenciales expone la API a cualquier sitio |
| Secretos fuera de la imagen | `.env` en `.gitignore` y `.dockerignore` | la imagen se puede publicar sin filtrar credenciales |

Pendiente opcional según el proyecto: rate limiting en `/token` (p. ej. `slowapi`) y refresh tokens.

## Tests de auth obligatorios

Login OK (200 + `token_type == "bearer"`), contraseña mala (401 + header `WWW-Authenticate: Bearer`), usuario inexistente (401, mismo mensaje), endpoint protegido sin token (401), token inválido/expirado (401), recurso ajeno (403), endpoint admin con usuario común (403), registro con email duplicado (400), contraseña débil (422). Ver testing.md.
