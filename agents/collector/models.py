import datetime
import hashlib
import re
from typing import Literal, Optional
from pydantic import BaseModel, Field

PlatformType = Literal["krisha", "telegram", "instagram", "manual", "demo"]
StatusType = Literal["new", "filtered", "error"]

class RawAd(BaseModel):
    id: str
    platform: PlatformType
    account: Optional[str] = "Unknown"
    url: str
    text: str
    image_path: Optional[str] = None
    published_at: Optional[str] = None
    captured_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    is_demo: bool = False
    status: StatusType = "new"
    status_reason: Optional[str] = None
    dedup_hash: Optional[str] = None

    def calculate_dedup_hash(self) -> str:
        norm_text = re.sub(r'\s+', ' ', self.text.strip().lower())
        norm_url = re.sub(r'\s+', '', self.url.strip().lower())
        raw_key = f"{norm_url}|{norm_text}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def model_post_init(self, __context):
        if not self.dedup_hash:
            self.dedup_hash = self.calculate_dedup_hash()
