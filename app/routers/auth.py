"""Request-scoped user identity helpers for user-owned data routes."""

import os
from typing import Annotated

from fastapi import Header, HTTPException, Query


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
