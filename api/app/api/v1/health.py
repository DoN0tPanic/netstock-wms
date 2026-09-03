from typing import Any

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.deps import CurrentUser

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(user: CurrentUser) -> dict[str, Any]:
    checks: dict[str, Any] = {"database": "unknown", "ollama": "disabled"}

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc}"

    if settings.extract_enabled:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{settings.ollama_base_url}/api/tags")
                checks["ollama"] = "ok" if response.status_code == 200 else "unreachable"
        except Exception:  # noqa: BLE001
            checks["ollama"] = "unreachable"

    is_ready = checks["database"] == "ok"
    return {"ready": is_ready, "checks": checks}
