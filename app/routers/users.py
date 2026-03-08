"""Allowed users management routes."""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db.firestore import get_firestore
from app.db.repositories.allowed_users import AllowedUsersRepository

router = APIRouter(prefix="/api/users", tags=["users"])


def get_users_repo() -> AllowedUsersRepository:
    return AllowedUsersRepository(get_firestore())


UsersDB = Annotated[AllowedUsersRepository, Depends(get_users_repo)]


class AddUserRequest(BaseModel):
    email: str


@router.get("")
async def list_users(repo: UsersDB) -> list[dict]:
    return await repo.list_all()


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_user(body: AddUserRequest, repo: UsersDB) -> dict:
    if not body.email or "@" not in body.email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    await repo.add(body.email.lower().strip())
    return {"email": body.email.lower().strip()}


@router.get("/check")
async def check_user(email: str, repo: UsersDB) -> dict:
    """Check if an email is in the allowlist. Also passes ALLOWED_EMAIL env var."""
    admin_email = os.getenv("ALLOWED_EMAIL", "")
    if admin_email and email.lower() == admin_email.lower():
        return {"allowed": True}
    allowed = await repo.is_allowed(email.lower())
    return {"allowed": allowed}


@router.delete("/{email:path}")
async def remove_user(email: str, repo: UsersDB) -> dict:
    await repo.remove(email.lower())
    return {"success": True}
