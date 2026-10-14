"""
models/schemas.py - Pydantic models for structured validation.

WHY PYDANTIC?
1. LLM Guardrails: Generative AI outputs are inherently probabilistic text. 
   Pydantic enforces strict type checking and validation rules. If Gemini omits a field
   or returns an unexpected type, Pydantic immediately catches it.
2. Structured Outputs: The official google-genai SDK can use Pydantic models directly 
   as the 'response_schema', forcing Gemini to return JSON that matches this structure.
"""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class CategoryScores(BaseModel):
    """
    Breakdown of scores by category.
    Each category has a maximum weight defined in the requirements.
    Total maximum possible across all categories is 100.
    """
    skills_match: float = Field(
        ...,
        ge=0.0,
        le=40.0,
        description="Assessment of hard and soft technical skills match (Max 40 points)"
    )
    experience_relevance: float = Field(
        ...,
        ge=0.0,
        le=25.0,
        description="Relevance and depth of professional/internship experience (Max 25 points)"
    )
    keywords_ats: float = Field(
        ...,
        ge=0.0,
        le=20.0,
        description="ATS keywords density and phrasing alignment (Max 20 points)"
    )
    education_and_projects: float = Field(
        ...,
        ge=0.0,
        le=15.0,
        description="Relevance of degrees, certifications, and portfolio projects (Max 15 points)"
    )

    @property
    def total(self) -> float:
        """Helper to get exact mathematical sum of category scores."""
        return (
            self.skills_match +
            self.experience_relevance +
            self.keywords_ats +
            self.education_and_projects
        )


class MissingSkill(BaseModel):
    """Represents a single missing skill and how critical it is."""
    skill: str = Field(..., description="Name of the missing skill or tool")
    importance: Literal["high", "medium", "low"] = Field(
        ...,
        description="Priority of the skill: 'high' for must-have requirements, 'medium' for preferred, 'low' for nice-to-have"
    )


class Suggestion(BaseModel):
    """An actionable critique tied to a specific resume section."""
    section: str = Field(..., description="Target section (e.g., 'Work Experience', 'Skills', 'Projects', 'Summary')")
    suggestion: str = Field(..., description="Clear, actionable recommendation on how to improve this section")


class AnalysisResult(BaseModel):
    """
    The complete analysis payload returned by the Gemini AI engine.
    """
    overall_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Overall match score from 0 to 100. Must equal sum of category_scores."
    )
    category_scores: CategoryScores = Field(
        ...,
        description="Detailed score breakdown across the 4 key evaluation categories."
    )
    matched_skills: list[str] = Field(
        ...,
        description="List of skills and qualifications found in both resume and job description."
    )
    missing_skills: list[MissingSkill] = Field(
        ...,
        description="List of skills required or preferred by job description that are missing from the resume."
    )
    strengths: list[str] = Field(
        ...,
        min_length=1,
        description="3 to 5 key strong points where the candidate excels for this role."
    )
    suggestions: list[Suggestion] = Field(
        ...,
        min_length=1,
        description="5 to 8 specific, actionable suggestions to improve the resume."
    )
    one_line_summary: str = Field(
        ...,
        description="A concise 1-sentence executive summary of the candidate's fit."
    )

    @model_validator(mode="after")
    def reconcile_overall_score(self) -> "AnalysisResult":
        """
        DEFENSIVE CHECK:
        Requirement: The overall score must equal the sum of category scores.
        LLMs are known to occasionally make simple arithmetic mistakes.
        If the overall_score does not match the rounded sum of category_scores,
        we automatically recalculate and correct it in code.
        """
        calculated_sum = round(self.category_scores.total)
        # Ensure within 0-100 range
        clamped_sum = max(0, min(100, calculated_sum))
        if self.overall_score != clamped_sum:
            self.overall_score = clamped_sum
        return self


class AnalysisRecord(BaseModel):
    """
    Schema for persisting and retrieving analysis records from database storage.
    Adds metadata (id, timestamp, job title, etc.) on top of AnalysisResult.
    """
    id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    job_title: str
    resume_source: str  # filename or "[Pasted Text]"
    result: AnalysisResult
