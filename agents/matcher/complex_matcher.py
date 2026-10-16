import os
import re
import json
import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from agents.matcher.tools import MatcherTools, normalize_text, validate_quote
from database.repository import AdRepository

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.75
MARGIN_THRESHOLD = 0.15

class ComplexCandidate(BaseModel):
    complex_id: str
    complex_name: str
    developer_id: Optional[str] = None
    developer_name: Optional[str] = None
    confidence: float
    matched_signals: List[str] = Field(default_factory=list) # "название", "адрес", "застройщик", "телефон", "район"
    evidence_quotes: List[str] = Field(default_factory=list)

class ComplexMatchResult(BaseModel):
    candidates: List[ComplexCandidate] = Field(default_factory=list)
    auto_linked: bool = False
    top_candidate_id: Optional[str] = None
    status: str = "Нужна проверка"
    reasoning: str = ""
    source: str = "llm" # "llm" or "rules"

def match_complexes_fallback(text: str, repo: AdRepository) -> ComplexMatchResult:
    """
    Deterministic fallback matcher using rapidfuzz and signal extraction against DB complexes.
    Source: 'rules'
    """
    complexes = repo.get_complexes()
    norm_text = normalize_text(text)

    scored_candidates = []

    for cplx in complexes:
        c_id = cplx["id"]
        c_name = cplx["name"]
        d_id = cplx["developer_id"]
        d_name = cplx.get("developer_name") or ""
        address = cplx.get("address") or ""
        district = cplx.get("district") or ""
        city = cplx.get("city") or ""

        # Clean complex name without 'ЖК' prefix
        clean_name = re.sub(r'^(жк|жилой комплекс)\s+', '', c_name, flags=re.IGNORECASE).strip()
        norm_clean_name = normalize_text(clean_name)
        norm_full_name = normalize_text(c_name)

        matched_signals = []
        evidence_quotes = []
        score = 0.0

        # Signal 1: Name match
        if norm_full_name and norm_full_name in norm_text:
            matched_signals.append("название")
            score += 0.80
            for line in text.splitlines():
                if norm_clean_name in normalize_text(line):
                    evidence_quotes.append(line.strip())
                    break
        elif norm_clean_name and norm_clean_name in norm_text:
            matched_signals.append("название")
            score += 0.75
            for line in text.splitlines():
                if norm_clean_name in normalize_text(line):
                    evidence_quotes.append(line.strip())
                    break
        else:
            sim = fuzz.partial_ratio(norm_clean_name, norm_text) if norm_clean_name else 0
            if sim > 80:
                matched_signals.append("название")
                score += 0.45

        # Signal 2: Developer match
        if d_name:
            clean_d_name = re.sub(r'^(тоо|ао|ип)\s+', '', d_name, flags=re.IGNORECASE).strip()
            norm_d_name = normalize_text(clean_d_name)
            if norm_d_name and norm_d_name in norm_text:
                matched_signals.append("застройщик")
                score += 0.15

        # Signal 3: Address match
        norm_addr = normalize_text(address)
        if norm_addr and norm_addr in norm_text:
            matched_signals.append("адрес")
            score += 0.15

        # Signal 4: District / City match
        norm_dist = normalize_text(district)
        norm_city = normalize_text(city)
        if (norm_dist and norm_dist in norm_text) or (norm_city and norm_city in norm_text):
            matched_signals.append("район")
            score += 0.10

        confidence = min(0.98, score)

        if confidence > 0.2:
            candidate = ComplexCandidate(
                complex_id=c_id,
                complex_name=c_name,
                developer_id=d_id,
                developer_name=d_name,
                confidence=round(confidence, 2),
                matched_signals=matched_signals,
                evidence_quotes=evidence_quotes
            )
            scored_candidates.append(candidate)

    # Sort candidates by confidence descending
    scored_candidates.sort(key=lambda x: x.confidence, reverse=True)
    top_candidates = scored_candidates[:3]

    return evaluate_linking_thresholds(top_candidates, source="rules")

def evaluate_linking_thresholds(candidates: List[ComplexCandidate], source: str = "rules") -> ComplexMatchResult:
    """
    Applies rule: Auto-linking ONLY if top-1 confidence >= 0.75 AND margin over top-2 >= 0.15.
    Otherwise status is 'Нужна проверка'.
    """
    if not candidates:
        return ComplexMatchResult(
            candidates=[],
            auto_linked=False,
            top_candidate_id=None,
            status="Нужна проверка",
            reasoning="Кандидаты для привязки к ЖК не найдены.",
            source=source
        )

    top1 = candidates[0]
    top2_conf = candidates[1].confidence if len(candidates) > 1 else 0.0
    margin = round(top1.confidence - top2_conf, 2)

    if top1.confidence >= CONFIDENCE_THRESHOLD and margin >= MARGIN_THRESHOLD:
        return ComplexMatchResult(
            candidates=candidates,
            auto_linked=True,
            top_candidate_id=top1.complex_id,
            status="linked",
            reasoning=f"Автоматическая привязка: высокая уверенность {top1.confidence:.2f} (отрыв {margin:.2f}).",
            source=source
        )
    else:
        return ComplexMatchResult(
            candidates=candidates,
            auto_linked=False,
            top_candidate_id=top1.complex_id,
            status="Нужна проверка",
            reasoning=f"Требуется выбор аналитиком (уверенность {top1.confidence:.2f}, отрыв от 2-го {margin:.2f}).",
            source=source
        )

