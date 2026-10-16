import re
import hashlib
from typing import List, Dict, Any, Optional
from database.repository import AdRepository

def normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text or "").strip().lower()

def validate_quote(quote: str, source_text: str) -> bool:
    if not quote or not quote.strip():
        return False
    norm_quote = normalize_text(quote)
    norm_text = normalize_text(source_text)
    return norm_quote in norm_text

def extract_phone_numbers(text: str) -> List[str]:
    """
    Extracts phone numbers from text and normalizes them.
    Patterns: +7 (701) 123-45-67, 87011234567, 7011234567, etc.
    """
    if not text:
        return []
    # Match patterns with 10-11 digits
    raw_matches = re.findall(r'(?:\+?7|8)?[\s\-\(]*(\d{3})[\s\-\)]*(\d{3})[\s\-]*(\d{2})[\s\-]*(\d{2})', text)
    phones = []
    for m in raw_matches:
        digits = "".join(m)
        if len(digits) == 10:
            phones.append(f"+7{digits}")
    return list(set(phones))

def hash_phone(phone: str) -> str:
    """
    Hashes phone number using SHA-256 for privacy.
    """
    clean_p = re.sub(r'\D', '', phone or "")
    return hashlib.sha256(clean_p.encode('utf-8')).hexdigest()[:16]

def mask_phone(phone: str) -> str:
    """
    Masks phone number e.g. +7 (701) ***-**-67
    """
    clean_p = re.sub(r'\D', '', phone or "")
    if len(clean_p) >= 10:
        return f"+7 ({clean_p[-10:-7]}) ***-**-{clean_p[-2:]}"
    return "****"

class MatcherTools:
    def __init__(self, repo: AdRepository):
        self.repo = repo

    def find_residential_complex(self, query: str) -> List[Dict[str, Any]]:
        return self.repo.get_complexes(query=query)

    def get_developer(self, bin_or_name: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_developer(bin_or_name=bin_or_name)

    def list_ads_by_phone(self, phone_hash_or_account: str) -> List[Dict[str, Any]]:
        ads = self.repo.get_related_ads(account=phone_hash_or_account)
        return [ad.model_dump() for ad in ads]

    def get_complex(self, id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_complex_by_id(complex_id=id)
