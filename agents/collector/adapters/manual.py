import uuid
from typing import List, Optional

from agents.collector.adapters.base import SourceAdapter
from agents.collector.models import RawAd

class ManualAdapter(SourceAdapter):
    name = "manual"

    def fetch(self, query_or_url: str) -> List[RawAd]:
        return [
            RawAd(
                id=f"manual-{uuid.uuid4().hex[:8]}",
                platform="manual",
                account="Аналитик (ручной ввод)",
                url=query_or_url if query_or_url.startswith("http") else "https://manual-entry.local/ad",
                text=query_or_url if not query_or_url.startswith("http") else f"Ручная публикация: {query_or_url}",
                is_demo=False
            )
        ]

    def create_manual_ad(
        self,
        text: str,
        url: Optional[str] = None,
        account: Optional[str] = None,
        image_path: Optional[str] = None,
        is_demo: bool = False
    ) -> RawAd:
        return RawAd(
            id=f"manual-{uuid.uuid4().hex[:8]}",
            platform="manual",
            account=account or "Аналитик MIO",
            url=url or "https://manual-entry.local/ad",
            text=text,
            image_path=image_path,
            is_demo=is_demo
        )
