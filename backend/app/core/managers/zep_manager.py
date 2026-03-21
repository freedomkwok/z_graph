from app.core.service.zep_service import ZepService

class ZepManager:
    def __init__(self, zep_service: ZepService) -> None:
        self.zep_service = zep_service

    async def ping_dependencies(self) -> dict[str, bool]:
        return {"zep_available": await self.zep_service.is_available()}
