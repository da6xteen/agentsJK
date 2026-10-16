from abc import ABC, abstractmethod
from typing import List
from agents.collector.models import RawAd

class SourceAdapter(ABC):
    name: str

    @abstractmethod
    def fetch(self, query_or_url: str) -> List[RawAd]:
        """
        Fetch raw ads from source given a query, channel, or URL.
        """
        pass
