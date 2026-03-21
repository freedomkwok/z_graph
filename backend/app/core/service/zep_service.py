import httpx

from app.core.config import settings


class ZepService:
    async def is_available(self) -> bool:
        if not settings.zep_api_url:
            return False

        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(settings.zep_api_url)
                return response.status_code < 500
        except httpx.HTTPError:
            return False
