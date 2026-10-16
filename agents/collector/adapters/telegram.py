import logging
import os
import re
from typing import List
from bs4 import BeautifulSoup
import httpx

from agents.collector.adapters.base import SourceAdapter
from agents.collector.models import RawAd

logger = logging.getLogger(__name__)

class TelegramAdapter(SourceAdapter):
    name = "telegram"
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SAQ-QURYLYS-Collector/1.0"

    def fetch(self, query_or_url: str) -> List[RawAd]:
        tg_api_id = os.getenv("TELEGRAM_API_ID")
        tg_api_hash = os.getenv("TELEGRAM_API_HASH")

        if tg_api_id and tg_api_hash:
            logger.info("TELEGRAM_API_ID provided: Telethon full client mode available")

        # Keyless fallback mode: Telegram public channel web preview t.me/s/<channel>
        channel_name = self._extract_channel_name(query_or_url)
        preview_url = f"https://t.me/s/{channel_name}"

        try:
            html_content = self._fetch_preview(preview_url)
            return self.parse_html(html_content, channel_name=channel_name)
        except Exception as e:
            logger.error(f"Error fetching Telegram preview for {channel_name}: {e}")
            raise e

    def _extract_channel_name(self, query_or_url: str) -> str:
        clean = query_or_url.strip().lstrip("@")
        if "t.me/" in clean:
            match = re.search(r"t\.me/(?:s/)?([^/]+)", clean)
            if match:
                return match.group(1)
        return clean

    def _fetch_preview(self, url: str) -> str:
        headers = {"User-Agent": self.DEFAULT_USER_AGENT}
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text

    def parse_html(self, html_content: str, channel_name: str) -> List[RawAd]:
        soup = BeautifulSoup(html_content, "html.parser")
        messages = soup.find_all(class_=re.compile(r"tgme_widget_message\b"))

        raw_ads = []
        for idx, msg in enumerate(messages):
            post_id_attr = msg.get("data-post", f"{channel_name}/{idx}")
            post_url = f"https://t.me/{post_id_attr}"

            text_el = msg.find(class_=re.compile(r"tgme_widget_message_text"))
            text = text_el.get_text(" ", strip=True) if text_el else ""

            if not text:
                continue

            time_el = msg.find("time")
            published_at = time_el.get("datetime") if time_el and time_el.get("datetime") else None

            ad = RawAd(
                id=f"tg-{post_id_attr.replace('/', '-')}",
                platform="telegram",
                account=f"@{channel_name}",
                url=post_url,
                text=text,
                published_at=published_at,
                is_demo=False
            )
            raw_ads.append(ad)

        return raw_ads
