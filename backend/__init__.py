"""FastAPI backend package."""
from .envfile import load_env

load_env()   # .env at the repo root (before storage reads HYDROPIN_DB); shell variables win
