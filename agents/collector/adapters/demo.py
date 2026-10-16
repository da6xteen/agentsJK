import json
import os
from typing import List

from agents.collector.adapters.base import SourceAdapter
from agents.collector.models import RawAd

class DemoAdapter(SourceAdapter):
    name = "demo"

    def __init__(self, seed_filepath: str = "seed/demo_ads.json"):
        self.seed_filepath = seed_filepath

    def fetch(self, query_or_url: str = "") -> List[RawAd]:
        if not os.path.exists(self.seed_filepath):
            raise FileNotFoundError(f"Seed file not found: {self.seed_filepath}")

        with open(self.seed_filepath, "r", encoding="utf-8") as f:
            items = json.load(f)

        ads = []
        for item in items:
            ad = RawAd(
                id=item["id"],
                platform=item["platform"],
                account=item.get("account", "DEMO Account"),
                url=item["url"],
                text=item["text"],
                published_at=item.get("published_at"),
                is_demo=True
            )
            ads.append(ad)

        return ads
