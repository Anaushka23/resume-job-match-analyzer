"""
tests/test_analyzer.py - Tests for input validation and Gemini retry logic.

WHY MOCK THE GEMINI CLIENT?
We should NEVER call a real external API in automated tests because:
  1. Tests would be slow (30-60 seconds each).
  2. Tests would cost real money (API credits).
  3. Tests would fail when offline or when API keys aren't set.
  4. Results would be non-deterministic.

Instead, we mock google.genai.Client and control exactly what it returns,
making tests instant, free, offline-capable, and deterministic.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from services.analyzer import validate_inputs, analyze, AnalysisError
from models.schemas import AnalysisResult, CategoryScores, MissingSkill, Suggestion
import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_RESUME = (
    "Jane Smith — Python Developer\n"
    "Skills: Python, Django, REST APIs, PostgreSQL, Docker\n"
    "Experience: 2 years at Infosys building backend APIs.\n"
    "Education: B.Tech Computer Science, VTU 2022.\n"
    "Projects: Open-source Flask logging library, 200+ GitHub stars."
)

VALID_JOB = (
    "We need a Python Backend Developer with Django, SQL, and REST API experience. "
    "Preferred: Docker, AWS. Minimum 1 year experience. B.Tech required."
)


def make_fake_analysis_result() -> AnalysisResult:
    """Returns a hardcoded AnalysisResult that mimics a real Gemini response."""
    return AnalysisResult(
        overall_score=74,
        category_scores=CategoryScores(
            skills_match=30.0,
            experience_relevance=18.0,
            keywords_ats=14.0,
            education_and_projects=12.0,
        ),
        matched_skills=["Python", "Django", "REST APIs", "PostgreSQL"],
        missing_skills=[MissingSkill(skill="AWS", importance="medium")],
        strengths=["Strong Python core", "Relevant experience", "Relevant degree"],
        suggestions=[
            Suggestion(section="Work Experience", suggestion="Quantify achievements"),
            Suggestion(section="Skills", suggestion="Add AWS to skills"),
        ],
        one_line_summary="Good match with minor gaps in cloud tooling.",
    )


# ---------------------------------------------------------------------------
# validate_inputs() tests
# ---------------------------------------------------------------------------

class TestValidateInputs:
    """Tests for the input length validation function."""

    def test_valid_inputs_pass(self):
        ok, msg = validate_inputs(VALID_RESUME, VALID_JOB)
        assert ok is True
        assert msg == ""

    def test_resume_too_short(self):
        ok, msg = validate_inputs("Too short", VALID_JOB)
        assert ok is False
        assert "resume" in msg.lower()
        assert str(config.MIN_RESUME_CHARS) in msg

    def test_job_too_short(self):
        ok, msg = validate_inputs(VALID_RESUME, "Short")
        assert ok is False
        assert "job description" in msg.lower()

    def test_resume_too_long(self):
        huge_resume = "A" * (config.MAX_TEXT_CHARS + 1)
        ok, msg = validate_inputs(huge_resume, VALID_JOB)
        assert ok is False
        assert "too long" in msg.lower()

    def test_job_too_long(self):
        huge_job = "B" * (config.MAX_TEXT_CHARS + 1)
        ok, msg = validate_inputs(VALID_RESUME, huge_job)
        assert ok is False
        assert "too long" in msg.lower()

    def test_empty_strings_are_too_short(self):
        ok, msg = validate_inputs("", VALID_JOB)
        assert ok is False


# ---------------------------------------------------------------------------
# analyze() tests — Gemini API mocked
# ---------------------------------------------------------------------------

def make_mock_gemini_response(result: AnalysisResult) -> MagicMock:
    """
    Creates a mock that makes client.models.generate_content() return
    a fake response object whose .text attribute holds the JSON string.
    """
    fake_response = MagicMock()
    # Pydantic's model_dump() → JSON string (what Gemini's .text field contains)
    fake_response.text = json.dumps(result.model_dump())

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = fake_response

    return mock_client


class TestAnalyze:
    """Tests for the main analyze() function with mocked Gemini calls."""

    def test_successful_analysis(self):
        """
        Happy path: Gemini returns valid JSON, Pydantic validates it,
        and analyze() returns a correct AnalysisResult.
        """
        expected = make_fake_analysis_result()
        mock_client = make_mock_gemini_response(expected)

        # Patch the Client class so that genai.Client(...) returns our mock
        with patch("services.analyzer.genai.Client", return_value=mock_client):
            result = analyze(VALID_RESUME, VALID_JOB)

        assert result.overall_score == 74
        assert "Python" in result.matched_skills
        assert len(result.suggestions) >= 1

    def test_raises_value_error_on_bad_input(self):
        """
        analyze() must raise ValueError (not crash) when inputs are too short.
        The error should happen BEFORE the Gemini API is ever called.
        """
        with patch("services.analyzer.genai.Client") as mock_client_cls:
            with pytest.raises(ValueError):
                analyze("Hi", VALID_JOB)
            # Gemini must NOT have been called
            mock_client_cls.assert_not_called()

    def test_retries_on_api_failure_then_succeeds(self):
        """
        Retry logic: first call raises an exception, second call succeeds.
        analyze() should succeed overall (not raise AnalysisError).

        This directly tests that our retry loop works correctly.
        """
        expected = make_fake_analysis_result()
        fake_response = MagicMock()
        fake_response.text = json.dumps(expected.model_dump())

        mock_client = MagicMock()
        # First call raises an error; second call returns the valid response
        mock_client.models.generate_content.side_effect = [
            Exception("Temporary network error"),
            fake_response,
        ]

        with patch("services.analyzer.genai.Client", return_value=mock_client):
            with patch("services.analyzer.time.sleep"):  # skip real sleep in tests
                result = analyze(VALID_RESUME, VALID_JOB)

        assert result.overall_score == 74
        assert mock_client.models.generate_content.call_count == 2

    def test_raises_analysis_error_after_all_retries_exhausted(self):
        """
        All 3 attempts fail → analyze() must raise AnalysisError with 
        a friendly message, not a raw Python exception.
        """
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API down")

        with patch("services.analyzer.genai.Client", return_value=mock_client):
            with patch("services.analyzer.time.sleep"):
                with pytest.raises(AnalysisError) as exc_info:
                    analyze(VALID_RESUME, VALID_JOB)

        assert "could not be completed" in str(exc_info.value).lower()

    def test_score_reconciliation_via_pydantic(self):
        """
        If Gemini returns an overall_score that doesn't match the category sum,
        the Pydantic @model_validator must correct it automatically.

        Here we craft a response where overall_score=99 but categories sum to 74.
        After Pydantic validation, overall_score should be corrected to 74.
        """
        tampered = make_fake_analysis_result()
        # Manually corrupt the overall_score (simulating a Gemini arithmetic mistake)
        raw_dict = tampered.model_dump()
        raw_dict["overall_score"] = 99  # wrong! categories sum to 74

        fake_response = MagicMock()
        fake_response.text = json.dumps(raw_dict)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response

        with patch("services.analyzer.genai.Client", return_value=mock_client):
            result = analyze(VALID_RESUME, VALID_JOB)

        # The validator must have corrected 99 → 74
        assert result.overall_score == 74
