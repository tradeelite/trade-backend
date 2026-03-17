"""Request-scoped user identity helpers for user-owned data routes."""

import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query

from app.db.firestore import get_firestore
from app.db.repositories.allowed_users import AllowedUsersRepository


def get_request_user_email(
    x_user_email: Annotated[str | None, Header(alias="x-user-email")] = None,
    user_email_query: Annotated[str | None, Query(alias="userEmail")] = None,
) -> str:
    email = (x_user_email or user_email_query or "").strip().lower()
    if email:
        return email

    # Backward compatibility: if app is configured with a single admin account
    # and caller did not send user context, treat request as admin-owned.
    admin_email = os.getenv("ALLOWED_EMAIL", "").strip().lower()
    if admin_email:
        return admin_email

    raise HTTPException(status_code=401, detail="Missing user context")


def get_users_repo() -> AllowedUsersRepository:
    return AllowedUsersRepository(get_firestore())


async def resolve_admin_email(repo: AllowedUsersRepository) -> str:
    admin_email = os.getenv("ALLOWED_EMAIL", "").strip().lower()
    if admin_email:
        return admin_email

    # Fallback for deployments where ALLOWED_EMAIL was not set:
    # pick earliest allowlisted user as admin anchor.
    users = await repo.list_all()
    if not users:
        return ""
    users_sorted = sorted(users, key=lambda u: u.get("added_at", ""))
    return (users_sorted[0].get("email") or "").strip().lower()


async def is_admin_email(email: str, repo: AllowedUsersRepository) -> bool:
    admin_email = await resolve_admin_email(repo)
    return bool(admin_email and email.lower() == admin_email)


async def require_admin_user(
    user_email: Annotated[str, Depends(get_request_user_email)],
    repo: Annotated[AllowedUsersRepository, Depends(get_users_repo)],
) -> str:
    if not await is_admin_email(user_email, repo):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_email
