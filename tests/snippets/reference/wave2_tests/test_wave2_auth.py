"""Ola 2: auth de security.md armado en el proyecto de referencia (BE-08, BE-09, D6)."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import get_settings
from app.crud.auth import SessionRepository, UserRepository
from app.errors import SessionRotatedError
from app.main import app
from app.models import Permission, Role, Session, User
from app.security import hash_password
from app.services.auth import AuthService

PASSWORD = "Passw0rd!x"


async def make_user(session: AsyncSession, email: str, permissions: list[str]) -> User:
    role = Role(name=f"role-{email}", permissions=permissions)
    session.add(role)
    await session.flush()
    user = User(email=email, password_hash=hash_password(PASSWORD), role_id=role.id)
    session.add(user)
    await session.flush()
    return user


async def login(client: AsyncClient, email: str) -> tuple[str, str]:
    response = await client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"], response.cookies["refresh_token"]


async def refresh_with(cookie: str) -> Response:
    """Un refresh con una cookie explícita (la que tenía la otra pestaña), sin jar compartido."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post("/api/v1/auth/refresh", headers={"cookie": f"refresh_token={cookie}"})


async def test_permission_granted_is_200_and_missing_is_403(client: AsyncClient, db_session: AsyncSession) -> None:
    await make_user(db_session, "boss@example.com", [Permission.ADMIN_REPORT.value])
    await make_user(db_session, "clerk@example.com", [])
    boss, _ = await login(client, "boss@example.com")
    clerk, _ = await login(client, "clerk@example.com")
    db_session.expunge_all()  # sesión limpia: sin el rol ya cargado en el identity map (BE-08)

    allowed = await client.get("/api/v1/admin/report", headers={"Authorization": f"Bearer {boss}"})
    db_session.expunge_all()
    denied = await client.get("/api/v1/admin/report", headers={"Authorization": f"Bearer {clerk}"})

    assert allowed.status_code == 200, allowed.text
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"


async def test_me_has_the_schema_the_frontend_expects(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await make_user(db_session, "ana@example.com", ["orders.read", "orders.write"])
    access, _ = await login(client, "ana@example.com")
    db_session.expunge_all()

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"id", "email", "role", "permissions"}
    assert body == {"id": user.id, "email": "ana@example.com", "role": "role-ana@example.com",
                    "permissions": ["orders.read", "orders.write"]}


async def test_reuse_inside_the_grace_window_is_session_rotated_and_keeps_the_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await make_user(db_session, "tabs@example.com", [])
    _, old_cookie = await login(client, "tabs@example.com")

    tab_a = await refresh_with(old_cookie)  # la pestaña A rota
    assert tab_a.status_code == 200
    new_cookie = tab_a.cookies["refresh_token"]

    tab_b = await refresh_with(old_cookie)  # la pestaña B llega con la cookie vieja
    assert tab_b.status_code == 401
    assert tab_b.json()["code"] == "session_rotated"
    assert tab_b.headers["www-authenticate"] == "Bearer"

    retry = await refresh_with(new_cookie)  # reintento con la cookie nueva: la sesión sigue viva
    assert retry.status_code == 200


async def test_reuse_after_the_grace_window_revokes_every_session(client: AsyncClient, db_session: AsyncSession) -> None:
    await make_user(db_session, "thief@example.com", [])
    _, old_cookie = await login(client, "thief@example.com")
    assert (await refresh_with(old_cookie)).status_code == 200
    await db_session.execute(update(Session).values(replaced_at=datetime.now(UTC) - timedelta(minutes=5)))

    reuse = await refresh_with(old_cookie)

    assert reuse.status_code == 401
    assert reuse.json()["code"] == "not_authenticated"  # no "session_rotated": esto sí puede ser robo
    assert (await db_session.scalars(select(Session).where(Session.revoked_at.is_(None)))).first() is None


async def test_refresh_without_cookie_is_not_authenticated(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


@pytest.mark.skipif(os.getenv("TEST_DB") != "postgres", reason="requiere PostgreSQL (FOR UPDATE)")
async def test_two_simultaneous_refreshes_rotate_only_once(engine: AsyncEngine) -> None:
    """D6: sin FOR UPDATE ambos leen el token sin rotar y los dos devuelven tokens nuevos."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = get_settings()

    def service(s: AsyncSession) -> AuthService:
        return AuthService(s, UserRepository(s), SessionRepository(s), settings)

    async with factory() as s:
        await make_user(s, "race@example.com", [])
        await s.commit()
        _, token = await service(s).login("race@example.com", PASSWORD)

    async def attempt() -> str:
        async with factory() as s:
            try:
                await service(s).refresh(token)
            except SessionRotatedError:
                return "rotated"
            return "ok"

    try:
        assert sorted(await asyncio.gather(attempt(), attempt())) == ["ok", "rotated"]
    finally:
        async with factory() as s:
            await s.execute(delete(Session))
            await s.execute(delete(User))
            await s.execute(delete(Role))
            await s.commit()
