import datetime
import pytest
import sqlite3
from database.repository import AdRepository
from agents.permits import check_legal_basis, STATUS_CONFIRMED_VALID, STATUS_ABSENCE_ESTABLISHED, STATUS_UNVERIFIED
from agents.scoring import calculate_risk_score

@pytest.fixture
def temp_repo(tmp_path):
    db_file = str(tmp_path / "test_permits.db")
    repo = AdRepository(db_path=db_file)

    # Insert test complexes
    with repo._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO developers VALUES ('dev-test', 'ТОО Тест ДЕМО', '111222333444', '+77001112233')")
        cursor.execute("INSERT INTO complexes VALUES ('c-case-a', 'ЖК Кейс А', 'dev-test', 'Адрес A', 'Р-н A', 'Алматы', 0, 'green', 'pending', NULL, NULL, NULL)")
        cursor.execute("INSERT INTO complexes VALUES ('c-case-b', 'ЖК Кейс B', 'dev-test', 'Адрес B', 'Р-н B', 'Астана', 0, 'green', 'pending', NULL, NULL, NULL)")
        cursor.execute("INSERT INTO complexes VALUES ('c-case-c', 'ЖК Кейс C', 'dev-test', 'Адрес C', 'Р-н C', 'Алматы', 0, 'green', 'pending', NULL, NULL, NULL)")
        cursor.execute("INSERT INTO complexes VALUES ('c-expired', 'ЖК Просрочен', 'dev-test', 'Адрес E', 'Р-н E', 'Шымкент', 0, 'green', 'pending', NULL, NULL, NULL)")
        cursor.execute("INSERT INTO complexes VALUES ('c-multi', 'ЖК Мульти', 'dev-test', 'Адрес M', 'Р-н M', 'Астана', 0, 'green', 'pending', NULL, NULL, NULL)")
        cursor.execute("INSERT INTO complexes VALUES ('c-nodata', 'ЖК БезДанных', 'dev-test', 'Адрес N', 'Р-н N', 'Актобе', 0, 'green', 'pending', NULL, NULL, NULL)")

        # Case B: Absence record
        cursor.execute("""
            INSERT INTO absence_records VALUES (
                'abs-test-b', 'c-case-b', 'Официальный запрос МИО ДЕМО', '2025-02-10T10:00:00Z',
                'absence_established', 'Правовых оснований нет', 1
            )
        """)

        # Case C: Single operator guarantee (active)
        cursor.execute("""
            INSERT INTO permits VALUES (
                'p-test-c', 'dev-test', 'c-case-c', 'single_operator_guarantee', '№ КЖК-100-ДЕМО',
                '2024-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'active',
                'АО КЖК ДЕМО', '2025-02-01T00:00:00Z', 1
            )
        """)

        # Expired permit
        cursor.execute("""
            INSERT INTO permits VALUES (
                'p-test-exp', 'dev-test', 'c-expired', 'mio_permit', '№ МИО-EXP-ДЕМО',
                '2023-01-01T00:00:00Z', '2024-01-01T00:00:00Z', 'expired',
                'МИО ДЕМО', '2025-02-01T00:00:00Z', 1
            )
        """)

        # Multi permits: one expired mio_permit, one active single_operator_guarantee
        cursor.execute("""
            INSERT INTO permits VALUES (
                'p-test-m1', 'dev-test', 'c-multi', 'mio_permit', '№ МИО-EXP',
                '2022-01-01T00:00:00Z', '2023-01-01T00:00:00Z', 'expired',
                'МИО ДЕМО', '2025-02-01T00:00:00Z', 1
            )
        """)
        cursor.execute("""
            INSERT INTO permits VALUES (
                'p-test-m2', 'dev-test', 'c-multi', 'single_operator_guarantee', '№ КЖК-ACT',
                '2024-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'active',
                'КЖК ДЕМО', '2025-02-01T00:00:00Z', 1
            )
        """)

        conn.commit()

    return repo


def test_case_a_unverified(temp_repo):
    """
    Кейс A: основание не проверено (UNVERIFIED) + платная бронь (R2) + реклама (R3)
    Ожидается: R1 = 0. Балл = 25 (R2) + 10 (R3) = 35, жёлтая зона.
    """
    res = check_legal_basis("c-case-a", as_of_date="2025-02-15T12:00:00Z", repo=temp_repo)
    assert res["status"] == STATUS_UNVERIFIED
    assert res["r1_eligible"] is False

    # Factors confirmed: R2, R3 (R1 not added)
    factors = ["R2", "R3"]
    score, zone, label = calculate_risk_score(factors)
    assert score == 35
    assert zone == "yellow"


def test_case_b_absence_established(temp_repo):
    """
    Кейс B: отсутствие установлено (ABSENCE_ESTABLISHED) + депозит (R2) + реклама (R3)
    Ожидается: R1 (+35) + R2 (+25) + R3 (+10) = 70 баллов, красная зона (60+ И R1+R2).
    """
    res = check_legal_basis("c-case-b", as_of_date="2025-02-15T12:00:00Z", repo=temp_repo)
    assert res["status"] == STATUS_ABSENCE_ESTABLISHED
    assert res["r1_eligible"] is True

    # Factors confirmed: R1, R2, R3
    factors = ["R1", "R2", "R3"]
    score, zone, label = calculate_risk_score(factors)
    assert score == 70
    assert zone == "red"


def test_case_c_confirmed_valid_guarantee(temp_repo):
    """
    Кейс C: действующая гарантия КЖК (CONFIRMED_VALID) + обычная реклама (R3)
    Ожидается: R1 = 0, балл = 10 (R3), зелёная зона. Отсутствие разрешения МИО — не R1.
    """
    res = check_legal_basis("c-case-c", as_of_date="2025-02-15T12:00:00Z", repo=temp_repo)
    assert res["status"] == STATUS_CONFIRMED_VALID
    assert res["r1_eligible"] is False

    factors = ["R3"]
    score, zone, label = calculate_risk_score(factors)
    assert score == 10
    assert zone == "green"


def test_expired_permit_yields_unverified(temp_repo):
    """
    Просроченное разрешение без подтверждённого акта отсутствия -> UNVERIFIED, R1 = 0.
    """
    res = check_legal_basis("c-expired", as_of_date="2025-02-15T12:00:00Z", repo=temp_repo)
    assert res["status"] == STATUS_UNVERIFIED
    assert res["r1_eligible"] is False
    assert len(res["expired_or_invalid_permits"]) == 1


def test_two_permits_one_active_one_expired(temp_repo):
    """
    Два разных основания: одно просрочено, одно действует -> CONFIRMED_VALID.
    """
    res = check_legal_basis("c-multi", as_of_date="2025-02-15T12:00:00Z", repo=temp_repo)
    assert res["status"] == STATUS_CONFIRMED_VALID
    assert res["r1_eligible"] is False
    assert len(res["valid_permits"]) == 1


def test_no_data_or_unavailable_registry(temp_repo):
    """
    Недоступный реестр / отсутствие данных -> UNVERIFIED (0 баллов, «Нужна проверка»).
    """
    res = check_legal_basis("c-nodata", as_of_date="2025-02-15T12:00:00Z", repo=temp_repo)
    assert res["status"] == STATUS_UNVERIFIED
    assert res["r1_eligible"] is False
