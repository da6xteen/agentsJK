import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

import database.repository
from app.main import app
from agents.matcher.payment_extractor import (
    PaymentExtractor,
    extract_payment_rules,
    PaymentExtractorResult,
    validate_quote
)
from agents.matcher.complex_matcher import (
    ComplexMatcher,
    match_complexes_fallback,
    evaluate_linking_thresholds,
    ComplexCandidate
)
from agents.scoring import calculate_risk_score

client = TestClient(app)

def test_regex_fallback_payment_phrasings():
    # Phrasing 1: бронь
    text1 = "Забронируйте квартиру в ЖК сегодня! Бронь составляет 200 000 тг."
    res1 = extract_payment_rules(text1)
    assert res1.offers_payment is True
    assert res1.payment_type == "бронь"
    assert res1.amount == 200000.0

    # Phrasing 2: депозит
    text2 = "Для покупки требуется начальный депозит 500 000 тенге."
    res2 = extract_payment_rules(text2)
    assert res2.offers_payment is True
    assert res2.payment_type == "депозит"
    assert res2.amount == 500000.0

    # Phrasing 3: задаток
    text3 = "Внесите задаток до конца недели для сохранения специальной цены."
    res3 = extract_payment_rules(text3)
    assert res3.offers_payment is True
    assert res3.payment_type == "задаток"

    # Phrasing 4: первоначальный взнос
    text4 = "Первоначальный взнос 1 000 000 тг при бронировании."
    res4 = extract_payment_rules(text4)
    assert res4.offers_payment is True
    assert res4.payment_type == "первоначальный_взнос"
    assert res4.amount == 1000000.0

    # Phrasing 5: non-payment text
    text5 = "Продам квартиру с готовым ремонтом в сданном доме."
    res5 = extract_payment_rules(text5)
    assert res5.offers_payment is False
    assert res5.payment_type == "нет"


def test_quote_validation():
    source_text = "Внимание! Закрепим за вами квартиру при бронировании! Нужен начальный депозит всего 500 000 тенге."

    # Valid verbatim quote
    assert validate_quote("Нужен начальный депозит всего 500 000 тенге", source_text) is True

    # Fabricated quote rejected
    assert validate_quote("Секретный перевод на карту физлица", source_text) is False

    extractor = PaymentExtractor()
    bad_res = PaymentExtractorResult(
        offers_payment=True,
        payment_type="депозит",
        amount=500000,
        currency="KZT",
        evidence_quote="Поддельная цитата отсутствующая в тексте",
        confidence=0.9,
        reasoning_short="тест",
        source="llm"
    )
    validated = extractor._post_validate(bad_res, source_text)
    assert validated.offers_payment is False
    assert validated.payment_type == "нет"


def test_invalid_json_llm_retry_and_fallback():
    extractor = PaymentExtractor(repo=database.repository.repo)
    extractor.api_key = "fake_key_for_test"

    source_text = "Требуется депозит 300 000 тг."

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="INVALID_NON_JSON_RESPONSE")]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic.return_value = mock_client

        result = extractor.process(source_text)

        assert result.offers_payment is True
        assert result.payment_type == "депозит"
        assert result.source == "rules"


def test_matching_threshold_logic():
    # Case 1: High confidence and good margin -> auto-linked
    c1 = ComplexCandidate(complex_id="c-001", complex_name="ЖК Алатау", confidence=0.85)
    c2 = ComplexCandidate(complex_id="c-002", complex_name="ЖК Байтерек", confidence=0.50)
    res1 = evaluate_linking_thresholds([c1, c2], source="rules")
    assert res1.auto_linked is True
    assert res1.status == "linked"
    assert res1.top_candidate_id == "c-001"

    # Case 2: High confidence but small margin -> Needs analyst check
    c3 = ComplexCandidate(complex_id="c-001", complex_name="ЖК Алатау", confidence=0.80)
    c4 = ComplexCandidate(complex_id="c-002", complex_name="ЖК Алатау Премиум", confidence=0.70)
    res2 = evaluate_linking_thresholds([c3, c4], source="rules")
    assert res2.auto_linked is False
    assert res2.status == "Нужна проверка"

    # Case 3: Top confidence below 0.75 threshold -> Needs analyst check
    c5 = ComplexCandidate(complex_id="c-001", complex_name="ЖК Алатау", confidence=0.60)
    res3 = evaluate_linking_thresholds([c5], source="rules")
    assert res3.auto_linked is False
    assert res3.status == "Нужна проверка"


def test_risk_scoring_rules_and_zones():
    # Green zone: 0 - 24
    score_green, zone_green, _ = calculate_risk_score(["R3"]) # 10
    assert score_green == 10
    assert zone_green == "green"

    # Yellow zone: 25 - 59
    score_yellow, zone_yellow, _ = calculate_risk_score(["R2", "R3"]) # 25 + 10 = 35
    assert score_yellow == 35
    assert zone_yellow == "yellow"

    # Score >= 60 WITHOUT R1+R2 pair -> Yellow zone!
    score_yellow_60, zone_yellow_60, _ = calculate_risk_score(["R1", "R3", "R4"]) # 35 + 10 + 15 = 60
    assert score_yellow_60 == 60
    assert zone_yellow_60 == "yellow"

    # Score >= 60 WITH BOTH R1 AND R2 confirmed -> Red zone!
    score_red, zone_red, _ = calculate_risk_score(["R1", "R2", "R3"]) # 35 + 25 + 10 = 70
    assert score_red == 70
    assert zone_red == "red"


def test_accept_recalculates_score_reject_does_not():
    # 1. Run collector demo to get an ad
    col_resp = client.post("/api/collector/run", json={"source": "demo", "query_or_url": "demo"})
    assert col_resp.status_code == 200
    ad_id = col_resp.json()["ads"][0]["id"]

    # 2. Analyze ad
    an_resp = client.post(f"/api/ads/{ad_id}/analyze")
    assert an_resp.status_code == 200
    hypotheses = client.get(f"/api/ads/{ad_id}/hypotheses").json()["hypotheses"]
    assert len(hypotheses) > 0

    hyp = hypotheses[0]
    hyp_id = hyp["id"]

    # Initial score should be 0 before acceptance
    init_score = client.get(f"/api/ads/{ad_id}/hypotheses").json()["risk_score"]
    assert init_score == 0

    # 3. Reject hypothesis -> score must remain unchanged
    rej_resp = client.post(f"/api/hypotheses/{hyp_id}/reject", json={"author": "Тестовый Аналитик"})
    assert rej_resp.status_code == 200
    post_rej_score = client.get(f"/api/ads/{ad_id}/hypotheses").json()["risk_score"]
    assert post_rej_score == init_score

    # 4. Create another pending hypothesis and Accept it -> score must update
    r2_hyp_id = database.repository.repo.save_hypothesis({
        "ad_id": ad_id,
        "type": "R2",
        "title": "R2: прямое предложение внести деньги",
        "description": "Тест",
        "evidence_quote": "депозит",
        "confidence": 0.9,
        "source": "rules",
        "status": "pending"
    })

    acc_resp = client.post(f"/api/hypotheses/{r2_hyp_id}/accept", json={"author": "Тестовый Аналитик"})
    assert acc_resp.status_code == 200
    post_acc_score = client.get(f"/api/ads/{ad_id}/hypotheses").json()["risk_score"]
    assert post_acc_score == 25 # R2 weight is 25

    # Check audit log saved
    audit_resp = client.get("/api/audit-logs", params={"ad_id": ad_id})
    assert audit_resp.status_code == 200
    logs = audit_resp.json()
    assert len(logs) >= 2
