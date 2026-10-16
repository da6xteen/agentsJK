import datetime
import json
import logging
import re
from typing import List
from bs4 import BeautifulSoup
import httpx

from agents.collector.adapters.base import SourceAdapter
from agents.collector.models import RawAd

logger = logging.getLogger(__name__)

class KrishaAdapter(SourceAdapter):
    name = "krisha"
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SAQ-QURYLYS-Collector/1.0"

    def fetch(self, query_or_url: str) -> List[RawAd]:
        ads = []
        try:
            if query_or_url.startswith("http://") or query_or_url.startswith("https://"):
                html_content = self._fetch_url(query_or_url)
                ad = self.parse_html(html_content, url=query_or_url)
                if ad:
                    ads.append(ad)
            else:
                # Search query simulation or URL batching
                search_url = f"https://krisha.kz/a/show/990001"
                html_content = self._fetch_url(search_url)
                ad = self.parse_html(html_content, url=search_url)
                if ad:
                    ads.append(ad)
        except Exception as e:
            logger.error(f"Error in KrishaAdapter fetching {query_or_url}: {e}")
            # Do not crash pipeline, caller handles errors or returns empty list
            raise e
        return ads

    def _fetch_url(self, url: str) -> str:
        headers = {"User-Agent": self.DEFAULT_USER_AGENT}
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text

    def parse_html(self, html_content: str, url: str) -> RawAd:
        soup = BeautifulSoup(html_content, "html.parser")

        # Extract title
        title_el = soup.find(class_=re.compile(r"offer__title|title"))
        title = title_el.get_text(strip=True) if title_el else ""

        # Extract description
        desc_el = soup.find(class_=re.compile(r"offer__description|text|description"))
        description = desc_el.get_text(" ", strip=True) if desc_el else ""

        # Extract price
        price_el = soup.find(class_=re.compile(r"offer__price|price"))
        price = price_el.get_text(strip=True) if price_el else ""

        # Extract phone (masked)
        phone_el = soup.find(class_=re.compile(r"phone"))
        phone = phone_el.get_text(strip=True) if phone_el else ""

        # Extract address
        addr_el = soup.find(class_=re.compile(r"offer__advert-title|address"))
        address = addr_el.get_text(" ", strip=True) if addr_el else ""

        # Extract author/account
        author_el = soup.find(class_=re.compile(r"offer__author|author"))
        account = author_el.get_text(strip=True) if author_el else "Krisha User"

        # Combine full text
        full_text_parts = [p for p in [title, address, price, phone, description] if p]
        full_text = " | ".join(full_text_parts) if full_text_parts else "Нет описания"

        # Generate unique ID from URL or hash
        ad_id = f"krisha-{hash(url) & 0xffffffff}"

        return RawAd(
            id=ad_id,
            platform="krisha",
            account=account,
            url=url,
            text=full_text,
            is_demo=False
        )
