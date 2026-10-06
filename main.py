"""Vercel entrypoint. The FastAPI preset looks for an ASGI `app` in main.py."""
from app.main import app  # noqa: F401
