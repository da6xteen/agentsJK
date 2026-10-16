import datetime
from typing import Optional, Dict, Any, List
from database.repository import AdRepository

STATUS_CONFIRMED_VALID = "CONFIRMED_VALID"
STATUS_ABSENCE_ESTABLISHED = "ABSENCE_ESTABLISHED"
STATUS_UNVERIFIED = "UNVERIFIED"

def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime.datetime]:
    if not dt_str:
        return None
    try:
        # Normalize ISO string with Z or offsets
        clean_str = dt_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(clean_str)
    except Exception:
        return None

def check_legal_basis(
    complex_id: str,
    as_of_date: Optional[Any] = None,
    repo: Optional[AdRepository] = None
) -> Dict[str, Any]:
    """
    Deterministically evaluates legal bases (permits) for a residential complex.
    Returns:
    - CONFIRMED_VALID: Valid active permit exists -> R1 NOT granted.
    - ABSENCE_ESTABLISHED: Formally verified that NO valid legal basis exists -> R1 (+35) eligible.
    - UNVERIFIED: Data missing, registry unavailable, expired permit without absence record -> R1 = 0, 'Нужна проверка'.
    """
    if repo is None:
        repo = AdRepository()

    # Determine reference date
    if as_of_date is None:
        ref_dt = datetime.datetime.now(datetime.timezone.utc)
    elif isinstance(as_of_date, datetime.datetime):
        ref_dt = as_of_date.astimezone(datetime.timezone.utc) if as_of_date.tzinfo else as_of_date.replace(tzinfo=datetime.timezone.utc)
    elif isinstance(as_of_date, str):
        parsed = parse_iso_datetime(as_of_date)
        ref_dt = parsed if parsed else datetime.datetime.now(datetime.timezone.utc)
    else:
        ref_dt = datetime.datetime.now(datetime.timezone.utc)

    permits = repo.get_permits_by_complex(complex_id)
    absence_records = repo.get_absence_records_by_complex(complex_id)

    valid_permits: List[Dict[str, Any]] = []
    expired_or_invalid_permits: List[Dict[str, Any]] = []

    for p in permits:
        status = p.get("status", "").lower()
        source = p.get("source")
        verified_at = p.get("verified_at")

        # Must have verified metadata
        if not source or not verified_at:
            expired_or_invalid_permits.append(p)
            continue

        if status != "active":
            expired_or_invalid_permits.append(p)
            continue

        # Check dates
        issued_dt = parse_iso_datetime(p.get("issued_at"))
        valid_until_dt = parse_iso_datetime(p.get("valid_until"))

        if issued_dt and ref_dt < issued_dt:
            expired_or_invalid_permits.append(p)
            continue

        if valid_until_dt and ref_dt > valid_until_dt:
            expired_or_invalid_permits.append(p)
            continue

        valid_permits.append(p)

    if valid_permits:
        return {
            "status": STATUS_CONFIRMED_VALID,
            "status_label": "Действующее подтверждённое правовое основание",
            "r1_eligible": False,
            "valid_permits": valid_permits,
            "expired_or_invalid_permits": expired_or_invalid_permits,
            "absence_records": absence_records,
            "note": f"Подтверждено наличие действующих разрешений ({len(valid_permits)} шт.). R1 не начисляется."
        }

    # Check explicit absence records
    valid_absence = [
        a for a in absence_records
        if a.get("result") == "absence_established" and a.get("source") and a.get("verified_at")
    ]

    if valid_absence:
        return {
            "status": STATUS_ABSENCE_ESTABLISHED,
            "status_label": "Установлено отсутствие применимого правового основания",
            "r1_eligible": True,
            "valid_permits": [],
            "expired_or_invalid_permits": expired_or_invalid_permits,
            "absence_records": valid_absence,
            "note": "Проверенными данными официально установлено отсутствие правового основания. Начисляется фактор R1 (+35)."
        }

    return {
        "status": STATUS_UNVERIFIED,
        "status_label": "Правовое основание не проверено (Нужна проверка)",
        "r1_eligible": False,
        "valid_permits": [],
        "expired_or_invalid_permits": expired_or_invalid_permits,
        "absence_records": absence_records,
        "note": "Данные о разрешениях отсутствуют или требуют уточнения. R1 = 0, требуется проверка аналитиком."
    }
