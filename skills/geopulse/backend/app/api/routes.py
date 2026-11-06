"""Application entry point kept for uvicorn app.api.routes:app compatibility."""
from .main import app, create_app

__all__ = ["app", "create_app"]
