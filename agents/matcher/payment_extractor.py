import os
import re
import json
import base64
import logging
from typing import Optional, Literal
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

PaymentType = Literal["бронь", "депозит", "задаток", "первоначальный_взнос", "иное", "нет"]
CurrencyType = Literal["KZT", "USD", "null"]

class PaymentExtractorResult(BaseModel):
    offers_payment: bool
    payment_type: PaymentType
    amount: Optional[float] = None
    currency: Optional[str] = "KZT"
    evidence_quote: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_short: str = ""
    source: str = "llm"  # "llm" or "rules"

def normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text or "").strip().lower()

def validate_quote(quote: str, source_text: str) -> bool:
    if not quote or not quote.strip():
        return False
    norm_quote = normalize_text(quote)
    norm_text = normalize_text(source_text)
    return norm_quote in norm_text

def extract_payment_rules(text: str) -> PaymentExtractorResult:
    """
    Deterministic rule/regex fallback extractor for payment terms.
    Source: 'rules'
    """
    norm_text = normalize_text(text)

    keywords_map = [
        (r'первоначальн|первый взнос|гарантийный взнос|регистрационный взнос', "первоначальный_взнос"),
        (r'депозит', "депозит"),
        (r'задаток', "задаток"),
        (r'брон', "бронь"),
        (r'взнос|предоплат|закреп|аванс|резерв|оплат|деньги', "иное"),
    ]

    found_type: Optional[PaymentType] = None
    matched_keyword = None

    for pattern, p_type in keywords_map:
        match = re.search(pattern, norm_text)
        if match:
            found_type = p_type
            matched_keyword = match.group(0)
            break

    if not found_type:
        return PaymentExtractorResult(
            offers_payment=False,
            payment_type="нет",
            amount=None,
            currency=None,
            evidence_quote="",
            confidence=0.95,
            reasoning_short="Признаков требования внести платеж не обнаружено.",
            source="rules"
        )

    # Extract sentence containing matched keyword as quote
    sentences = re.split(r'[.!?\n]', text)
    quote = ""
    for sentence in sentences:
        if matched_keyword and matched_keyword in normalize_text(sentence):
            quote = sentence.strip()
            break

    if not quote:
        quote = text[:150].strip()

    # Amount extraction
    amount = None
    currency = "KZT"

    # Match numbers like '500 000', '1 000 000', '300 тыс', '200000', '5%'
    num_match = re.search(r'(\d[\d\s\.]*)\s*(тыс|млн|тг|тенге|kzt|usd|\$|%)?', norm_text)
    if num_match:
        raw_num = num_match.group(1).replace(' ', '').replace('.', '')
        unit = num_match.group(2) or ""
        try:
            val = float(raw_num)
            if 'тыс' in unit:
                val *= 1000
            elif 'млн' in unit:
                val *= 1000000
            if val > 0:
                amount = val
            if 'usd' in unit or '$' in unit:
                currency = "USD"
        except ValueError:
            amount = None

    return PaymentExtractorResult(
        offers_payment=True,
        payment_type=found_type,
        amount=amount,
        currency=currency,
        evidence_quote=quote,
        confidence=0.85,
        reasoning_short=f"Обнаружено прямое предложение платежа ({found_type}) по ключевым словам.",
        source="rules"
    )

class PaymentExtractor:
    def __init__(self, repo=None):
        self.repo = repo
        self.api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("ANTHROPIC_MODEL") or os.getenv("LLM_MODEL") or "claude-3-5-sonnet-20241022"

    def process(self, text: str, image_path: Optional[str] = None) -> PaymentExtractorResult:
        if not self.api_key:
            logger.info("No API key found. Using rule-based payment extractor.")
            res = extract_payment_rules(text)
            return self._post_validate(res, text)

        res = self._call_llm(text, image_path)
        if res is None:
            logger.warning("LLM extraction failed after retry. Falling back to rules.")
            res = extract_payment_rules(text)

        return self._post_validate(res, text)

    def _call_llm(self, text: str, image_path: Optional[str] = None) -> Optional[PaymentExtractorResult]:
        prompt_text = f"""
Проанализируй текст объявления о недвижимости на предмет предложения внести деньги (бронь, депозит, задаток, первоначальный взнос, аванс) ДО проверки юридических документов.

Верни строго JSON со следующей структурой без markdown тэгов или текста вне JSON:
{{
  "offers_payment": boolean,
  "payment_type": "бронь" | "депозит" | "задаток" | "первоначальный_взнос" | "иное" | "нет",
  "amount": число или null,
  "currency": "KZT" | "USD" | null,
  "evidence_quote": "дословный фрагмент текста, подтверждающий вывод",
  "confidence": число от 0.0 до 1.0,
  "reasoning_short": "краткое объяснение в 1 предложение"
}}

ТЕКСТ ОБЪЯВЛЕНИЯ:
{text}
"""
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        for attempt in range(2):
            try:
                content_list = []
                if image_path and os.path.exists(image_path) and attempt == 0:
                    try:
                        with open(image_path, "rb") as img_f:
                            img_data = base64.b64encode(img_f.read()).decode("utf-8")
                            ext = os.path.splitext(image_path)[1].lower()
                            media_type = "image/png" if ext == ".png" else "image/jpeg"
                            content_list.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": img_data
                                }
                            })
                    except Exception as e:
                        logger.warning(f"Failed to read image {image_path}: {e}")

                content_list.append({"type": "text", "text": prompt_text})

                message = client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": content_list}]
                )

                raw_resp = message.content[0].text.strip()
                clean_json = re.sub(r'^```(json)?|```$', '', raw_resp, flags=re.MULTILINE).strip()
                data = json.loads(clean_json)

                result = PaymentExtractorResult(
                    offers_payment=data["offers_payment"],
                    payment_type=data["payment_type"],
                    amount=data.get("amount"),
                    currency=data.get("currency"),
                    evidence_quote=data.get("evidence_quote", ""),
                    confidence=float(data.get("confidence", 0.8)),
                    reasoning_short=data.get("reasoning_short", ""),
                    source="llm"
                )

                if self.repo:
                    self.repo.save_llm_log(
                        agent="payment_extractor",
                        model=self.model,
                        prompt=prompt_text,
                        response=raw_resp,
                        validation_result="success"
                    )

                return result

            except Exception as e:
                logger.warning(f"PaymentExtractor LLM attempt {attempt + 1} failed: {e}")
                if self.repo:
                    self.repo.save_llm_log(
                        agent="payment_extractor",
                        model=self.model,
                        prompt=prompt_text,
                        response=str(e),
                        validation_result=f"retry_{attempt + 1}" if attempt == 0 else "fallback_error"
                    )
                if attempt == 0:
                    prompt_text += "\nВНИМАНИЕ: Предыдущий ответ был невалидным JSON. Верни СТРОГО JSON!"

        return None

    def _post_validate(self, result: PaymentExtractorResult, source_text: str) -> PaymentExtractorResult:
        if result.offers_payment:
            if not validate_quote(result.evidence_quote, source_text):
                logger.warning(f"Invalid quote '{result.evidence_quote}' not found in source text. Discarding hypothesis.")
                result.offers_payment = False
                result.payment_type = "нет"
                result.amount = None
                result.evidence_quote = ""
                result.confidence = 0.0
                result.reasoning_short = "Цитата-основание не найдена в исходном тексте объявления (гипотеза отброшена)."

        return result
