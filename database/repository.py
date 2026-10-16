import datetime
import json
import os
import sqlite3
import uuid
from typing import List, Optional, Dict, Any
from agents.collector.models import RawAd

class AdRepository:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.getenv("DB_PATH", "saq_qurylys.db")
        self.db_path = db_path
        self._init_db()
        self._seed_demo_data()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Ads table
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

            # Developers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS developers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    bin TEXT NOT NULL UNIQUE,
                    contact TEXT
                )
            """)

            # Complexes (ЖК) table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS complexes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    developer_id TEXT,
                    address TEXT,
                    district TEXT,
                    city TEXT,
                    risk_score INTEGER DEFAULT 0,
                    risk_zone TEXT DEFAULT 'green',
                    review_status TEXT DEFAULT 'pending',
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    analyst_note TEXT,
                    FOREIGN KEY(developer_id) REFERENCES developers(id)
                )
            """)

            # Permit types table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS permit_types (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    legal_basis_note TEXT
                )
            """)

            # Permits table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS permits (
                    id TEXT PRIMARY KEY,
                    developer_id TEXT,
                    complex_id TEXT NOT NULL,
                    permit_type_code TEXT NOT NULL,
                    number TEXT NOT NULL,
                    issued_at TEXT,
                    valid_until TEXT,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    is_demo INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(complex_id) REFERENCES complexes(id),
                    FOREIGN KEY(permit_type_code) REFERENCES permit_types(code)
                )
            """)

            # Absence records table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS absence_records (
                    id TEXT PRIMARY KEY,
                    complex_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    result TEXT NOT NULL,
                    note TEXT,
                    is_demo INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(complex_id) REFERENCES complexes(id)
                )
            """)

            # Hypotheses table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hypotheses (
                    id TEXT PRIMARY KEY,
                    ad_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    evidence_quote TEXT,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(ad_id) REFERENCES ads(id)
                )
            """)

            # Audit logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id TEXT PRIMARY KEY,
                    ad_id TEXT NOT NULL,
                    hypothesis_id TEXT,
                    action TEXT NOT NULL,
                    author TEXT NOT NULL,
                    prev_score INTEGER,
                    new_score INTEGER,
                    timestamp TEXT NOT NULL
                )
            """)

            # LLM logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS llm_logs (
                    id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    response TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    validation_result TEXT NOT NULL
                )
            """)

            conn.commit()

    def _seed_demo_data(self):
        demo_developers = [
            ("dev-001", "ТОО Алатау Строй ДЕМО", "123456789012", "+77011112233"),
            ("dev-002", "ТОО Астана Курылыс ДЕМО", "234567890123", "+77012223344"),
            ("dev-003", "ТОО Гранд Бийлдер ДЕМО", "345678901234", "+77013334455"),
            ("dev-004", "ТОО Шымкент Инвест ДЕМО", "456789012355", "+77014445566"),
            ("dev-005", "ТОО Капитал Строй ДЕМО", "567890123456", "+77015556677"),
            ("dev-006", "ТОО Нура Девелопмент ДЕМО", "678901234567", "+77016667788"),
            ("dev-007", "ТОО Самрук Хоумс ДЕМО", "789012345678", "+77017778899"),
            ("dev-008", "ТОО Актобе Строй ДЕМО", "890123456789", "+77018889900"),
        ]

        demo_complexes = [
            ("c-001", "ЖК Алатау Премиум", "dev-001", "ул. Абая 150", "Бостандыкский р-н", "Алматы", 0, "green"),
            ("c-002", "ЖК Есиль Ривер", "dev-002", "ул. Кабанбай батыра 25", "Есильский р-н", "Астана", 0, "green"),
            ("c-003", "ЖК Байтерек Тауэрс", "dev-003", "пр. Тауелсиздик 10", "р-н Алматы", "Астана", 0, "green"),
            ("c-004", "ЖК Шымкент Сити", "dev-004", "мкр. Нурсат", "Каратауский р-н", "Шымкент", 0, "green"),
            ("c-005", "ЖК Арман", "dev-005", "ул. Достык 85", "Медеуский р-н", "Алматы", 0, "green"),
            ("c-006", "ЖК Нура", "dev-006", "ул. Сыганак 40", "Есильский р-н", "Астана", 0, "green"),
            ("c-007", "ЖК Астана Плаза", "dev-007", "пр. Мангилик Ел 55", "Есильский р-н", "Астана", 0, "green"),
            ("c-008", "ЖК Актюбинск Сити", "dev-008", "пр. Абилкайыр хана", "Центр", "Актобе", 0, "green"),
        ]

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for dev in demo_developers:
                cursor.execute("""
                    INSERT OR IGNORE INTO developers (id, name, bin, contact) VALUES (?, ?, ?, ?)
                """, dev)
            for cplx in demo_complexes:
                cursor.execute("""
                    INSERT OR IGNORE INTO complexes (id, name, developer_id, address, district, city, risk_score, risk_zone)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, cplx)

            # Seed permits from data/permits.json if exists
            permits_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "permits.json")
            if os.path.exists(permits_file):
                try:
                    with open(permits_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    for pt in data.get("permit_types", []):
                        cursor.execute("""
                            INSERT OR IGNORE INTO permit_types (code, name, legal_basis_note)
                            VALUES (?, ?, ?)
                        """, (pt["code"], pt["name"], pt.get("legal_basis_note", "")))

                    for p in data.get("permits", []):
                        cursor.execute("""
                            INSERT OR IGNORE INTO permits (
                                id, developer_id, complex_id, permit_type_code, number,
                                issued_at, valid_until, status, source, verified_at, is_demo
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            p["id"], p.get("developer_id"), p["complex_id"], p["permit_type_code"],
                            p["number"], p.get("issued_at"), p.get("valid_until"), p["status"],
                            p["source"], p["verified_at"], 1 if p.get("is_demo", True) else 0
                        ))

                    for a in data.get("absence_records", []):
                        cursor.execute("""
                            INSERT OR IGNORE INTO absence_records (
                                id, complex_id, source, verified_at, result, note, is_demo
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            a["id"], a["complex_id"], a["source"], a["verified_at"],
                            a["result"], a.get("note", ""), 1 if a.get("is_demo", True) else 0
                        ))
                except Exception as e:
                    print(f"Error seeding permits.json: {e}")

            conn.commit()

    def save_ad(self, ad: RawAd) -> bool:
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
                return False

    def get_ad(self, ad_id: str) -> Optional[RawAd]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
            r = cursor.fetchone()
            if not r:
                return None
            return RawAd(
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

    def save_hypothesis(self, hyp: Dict[str, Any]) -> str:
        hyp_id = hyp.get("id") or f"hyp-{uuid.uuid4().hex[:8]}"
        created_at = hyp.get("created_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload_json = json.dumps(hyp.get("payload_json", {}), ensure_ascii=False)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO hypotheses (
                    id, ad_id, type, title, description, evidence_quote,
                    confidence, source, status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hyp_id,
                hyp["ad_id"],
                hyp["type"],
                hyp["title"],
                hyp.get("description", ""),
                hyp.get("evidence_quote", ""),
                float(hyp["confidence"]),
                hyp["source"],
                hyp.get("status", "pending"),
                payload_json,
                created_at
            ))
            conn.commit()
        return hyp_id

    def get_hypotheses_by_ad(self, ad_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM hypotheses WHERE ad_id = ? ORDER BY created_at DESC", (ad_id,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                p_json = json.loads(r["payload_json"]) if r["payload_json"] else {}
                results.append({
                    "id": r["id"],
                    "ad_id": r["ad_id"],
                    "type": r["type"],
                    "title": r["title"],
                    "description": r["description"],
                    "evidence_quote": r["evidence_quote"],
                    "confidence": r["confidence"],
                    "source": r["source"],
                    "status": r["status"],
                    "payload": p_json,
                    "created_at": r["created_at"]
                })
            return results

    def get_hypothesis(self, hyp_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM hypotheses WHERE id = ?", (hyp_id,))
            r = cursor.fetchone()
            if not r:
                return None
            p_json = json.loads(r["payload_json"]) if r["payload_json"] else {}
            return {
                "id": r["id"],
                "ad_id": r["ad_id"],
                "type": r["type"],
                "title": r["title"],
                "description": r["description"],
                "evidence_quote": r["evidence_quote"],
                "confidence": r["confidence"],
                "source": r["source"],
                "status": r["status"],
                "payload": p_json,
                "created_at": r["created_at"]
            }

    def update_hypothesis_status(self, hyp_id: str, status: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE hypotheses SET status = ? WHERE id = ?", (status, hyp_id))
            conn.commit()
            return cursor.rowcount > 0

    def save_audit_log(self, ad_id: str, hypothesis_id: Optional[str], action: str, author: str, prev_score: int, new_score: int):
        log_id = f"audit-{uuid.uuid4().hex[:8]}"
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_logs (id, ad_id, hypothesis_id, action, author, prev_score, new_score, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (log_id, ad_id, hypothesis_id, action, author, prev_score, new_score, ts))
            conn.commit()

    def get_audit_logs(self, ad_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []
        if ad_id:
            query += " AND ad_id = ?"
            params.append(ad_id)
        query += " ORDER BY timestamp DESC"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def save_llm_log(self, agent: str, model: str, prompt: str, response: str, validation_result: str):
        log_id = f"llm-{uuid.uuid4().hex[:8]}"
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO llm_logs (id, agent, model, prompt, response, timestamp, validation_result)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (log_id, agent, model, prompt, response, ts, validation_result))
            conn.commit()

    def get_complexes(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = """
            SELECT c.*, d.name as developer_name, d.bin as developer_bin
            FROM complexes c
            LEFT JOIN developers d ON c.developer_id = d.id
        """
        params = []
        if query:
            sql += " WHERE c.name LIKE ? OR c.address LIKE ? OR c.district LIKE ? OR d.name LIKE ?"
            q = f"%{query}%"
            params = [q, q, q, q]

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_complex_by_id(self, complex_id: str) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT c.*, d.name as developer_name, d.bin as developer_bin
            FROM complexes c
            LEFT JOIN developers d ON c.developer_id = d.id
            WHERE c.id = ?
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (complex_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_complex_risk(self, complex_id: str, risk_score: int, risk_zone: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE complexes SET risk_score = ?, risk_zone = ? WHERE id = ?", (risk_score, risk_zone, complex_id))
            conn.commit()

    def update_complex_review(self, complex_id: str, review_status: str, author: str, note: Optional[str] = None):
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE complexes
                SET review_status = ?, reviewed_by = ?, reviewed_at = ?, analyst_note = ?
                WHERE id = ?
            """, (review_status, author, ts, note or "", complex_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_permit_types(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM permit_types")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_permits_by_complex(self, complex_id: str) -> List[Dict[str, Any]]:
        sql = """
            SELECT p.*, pt.name as permit_type_name, pt.legal_basis_note
            FROM permits p
            LEFT JOIN permit_types pt ON p.permit_type_code = pt.code
            WHERE p.complex_id = ?
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (complex_id,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_absence_records_by_complex(self, complex_id: str) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM absence_records WHERE complex_id = ?"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (complex_id,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_developer(self, bin_or_name: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM developers WHERE bin = ? OR name LIKE ?"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (bin_or_name, f"%{bin_or_name}%"))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_related_ads(self, account: Optional[str]) -> List[RawAd]:
        if not account or account == "Unknown":
            return []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ads WHERE account = ?", (account,))
            rows = cursor.fetchall()
            return [
                RawAd(
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
                ) for r in rows
            ]
