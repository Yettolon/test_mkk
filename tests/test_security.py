import pytest
from fastapi import HTTPException

from app.config import settings
from app.security import require_api_key


@pytest.mark.asyncio
async def test_api_key_accepts_configured_key() -> None:
    assert await require_api_key(settings.api_key) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "", "wrong-key"])
async def test_api_key_rejects_invalid_key(value: str | None) -> None:
    with pytest.raises(HTTPException) as exc:
        await require_api_key(value)
    assert exc.value.status_code == 401
