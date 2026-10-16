import logging
from typing import Dict, List, Optional

from agents.collector.adapters.base import SourceAdapter
from agents.collector.adapters.demo import DemoAdapter
from agents.collector.adapters.instagram import InstagramAdapter
from agents.collector.adapters.krisha import KrishaAdapter
from agents.collector.adapters.manual import ManualAdapter
from agents.collector.adapters.telegram import TelegramAdapter
from agents.collector.filter import check_relevance
from agents.collector.models import RawAd

logger = logging.getLogger(__name__)

class CollectorService:
    def __init__(self, db_session=None):
        self.db = db_session
        self.adapters: Dict[str, SourceAdapter] = {
            "krisha": KrishaAdapter(),
            "telegram": TelegramAdapter(),
            "instagram": InstagramAdapter(),
            "manual": ManualAdapter(),
            "demo": DemoAdapter(),
        }

    def collect(self, source: str, query_or_url: str) -> List[RawAd]:
        adapter = self.adapters.get(source.lower())
        if not adapter:
            raise ValueError(f"Unknown collector source adapter: {source}")

        results: List[RawAd] = []

        try:
            fetched_ads = adapter.fetch(query_or_url)
            for ad in fetched_ads:
                # Apply relevance filter
                is_rel, reason = check_relevance(ad.text)
                if not is_rel:
                    ad.status = "filtered"
                    ad.status_reason = reason

                results.append(ad)

        except Exception as e:
            logger.error(f"Collector error on source '{source}' with query '{query_or_url}': {e}")
            # Create an error record so network/parsing errors don't crash pipeline silently
            error_ad = RawAd(
                id=f"err-{source}-{hash(query_or_url) & 0xffffffff}",
                platform=source if source in ["krisha", "telegram", "instagram", "manual", "demo"] else "manual",
                account="Collector Service",
                url=query_or_url if query_or_url.startswith("http") else f"https://{source}.local/error",
                text=f"Failed to process source '{source}': {str(e)}",
                status="error",
                status_reason=str(e),
                is_demo=False
            )
            results.append(error_ad)

        return results
