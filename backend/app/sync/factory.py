from app.config import get_settings
from app.db import get_sessionmaker
from app.ingestion.providers.espn.provider import EspnProvider
from app.sync.service import SyncService


def build_sync_service() -> tuple[SyncService, EspnProvider]:
    settings = get_settings()
    provider = EspnProvider(settings)
    return SyncService(get_sessionmaker(), provider, settings), provider
