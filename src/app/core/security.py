from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_api_key is None or x_api_key not in settings.api_key_list:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
