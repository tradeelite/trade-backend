"""Async Firestore client singleton."""

from google.cloud import firestore
from google.cloud.firestore import AsyncClient

from app.core.config import settings

_client: AsyncClient | None = None


def get_firestore() -> AsyncClient:
    """Return a shared Firestore async client."""
    global _client
    if _client is None:
        _client = firestore.AsyncClient(project=settings.google_cloud_project)
    return _client
