"""
tests/test_schemas.py - Unit tests for Phase 1 Pydantic models.

Ensures that:
1. Category scores cannot exceed their weight caps.
2. The model validator recalculates and reconciles overall_score if the LLM's arithmetic is off.
3. MissingSkill importance only accepts 'high', 'medium', or 'low'.
"""

import pytest
from pydantic import ValidationError
from models.schemas import CategoryScores, MissingSkill, Suggestion, AnalysisResult


def test_category_scores_valid():
    """Test valid category scores within defined boundaries."""
    scores = CategoryScores(
        skills_match=35.0,
        experience_relevance=20.0,
        keywords_ats=15.0,
        education_and_projects=10.0
    )
    assert scores.total == 80.0


def test_category_scores_boundary_exceeded():
    """Test that exceeding the max weight throws a ValidationError."""
    with pytest.raises(ValidationError):
        # Max for skills_match is 40.0
        CategoryScores(
            skills_match=45.0,
            experience_relevance=20.0,
            keywords_ats=15.0,
            education_and_projects=10.0
        )


def test_missing_skill_invalid_importance():
    """Test that invalid importance enum throws ValidationError."""
    with pytest.raises(ValidationError):
        MissingSkill(skill="Docker", importance="critical")  # only high/medium/low allowed


def test_overall_score_reconciliation():
    """
    Test defensive check: if overall_score is inconsistent with the sum
    of category scores, it must be automatically corrected to equal the sum.
    """
    scores = CategoryScores(
        skills_match=30.0,
        experience_relevance=20.0,
        keywords_ats=15.0,
        education_and_projects=10.0
    )
    # Total sum is 75, but LLM mistakenly gave 60
    result = AnalysisResult(
        overall_score=60,
        category_scores=scores,
        matched_skills=["Python", "SQL"],
        missing_skills=[MissingSkill(skill="Docker", importance="high")],
        strengths=["Strong fundamentals", "Clear project experience", "Good communicator"],
        suggestions=[
            Suggestion(section="Skills", suggestion="Add Docker to your skills list"),
            Suggestion(section="Experience", suggestion="Quantify achievements in project 1")
        ],
        one_line_summary="Promising junior candidate with strong Python foundations."
    )
    # The validator must have corrected overall_score to 75
    assert result.overall_score == 75
