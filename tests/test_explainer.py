import pytest
from unittest.mock import MagicMock, patch
from database.repository import AdRepository
from agents.explainer import (
    RiskExplainerAgent,
    RiskExplanationOutput,
    contains_forbidden_words,
    validate_evidence_ids,
    generate_fallback_explanation
)
from agents.permits import STATUS_UNVERIFIED, STATUS_ABSENCE_ESTABLISHED

@pytest.fixture
def temp_repo(tmp_path):
    db_file = str(tmp_path / "test_explainer.db")
    repo = AdRepository(db_path=db_file)
    return repo

def test_contains_forbidden_words():
    assert contains_forbidden_words("Это объявление абсолютно незаконно!") == "незаконно"
    assert contains_forbidden_words("Выявлен факт мошенничества") == "мошенничества"
    assert contains_forbidden_words("Застройщик нарушил закон в этом проекте") == "нарушил закон"
    assert contains_forbidden_words("Обнаружены признаки риска и требуется проверка") is None

def test_validate_evidence_ids():
    output = RiskExplanationOutput(
        summary="Тест",
        factor_explanations=[
            {
                "code": "R2",
                "points": 25,
                "text": "Предложение внести деньги",
                "evidence_ids": ["hyp-1", "hyp-2"]
            }
        ],
        needs_verification=[]
    )
    assert validate_evidence_ids(output, {"hyp-1", "hyp-2", "hyp-3"}) is True
    assert validate_evidence_ids(output, {"hyp-1"}) is False

def test_generate_fallback_explanation():
    cplx = {"name": "ЖК Алатау", "developer_name": "ТОО Строй"}
    legal_check = {
        "status": STATUS_UNVERIFIED,
        "status_label": "Не проверено"
    }
    confirmed_factors = [
        {"code": "R2", "points": 25, "text": "Депозит", "evidence_ids": ["ev-1"]}
    ]
    needs_verif = ["Проверить разрешение"]

    output = generate_fallback_explanation(
        complex_info=cplx,
        legal_check=legal_check,
        confirmed_factors=confirmed_factors,
        needs_verification=needs_verif,
        score=35,
        zone_code="yellow",
        zone_label="Средний риск"
    )

    assert isinstance(output, RiskExplanationOutput)
    assert "ЖК Алатау" in output.summary
    assert "35" in output.summary
    assert "Оценка риска — не юридическое заключение." in output.disclaimer
    # Ensure no forbidden words
    assert contains_forbidden_words(output.summary) is None

def test_explainer_agent_offline_keyless(temp_repo):
    agent = RiskExplainerAgent(repo=temp_repo)
    agent.anthropic_key = None
    agent.openai_key = None

    # Run explanation on c-001
    res = agent.explain("c-001")
    assert res["complex_id"] == "c-001"
    assert res["source"] == "rules"
    assert "explanation" in res
    assert contains_forbidden_words(res["explanation"]["summary"]) is None

def test_explainer_llm_forbidden_word_retry_and_fallback(temp_repo):
    agent = RiskExplainerAgent(repo=temp_repo)
    agent.anthropic_key = "fake_key"

    # Mock response with forbidden word on attempt 1, and invalid JSON on attempt 2 -> triggers fallback
    mock_msg1 = MagicMock()
    mock_msg1.content = [MagicMock(text='{"summary": "Этот проект полностью незаконный!", "factor_explanations": [], "needs_verification": [], "disclaimer": "Оценка риска — не юридическое заключение."}')]

    mock_msg2 = MagicMock()
    mock_msg2.content = [MagicMock(text='INVALID_JSON')]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [mock_msg1, mock_msg2]
        mock_anthropic.return_value = mock_client

        res = agent.explain("c-001")
        assert res["source"] == "rules" # Fell back to rules
        assert contains_forbidden_words(res["explanation"]["summary"]) is None

        # Check that llm logs recorded the attempts
        logs = temp_repo.get_audit_logs() # check llm_logs
        with temp_repo._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM llm_logs WHERE agent = 'explainer'")
            llm_logs = cursor.fetchall()
            assert len(llm_logs) == 2
            assert "failed_forbidden_word" in llm_logs[0]["validation_result"]
