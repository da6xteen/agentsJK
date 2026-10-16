import os
import sqlite3
from typing import List, Optional
from agents.collector.models import RawAd

class AdRepository:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.getenv("DB_PATH", "saq_qurylys.db")
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ads (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    account TEXT,
                    url TEXT NOT NULL,
                    text TEXT NOT NULL,
                    image_path TEXT,
                    published_at TEXT,
                    captured_at TEXT NOT NULL,
                    is_demo INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    status_reason TEXT,
                    dedup_hash TEXT UNIQUE NOT NULL
                )
            """)
            conn.commit()

    def save_ad(self, ad: RawAd) -> bool:
        """
        Saves ad to DB with deduplication check.
        Returns True if saved, False if duplicate.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO ads (
                        id, platform, account, url, text, image_path,
                        published_at, captured_at, is_demo, status, status_reason, dedup_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ad.id,
                    ad.platform,
                    ad.account,
                    ad.url,
                    ad.text,
                    ad.image_path,
                    ad.published_at,
                    ad.captured_at,
                    1 if ad.is_demo else 0,
                    ad.status,
                    ad.status_reason,
                    ad.dedup_hash
                ))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Duplicate entry (dedup_hash or id exists)
                return False

    def get_ads(
        self,
        platform: Optional[str] = None,
        status: Optional[str] = None,
        is_demo: Optional[bool] = None
    ) -> List[RawAd]:
        query = "SELECT * FROM ads WHERE 1=1"
        params = []

        if platform:
            query += " AND platform = ?"
            params.append(platform)
        if status:
            query += " AND status = ?"
            params.append(status)
        if is_demo is not None:
            query += " AND is_demo = ?"
            params.append(1 if is_demo else 0)

        query += " ORDER BY captured_at DESC"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            ads = []
            for r in rows:
                ad = RawAd(
                    id=r["id"],
                    platform=r["platform"],
                    account=r["account"],
                    url=r["url"],
                    text=r["text"],
                    image_path=r["image_path"],
                    published_at=r["published_at"],
                    captured_at=r["captured_at"],
                    is_demo=bool(r["is_demo"]),
                    status=r["status"],
                    status_reason=r["status_reason"],
                    dedup_hash=r["dedup_hash"]
                )
                ads.append(ad)
            return ads
