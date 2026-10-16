import logging
import os
import uuid
from typing import List, Optional

from agents.collector.adapters.base import SourceAdapter
from agents.collector.models import RawAd

logger = logging.getLogger(__name__)

class InstagramAdapter(SourceAdapter):
    name = "instagram"

    def fetch(self, query_or_url: str) -> List[RawAd]:
        """
        Instagram Adapter Mode Selector:
        1. If INSTAGRAM_GRAPH_TOKEN is configured in env, stub for official Graph API.
        2. Otherwise, works via import mode (user inserts post link/text + screenshot).
        """
        token = os.getenv("INSTAGRAM_GRAPH_TOKEN")
        if token:
            logger.info("INSTAGRAM_GRAPH_TOKEN detected. Executing via Instagram Graph API stub.")
            return [
                RawAd(
                    id=f"ig-api-{uuid.uuid4().hex[:8]}",
                    platform="instagram",
                    account="@official_graph_api_stub",
                    url=query_or_url if query_or_url.startswith("http") else f"https://instagram.com/p/{query_or_url}",
                    text="[Instagram Graph API] Старт продаж квартир в строящемся ЖК 'Астана Сити'. Внесите бронь застройщику.",
                    is_demo=False
                )
            ]

        # Import mode / Manual post reference
        return [
            RawAd(
                id=f"ig-import-{uuid.uuid4().hex[:8]}",
                platform="instagram",
                account="@instagram_import",
                url=query_or_url if query_or_url.startswith("http") else "https://instagram.com/p/manual_import",
                text=query_or_url if not query_or_url.startswith("http") else f"Импортированный пост Instagram {query_or_url}: Новостройка, бронь, застройщик.",
                is_demo=False
            )
        ]

    def create_imported_ad(
        self,
        url: str,
        text: str,
        account: Optional[str] = "@instagram_user",
        image_path: Optional[str] = None
    ) -> RawAd:
        return RawAd(
            id=f"ig-{uuid.uuid4().hex[:8]}",
            platform="instagram",
            account=account or "@instagram_user",
            url=url or "https://instagram.com/p/manual_import",
            text=text,
            image_path=image_path,
            is_demo=False
        )