class ComplexMatcher:
    def __init__(self, repo: AdRepository):
        self.repo = repo
        self.tools = MatcherTools(repo)
        self.api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("ANTHROPIC_MODEL") or os.getenv("LLM_MODEL") or "claude-3-5-sonnet-20241022"

    def process(self, ad_id: str, text: str, account: Optional[str] = None) -> ComplexMatchResult:
        """
        Executes complex matching via tool-use agent loop or fallback matcher.
        """
        if not self.api_key:
            logger.info("No LLM API key. Executing fallback complex matcher.")
            return match_complexes_fallback(text, self.repo)

        try:
            res = self._run_agent_loop(ad_id, text, account)
            if res:
                return res
        except Exception as e:
            logger.warning(f"ComplexMatcher agent loop error: {e}. Executing fallback.")

        return match_complexes_fallback(text, self.repo)

    def _run_agent_loop(self, ad_id: str, text: str, account: Optional[str] = None) -> Optional[ComplexMatchResult]:
        """
        Agentic loop with tools (find_residential_complex, get_developer, list_ads_by_phone, get_complex).
        Max steps: 5
        """
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        tools_schema = [
            {
                "name": "find_residential_complex",
                "description": "Поиск ЖК по названию, адресу, району или застройщику в базе данных.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Поисковый запрос (например 'Алатау' или 'Абая')"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_developer",
                "description": "Получение информации о застройщике по БИН или названию.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "bin_or_name": {"type": "string", "description": "БИН или наименование застройщика"}
                    },
                    "required": ["bin_or_name"]
                }
            },
            {
                "name": "list_ads_by_phone",
                "description": "Получение других объявлений с тем же контактом или аккаунтом.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "phone_hash_or_account": {"type": "string", "description": "Аккаунт или хэш телефона"}
                    },
                    "required": ["phone_hash_or_account"]
                }
            },
            {
                "name": "get_complex",
                "description": "Получение информации о ЖК по его ID.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "ID ЖК в базе данных"}
                    },
                    "required": ["id"]
                }
            }
        ]

        system_prompt = """
Ты — Агент 2 (Сопоставитель ЖК и застройщиков).
Твоя задача — сопоставить публикацию объявления с конкретным Жилым Комплексом (ЖК) и застройщиком в реестре.
Используй доступные инструменты для поиска информации в реестре.
Верни результат в виде до 3 кандидатов ЖК в строго JSON формате.
"""

        messages = [
            {"role": "user", "content": f"Найди ЖК и застройщика для публикации:\nАккаунт: {account}\nТекст: {text}"}
        ]

        max_steps = 5

        for step in range(max_steps):
            response = client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=system_prompt,
                tools=tools_schema,
                messages=messages
            )

            if response.stop_reason == "tool_use":
                assistant_message_content = response.content
                messages.append({"role": "assistant", "content": assistant_message_content})

                tool_use_results = []
                for block in assistant_message_content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_args = block.input
                        tool_use_id = block.id

                        # Execute tool
                        res_content = ""
                        if tool_name == "find_residential_complex":
                            c_list = self.tools.find_residential_complex(tool_args.get("query", ""))
                            res_content = json.dumps(c_list, ensure_ascii=False)
                        elif tool_name == "get_developer":
                            dev = self.tools.get_developer(tool_args.get("bin_or_name", ""))
                            res_content = json.dumps(dev, ensure_ascii=False)
                        elif tool_name == "list_ads_by_phone":
                            ads_list = self.tools.list_ads_by_phone(tool_args.get("phone_hash_or_account", ""))
                            res_content = json.dumps(ads_list, ensure_ascii=False)
                        elif tool_name == "get_complex":
                            c_info = self.tools.get_complex(tool_args.get("id", ""))
                            res_content = json.dumps(c_info, ensure_ascii=False)

                        tool_use_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": res_content
                        })

                messages.append({"role": "user", "content": tool_use_results})

            else:
                raw_text = response.content[0].text
                clean_json = re.sub(r'^```(json)?|```$', '', raw_text, flags=re.MULTILINE).strip()
                try:
                    data = json.loads(clean_json)
                    raw_candidates = data.get("candidates", [])
                    candidates = []
                    for c in raw_candidates:
                        candidates.append(ComplexCandidate(
                            complex_id=c["complex_id"],
                            complex_name=c["complex_name"],
                            developer_id=c.get("developer_id"),
                            developer_name=c.get("developer_name"),
                            confidence=float(c.get("confidence", 0.5)),
                            matched_signals=c.get("matched_signals", []),
                            evidence_quotes=c.get("evidence_quotes", [])
                        ))
                    return evaluate_linking_thresholds(candidates, source="llm")
                except Exception as parse_err:
                    logger.warning(f"Failed to parse agent final JSON: {parse_err}")
                    return None

        return None
