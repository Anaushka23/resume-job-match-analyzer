"""
services/analyzer.py - The core AI engine. Coordinates everything end-to-end.

RESPONSIBILITIES:
  1. Validate input text (length checks)
  2. Build the prompt using services/prompts.py
  3. Call the Gemini API with structured output enforcement
  4. Retry on transient failures (network, rate limit, invalid JSON)
  5. Deserialize and Pydantic-validate the response
  6. Return a clean AnalysisResult object

WHY NO UI CODE HERE?
This module is 100% pure business logic. It has no Streamlit imports, no 
database calls, and no print statements. That makes it independently 
testable from the command line without ever launching a browser.
"""

import json
import logging
import time

from google import genai
from google.genai import types

import config
from models.schemas import AnalysisResult
from services.prompts import SYSTEM_PROMPT, build_analysis_prompt

logger = logging.getLogger("ResumeAnalyzer.analyzer")

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
MAX_RETRIES = 2          # Total extra attempts beyond the first try
RETRY_DELAY_SECONDS = 3  # Wait time between retries (avoids hammering the API)


class AnalysisError(Exception):
    """
    Raised when analysis fails after all retries or due to unrecoverable errors.
    Keeps the UI layer clean — it just catches AnalysisError and shows a message.
    """
    pass


def validate_inputs(resume_text: str, job_description: str) -> tuple[bool, str]:
    """
    Validates that both input texts meet the minimum and maximum length requirements.

    WHY VALIDATE INPUTS?
    - A 5-character resume is meaningless; the API call would waste money.
    - A 50,000-character document may exceed the model's context window.
    Catching these early gives the user instant feedback before a slow API call.

    Args:
        resume_text: The extracted or pasted resume content.
        job_description: The pasted job listing text.

    Returns:
        A (is_valid: bool, error_message: str) tuple.
        error_message is empty string when is_valid is True.
    """
    if len(resume_text.strip()) < config.MIN_RESUME_CHARS:
        return False, (
            f"Resume text is too short ({len(resume_text.strip())} characters). "
            f"Please provide at least {config.MIN_RESUME_CHARS} characters."
        )
    if len(job_description.strip()) < config.MIN_JOB_DESC_CHARS:
        return False, (
            f"Job description is too short ({len(job_description.strip())} characters). "
            f"Please provide at least {config.MIN_JOB_DESC_CHARS} characters."
        )
    if len(resume_text) > config.MAX_TEXT_CHARS:
        return False, (
            f"Resume is too long ({len(resume_text):,} characters). "
            f"Maximum allowed is {config.MAX_TEXT_CHARS:,} characters. "
            f"Please trim your resume."
        )
    if len(job_description) > config.MAX_TEXT_CHARS:
        return False, (
            f"Job description is too long ({len(job_description):,} characters). "
            f"Maximum allowed is {config.MAX_TEXT_CHARS:,} characters."
        )
    return True, ""


def _call_gemini_with_retry(resume_text: str, job_description: str) -> AnalysisResult:
    """
    Internal function: calls Gemini API and retries on transient errors.

    Uses the google-genai SDK's native structured output feature (response_schema)
    which forces Gemini to return JSON matching our Pydantic model exactly.

    WHY temperature=0?
    Temperature controls how "creative" or random the model's output is.
    At temperature=0, the model becomes deterministic — given the same inputs
    it will always produce the same (or very similar) output. For scoring,
    we want consistency, not creativity.

    WHY response_schema?
    Instead of asking "please return JSON", we hand Gemini our Pydantic class.
    The SDK converts it into a JSON Schema and constrains the model's token
    generation so it is mathematically impossible for it to return invalid JSON
    or omit required fields.

    Args:
        resume_text: Validated resume text.
        job_description: Validated job description text.

    Returns:
        A fully validated AnalysisResult Pydantic object.

    Raises:
        AnalysisError: After MAX_RETRIES failures.
    """
    # Initialise the Gemini client — reads GEMINI_API_KEY from config.
    # The client is created fresh per call (stateless), which is safe and simple.
    client = genai.Client(api_key=config.GEMINI_API_KEY)

    # Build the full prompt text
    user_prompt = build_analysis_prompt(resume_text, job_description)

    last_error = None

    for attempt in range(1, MAX_RETRIES + 2):  # e.g., attempt 1, 2, 3
        try:
            logger.info("Gemini API call — attempt %d of %d", attempt, MAX_RETRIES + 1)

            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    # System prompt sets the AI's persona and rules
                    system_instruction=SYSTEM_PROMPT,
                    # temperature=0 → deterministic, consistent scoring
                    temperature=0.0,
                    # response_schema → forces JSON output matching our Pydantic model.
                    # The SDK translates AnalysisResult into a JSON Schema and
                    # constrains Gemini's output tokens to match it exactly.
                    response_schema=AnalysisResult,
                    # Tells the SDK to return JSON (required when using response_schema)
                    response_mime_type="application/json",
                )
            )

            # The SDK returns the raw JSON text in response.text
            raw_json = response.text
            logger.debug("Raw Gemini response: %s", raw_json[:500])

            # Parse the JSON string into a Python dict, then validate with Pydantic.
            # This is the second layer of validation — the first is Gemini's own
            # schema enforcement. If somehow an invalid value slips through, Pydantic
            # catches it here, and the @model_validator reconciles the score math.
            result_dict = json.loads(raw_json)
            analysis = AnalysisResult(**result_dict)

            logger.info(
                "Analysis complete. Overall score: %d, Category sum: %.1f",
                analysis.overall_score,
                analysis.category_scores.total
            )
            return analysis

        except json.JSONDecodeError as e:
            # The model returned something that isn't valid JSON.
            # This is rare with response_schema but possible on edge cases.
            last_error = f"Gemini returned invalid JSON (attempt {attempt}): {e}"
            logger.warning(last_error)

        except Exception as e:
            # Catches network errors, rate limit errors, timeouts, etc.
            last_error = f"API error on attempt {attempt}: {type(e).__name__}: {e}"
            logger.warning(last_error)

        # If this was not the last attempt, wait before retrying
        if attempt <= MAX_RETRIES:
            logger.info("Waiting %ds before retry...", RETRY_DELAY_SECONDS)
            time.sleep(RETRY_DELAY_SECONDS)

    # All retries exhausted — raise a friendly, non-technical error
    raise AnalysisError(
        "The analysis could not be completed after multiple attempts. "
        "This is usually a temporary issue. Please try again in a moment.\n"
        f"Technical detail: {last_error}"
    )


def analyze(resume_text: str, job_description: str) -> AnalysisResult:
    """
    Public entry point: validates inputs, runs the Gemini analysis, returns result.

    This is the ONLY function that app.py should call from this module.
    Keeping the public API surface small makes the module easy to use and test.

    Args:
        resume_text: Raw text of the candidate's resume.
        job_description: Raw text of the job listing.

    Returns:
        An AnalysisResult Pydantic object with scores, skills, and suggestions.

    Raises:
        ValueError: If the input text fails length validation.
        AnalysisError: If the Gemini API fails after all retries.
    """
    # Step 1: validate inputs before touching the API
    is_valid, error_message = validate_inputs(resume_text, job_description)
    if not is_valid:
        raise ValueError(error_message)

    # Step 2: call Gemini with retry logic
    return _call_gemini_with_retry(resume_text, job_description)
