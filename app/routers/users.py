"""Allowed users management routes."""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db.firestore import get_firestore
from app.db.repositories.allowed_users import AllowedUsersRepository
from app.routers.auth import (
    get_request_user_email,
    is_admin_email,
    require_admin_user,
    resolve_admin_email,
)

router = APIRouter(prefix="/api/users", tags=["users"])


def get_users_repo() -> AllowedUsersRepository:
    return AllowedUsersRepository(get_firestore())


UsersDB = Annotated[AllowedUsersRepository, Depends(get_users_repo)]
UserEmail = Annotated[str, Depends(get_request_user_email)]
AdminUser = Annotated[str, Depends(require_admin_user)]


class AddUserRequest(BaseModel):
    email: str


@router.get("")
async def list_users(repo: UsersDB, _admin_user: AdminUser) -> list[dict]:
    return await repo.list_all()


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_user(body: AddUserRequest, repo: UsersDB, _admin_user: AdminUser) -> dict:
    if not body.email or "@" not in body.email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    await repo.add(body.email.lower().strip())
    return {"email": body.email.lower().strip()}


@router.get("/check")
async def check_user(email: str, repo: UsersDB) -> dict:
    """Check if an email is allowlisted and whether it is the admin account."""
    admin_email = await resolve_admin_email(repo)
    is_admin = bool(admin_email and email.lower() == admin_email.lower())
    if is_admin:
        return {"allowed": True, "is_admin": True, "admin_email": admin_email}
    allowed = await repo.is_allowed(email.lower())
    return {"allowed": allowed, "is_admin": False, "admin_email": admin_email}


@router.get("/me")
async def current_user(user_email: UserEmail, repo: UsersDB) -> dict:
    allowed = await repo.is_allowed(user_email.lower())
    if not allowed and user_email.lower() != (os.getenv("ALLOWED_EMAIL", "").lower().strip()):
        raise HTTPException(status_code=403, detail="User is not allowlisted")
    return {
        "email": user_email,
        "is_admin": await is_admin_email(user_email, repo),
        "admin_email": await resolve_admin_email(repo),
    }


@router.delete("/{email:path}")
async def remove_user(email: str, repo: UsersDB, _admin_user: AdminUser) -> dict:
    await repo.remove(email.lower())
    return {"success": True}
