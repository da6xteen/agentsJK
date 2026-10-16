import os
import re
import json
import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from agents.permits import check_legal_basis, STATUS_CONFIRMED_VALID, STATUS_ABSENCE_ESTABLISHED, STATUS_UNVERIFIED
from agents.scoring import calculate_risk_score, FACTOR_WEIGHTS
from database.repository import AdRepository

FORBIDDEN_WORDS = [
    r"\bнезаконн\w*",
    r"\bмошенничест\w*",
    r"\bнарушил\s+закон\b",
    r"\bпреступлен\w*",
    r"\bфальсификац\w*",
    r"\bвинов\w*",
    r"\bнелегальн\w*"
]

class FactorExplanation(BaseModel):
    code: str
    points: int
    text: str
    evidence_ids: List[str] = Field(default_factory=list)

class RiskExplanationOutput(BaseModel):
    summary: str
    factor_explanations: List[FactorExplanation]
    needs_verification: List[str]
    disclaimer: str = "Оценка риска — не юридическое заключение."

def contains_forbidden_words(text: str) -> Optional[str]:
    """Returns matched forbidden term if found, else None."""
    for pattern in FORBIDDEN_WORDS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None

def validate_evidence_ids(output: RiskExplanationOutput, valid_evidence_ids: set) -> bool:
    """Ensures all evidence_ids in factor_explanations exist in valid_evidence_ids."""
    for fe in output.factor_explanations:
        for eid in fe.evidence_ids:
            if eid not in valid_evidence_ids:
                return False
    return True

def generate_fallback_explanation(
    complex_info: Dict[str, Any],
    legal_check: Dict[str, Any],
    confirmed_factors: List[Dict[str, Any]],
    needs_verification: List[str],
    score: int,
    zone_code: str,
    zone_label: str
) -> RiskExplanationOutput:
    """
    Deterministic offline template-based explanation generator (Keyless Fallback).
    """
    c_name = complex_info.get("name", "Жилой комплекс")
    dev_name = complex_info.get("developer_name") or "Не указан"

    summary_parts = []
    summary_parts.append(f"Проведена оценка факторов риска по объекту «{c_name}» (застройщик: {dev_name}).")
    summary_parts.append(f"Итоговый показатель риска составляет {score} баллов, объект находится в {zone_code.upper()} зоне ({zone_label}).")

    if legal_check["status"] == STATUS_CONFIRMED_VALID:
        summary_parts.append("Подтверждено наличие действующего правового основания на привлечение средств (фактор R1 не начисляется).")
    elif legal_check["status"] == STATUS_ABSENCE_ESTABLISHED:
        summary_parts.append("Проверенными данными установлено отсутствие правового основания для привлечения средств дольщиков (подтверждён фактор R1 +35).")
    else:
        summary_parts.append("Правовые основания объекта не проверены или реестр недоступен — отсутствие данных не является правонарушением, но требует проверки (R1 = 0 баллов).")

    r2_factors = [f for f in confirmed_factors if f.get("code") == "R2"]
    if r2_factors:
        summary_parts.append("В рекламных объявлениях зафиксированы предложения внесения денежных средств (бронь, депозит или первоначальный взнос) до проверки основания.")

    summary_parts.append("Итоговая карточка сформирована для анализа и требует финальной проверки аналитиком МИО.")
    summary_text = " ".join(summary_parts)

    factor_explanations = []
    for f in confirmed_factors:
        f_code = f.get("code", "")
        f_pts = f.get("points", FACTOR_WEIGHTS.get(f_code, 0))
        f_text = f.get("text", f"Подтверждён фактор {f_code}")
        e_ids = f.get("evidence_ids", [])
        factor_explanations.append(
            FactorExplanation(
                code=f_code,
                points=f_pts,
                text=f_text,
                evidence_ids=e_ids
            )
        )

    return RiskExplanationOutput(
        summary=summary_text,
        factor_explanations=factor_explanations,
        needs_verification=needs_verification if needs_verification else ["Проверить юридические основания на портале e-Licensing / КЖК."],
        disclaimer="Оценка риска — не юридическое заключение."
    )

