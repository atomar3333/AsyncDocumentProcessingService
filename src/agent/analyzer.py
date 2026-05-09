import json

from google import genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import settings
from src.models.enums import AnalysisType
from src.agent.prompts import SYSTEM_PROMPT, SUMMARY_PROMPT, EXTRACTION_PROMPT, CLASSIFICATION_PROMPT
from src.agent.schemas import SummaryResult, ExtractionResult, ClassificationResult
from src.agent.fetcher import FetchedDocument
from src.logging import get_logger

logger = get_logger(__name__)

PROMPT_MAP = {
    AnalysisType.summary: SUMMARY_PROMPT,
    AnalysisType.extraction: EXTRACTION_PROMPT,
    AnalysisType.classification: CLASSIFICATION_PROMPT,
}

SCHEMA_MAP = {
    AnalysisType.summary: SummaryResult,
    AnalysisType.extraction: ExtractionResult,
    AnalysisType.classification: ClassificationResult,
}

class TokenBudgetExceeded(Exception):
    pass


class AnalysisError(Exception):
    pass


async def call_llm(doc: FetchedDocument, analysis_type: AnalysisType, token_budget: int) -> tuple:
    """Call Gemini API with document file. Returns (parsed_result, token_usage)."""
    return await _call_gemini(doc, analysis_type, token_budget)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    before_sleep=lambda retry_state: logger.warning(
        "llm_retry", attempt=retry_state.attempt_number, error=str(retry_state.outcome.exception())
    ),
)
async def _call_gemini(doc: FetchedDocument, analysis_type: AnalysisType, token_budget: int) -> tuple:
    client = genai.Client(api_key=settings.gemini_api_key)
    prompt_text = SYSTEM_PROMPT + "\n\n" + PROMPT_MAP[analysis_type]
    uploaded_file = None

    try:
        # Upload document to Gemini File API
        uploaded_file = client.files.upload(file=doc.file_path)
        logger.info("gemini_file_uploaded", file_name=uploaded_file.name)

        # Generate content with the uploaded file
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt_text, uploaded_file],
        )

        # Extract token usage from response
        usage_meta = getattr(response, "usage_metadata", None)
        usage = {
            "input_tokens": getattr(usage_meta, "prompt_token_count", 0) if usage_meta else 0,
            "output_tokens": getattr(usage_meta, "candidates_token_count", 0) if usage_meta else 0,
        }
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]

        if usage["total_tokens"] > token_budget:
            raise TokenBudgetExceeded(f"Used {usage['total_tokens']} tokens, budget was {token_budget}")

        raw_text = response.text

        # Parse JSON from response (handle markdown code blocks)
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0]
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0]

        parsed = json.loads(raw_text.strip())
        return parsed, usage

    finally:
        # Cleanup remote file
        if uploaded_file:
            try:
                client.files.delete(name=uploaded_file.name)
                logger.info("gemini_file_deleted", file_name=uploaded_file.name)
            except Exception:
                pass


def validate_result(result: dict, analysis_type: AnalysisType, min_confidence: float) -> dict:
    """Validate result against Pydantic schema. Returns validated dict or raises."""
    schema_class = SCHEMA_MAP[analysis_type]
    validated = schema_class.model_validate(result)

    if analysis_type == AnalysisType.summary and validated.overall_confidence < min_confidence:
        raise AnalysisError(f"Summary confidence {validated.overall_confidence} below threshold {min_confidence}")
    elif analysis_type == AnalysisType.classification and validated.confidence < min_confidence:
        raise AnalysisError(f"Classification confidence {validated.confidence} below threshold {min_confidence}")

    return validated.model_dump()