class RiskExplainerAgent:
    def __init__(self, repo: Optional[AdRepository] = None):
        if repo is None:
            repo = AdRepository()
        self.repo = repo
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")

    def explain(
        self,
        complex_id: str,
        as_of_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Gathers data deterministically and generates explanation via LLM (or fallback).
        """
        cplx = self.repo.get_complex_by_id(complex_id)
        if not cplx:
            raise ValueError(f"Complex with ID {complex_id} not found")

        # 1. Deterministic Legal Basis Check
        legal_check = check_legal_basis(complex_id, as_of_date=as_of_date, repo=self.repo)

        # 2. Find associated ads & hypotheses
        # Search ads linked to this complex
        ads = self.repo.get_ads()
        linked_hypotheses: List[Dict[str, Any]] = []

        for ad in ads:
            ad_hyps = self.repo.get_hypotheses_by_ad(ad.id)
            for h in ad_hyps:
                # Check if hypothesis belongs to this complex or linked to it
                payload = h.get("payload", {})
                if h["type"] == "complex_link" and payload.get("top_candidate_id") == complex_id and h["status"] == "accepted":
                    linked_hypotheses.extend(ad_hyps)
                    break

        # Collect confirmed factors
        confirmed_factors_dict = {}
        valid_evidence_ids = set()

        # If R1 is established via check_legal_basis
        if legal_check["r1_eligible"]:
            r1_id = f"r1-{complex_id}"
            valid_evidence_ids.add(r1_id)
            confirmed_factors_dict["R1"] = {
                "code": "R1",
                "points": 35,
                "text": "Установлено отсутствие применимого правового основания (проверено реестром)",
                "evidence_ids": [r1_id]
            }

        needs_verification = []
        if legal_check["status"] == STATUS_UNVERIFIED:
            needs_verification.append("Необходимо запросить у застройщика или проверить в МИО/КЖК наличие разрешения или гарантии")

        for h in linked_hypotheses:
            h_type = h.get("type")
            h_id = h.get("id", "")
            if h_id:
                valid_evidence_ids.add(h_id)

            if h_type in ["R2", "R3", "R4", "R5", "R6"]:
                if h["status"] == "accepted":
                    if h_type not in confirmed_factors_dict:
                        pts = FACTOR_WEIGHTS.get(h_type, 0)
                        quote = h.get("evidence_quote") or h.get("description") or ""
                        confirmed_factors_dict[h_type] = {
                            "code": h_type,
                            "points": pts,
                            "text": f"{h.get('title', h_type)}: {quote}",
                            "evidence_ids": [h_id] if h_id else []
                        }
                    else:
                        if h_id and h_id not in confirmed_factors_dict[h_type]["evidence_ids"]:
                            confirmed_factors_dict[h_type]["evidence_ids"].append(h_id)
                elif h["status"] == "pending":
                    needs_verification.append(f"Необходимо проверить гипотезу ИИ: {h.get('title')} ({h.get('description')})")

        confirmed_factor_codes = list(confirmed_factors_dict.keys())
        confirmed_factors_list = list(confirmed_factors_dict.values())

        score, zone_code, zone_label = calculate_risk_score(confirmed_factor_codes)

        # Update complex risk score in DB
        self.repo.update_complex_risk(complex_id, score, zone_code)

        # Try LLM if key is available
        api_key = self.anthropic_key or self.openai_key
        if api_key:
            llm_result = self._call_llm_explainer(
                complex_info=cplx,
                legal_check=legal_check,
                confirmed_factors=confirmed_factors_list,
                needs_verification=needs_verification,
                score=score,
                zone_code=zone_code,
                zone_label=zone_label,
                valid_evidence_ids=valid_evidence_ids
            )
            if llm_result:
                return {
                    "complex_id": complex_id,
                    "complex": cplx,
                    "legal_basis": legal_check,
                    "risk_score": score,
                    "risk_zone": zone_code,
                    "risk_label": zone_label,
                    "confirmed_factors": confirmed_factors_list,
                    "explanation": llm_result.model_dump(),
                    "source": "llm"
                }

        # Offline / Fallback generator
        fallback_output = generate_fallback_explanation(
            complex_info=cplx,
            legal_check=legal_check,
            confirmed_factors=confirmed_factors_list,
            needs_verification=needs_verification,
            score=score,
            zone_code=zone_code,
            zone_label=zone_label
        )

        return {
            "complex_id": complex_id,
            "complex": cplx,
            "legal_basis": legal_check,
            "risk_score": score,
            "risk_zone": zone_code,
            "risk_label": zone_label,
            "confirmed_factors": confirmed_factors_list,
            "explanation": fallback_output.model_dump(),
            "source": "rules"
        }

    def _call_llm_explainer(
        self,
        complex_info: Dict[str, Any],
        legal_check: Dict[str, Any],
        confirmed_factors: List[Dict[str, Any]],
        needs_verification: List[str],
        score: int,
        zone_code: str,
        zone_label: str,
        valid_evidence_ids: set
    ) -> Optional[RiskExplanationOutput]:
        """Calls Anthropic Claude with strict prompt, validation, 1 retry and llm_logs."""
        try:
            import anthropic
        except ImportError:
            return None

        if not self.anthropic_key:
            return None

        client = anthropic.Anthropic(api_key=self.anthropic_key)
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

        prompt_data = {
            "complex": complex_info,
            "legal_basis_check": legal_check,
            "confirmed_factors": confirmed_factors,
            "needs_verification": needs_verification,
            "total_score": score,
            "risk_zone": zone_code,
            "risk_label": zone_label,
            "valid_evidence_ids": list(valid_evidence_ids)
        }

        system_prompt = """
Ты — Агент-объяснитель риска в системе 'SAQ QURYLYS' для аналитика МИО.
Напиши краткое объяснение на русском языке (3–6 предложений) для аналитика МИО и верни JSON строго по следующей Pydantic-схеме:

{
  "summary": "Краткое текстовое объяснение на русском (3-6 предложений)",
  "factor_explanations": [
    {
      "code": "R2",
      "points": 25,
      "text": "Объяснение фактора",
      "evidence_ids": ["id1"]
    }
  ],
  "needs_verification": ["Что именно и где проверить"],
  "disclaimer": "Оценка риска — не юридическое заключение."
}

ЖЁСТКИЕ ОГРАНИЧЕНИЯ:
1. Запрещены формулировки: 'незаконно', 'мошенничество', 'нарушил закон', 'преступление', 'негативный вердикт'. Используй только: 'обнаружены признаки риска', 'требуется проверка аналитиком'.
2. Только пересказ переданных фактов. Новые факты, суммы, законы не добавлять.
3. В evidence_ids передавай ТОЛЬКО ссылки из списка valid_evidence_ids.
4. Объясни правовой статус (R1) и укажи, что статус 'не проверено' не является нарушением закона.
"""

        prompt = f"{system_prompt}\n\nВходные данные:\n{json.dumps(prompt_data, ensure_ascii=False, indent=2)}"

        for attempt in range(2):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw_text = response.content[0].text

                # Extract JSON
                json_str = raw_text
                if "```json" in raw_text:
                    json_str = raw_text.split("```json")[1].split("```")[0]
                elif "```" in raw_text:
                    json_str = raw_text.split("```")[1].split("```")[0]

                parsed_dict = json.loads(json_str.strip())
                output = RiskExplanationOutput(**parsed_dict)

                # Validation 1: Forbidden words
                matched_forbidden = contains_forbidden_words(output.summary)
                if matched_forbidden:
                    self.repo.save_llm_log(
                        agent="explainer", model=model, prompt=prompt, response=raw_text,
                        validation_result=f"failed_forbidden_word: {matched_forbidden}"
                    )
                    prompt += f"\n\nОШИБКА: Обнаружено запрещённое слово '{matched_forbidden}'. Нарушены правила. Повтори ответ строго без запрещённых слов!"
                    continue

                # Validation 2: Evidence IDs
                if not validate_evidence_ids(output, valid_evidence_ids):
                    self.repo.save_llm_log(
                        agent="explainer", model=model, prompt=prompt, response=raw_text,
                        validation_result="failed_invalid_evidence_ids"
                    )
                    prompt += "\n\nОШИБКА: Указан несуществующий evidence_id. Разрешены только ID из списка valid_evidence_ids."
                    continue

                # Success
                self.repo.save_llm_log(
                    agent="explainer", model=model, prompt=prompt, response=raw_text,
                    validation_result="success"
                )
                return output

            except Exception as e:
                self.repo.save_llm_log(
                    agent="explainer", model=model, prompt=prompt, response=str(e),
                    validation_result=f"exception_attempt_{attempt+1}: {str(e)}"
                )
                prompt += f"\n\nОШИБКА валидации JSON: {str(e)}. Ответь строго валидным JSON!"

        return None
