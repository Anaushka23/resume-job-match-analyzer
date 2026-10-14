"""
tests/test_storage.py - Tests for the SQLite storage layer.

Uses ':memory:' databases (no file written to disk) so tests are:
  - Fast (in-RAM, not on-disk)
  - Isolated (each test gets a fresh database)
  - Side-effect free (nothing left behind on your filesystem)

WHY A PYTEST FIXTURE?
Instead of repeating the storage setup code in every test function, we define
it once as a @pytest.fixture. Pytest automatically calls the fixture and passes
its return value as an argument to any test function that names it.
"""

import pytest
from datetime import datetime

from models.schemas import (
    AnalysisRecord, AnalysisResult, CategoryScores, MissingSkill, Suggestion
)
from storage.sqlite_store import SQLiteStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage() -> SQLiteStorage:
    """
    Creates a fresh in-memory SQLite storage for each test.
    Because it's ':memory:', each test starts with a completely empty database.
    """
    return SQLiteStorage(":memory:")


def make_record(
    job_title: str = "Python Developer",
    score: int = 74,
    resume_source: str = "test.pdf"
) -> AnalysisRecord:
    """Helper to build a realistic AnalysisRecord for testing."""
    result = AnalysisResult(
        overall_score=score,
        category_scores=CategoryScores(
            skills_match=30.0,
            experience_relevance=18.0,
            keywords_ats=14.0,
            education_and_projects=12.0,
        ),
        matched_skills=["Python", "Django"],
        missing_skills=[MissingSkill(skill="Docker", importance="medium")],
        strengths=["Strong Python", "Relevant experience", "Good education"],
        suggestions=[
            Suggestion(section="Skills", suggestion="Add Docker"),
        ],
        one_line_summary="Good match overall.",
    )
    return AnalysisRecord(
        job_title=job_title,
        resume_source=resume_source,
        result=result,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSaveAnalysis:
    """Tests for the save_analysis() method."""

    def test_save_returns_a_string_id(self, storage):
        record = make_record()
        saved_id = storage.save_analysis(record)
        assert isinstance(saved_id, str)
        assert len(saved_id) > 0

    def test_save_assigns_unique_ids(self, storage):
        """Two saves must never return the same ID."""
        id1 = storage.save_analysis(make_record())
        id2 = storage.save_analysis(make_record())
        assert id1 != id2

    def test_saved_record_is_retrievable(self, storage):
        """
        A saved record must be fully recoverable by its ID.
        Note: we pass score=74 because the Pydantic @model_validator will
        reconcile overall_score to match the category sum (30+18+14+12=74).
        """
        record = make_record(job_title="Data Engineer", score=74)
        saved_id = storage.save_analysis(record)

        fetched = storage.get_by_id(saved_id)
        assert fetched is not None
        assert fetched.job_title == "Data Engineer"
        assert fetched.result.overall_score == 74


class TestGetAll:
    """Tests for the get_all() method."""

    def test_get_all_empty_returns_empty_list(self, storage):
        """No records saved → should return [] not raise an error."""
        result = storage.get_all()
        assert result == []

    def test_get_all_returns_all_records(self, storage):
        storage.save_analysis(make_record(job_title="Role A"))
        storage.save_analysis(make_record(job_title="Role B"))
        storage.save_analysis(make_record(job_title="Role C"))

        all_records = storage.get_all()
        assert len(all_records) == 3

    def test_get_all_returns_newest_first(self, storage):
        """
        Records must be returned newest-first (ORDER BY created_at DESC).
        We control timestamps by setting created_at explicitly.
        """
        import time

        rec_old = make_record(job_title="Old Job")
        storage.save_analysis(rec_old)

        time.sleep(0.05)  # tiny sleep to guarantee different timestamps

        rec_new = make_record(job_title="New Job")
        storage.save_analysis(rec_new)

        all_records = storage.get_all()
        # First item in the list should be the most recently saved
        assert all_records[0].job_title == "New Job"
        assert all_records[1].job_title == "Old Job"


class TestGetById:
    """Tests for the get_by_id() method."""

    def test_get_by_valid_id_returns_record(self, storage):
        saved_id = storage.save_analysis(make_record(job_title="Frontend Dev"))
        fetched = storage.get_by_id(saved_id)

        assert fetched is not None
        assert fetched.job_title == "Frontend Dev"

    def test_get_by_nonexistent_id_returns_none(self, storage):
        """A missing ID must return None, not raise an exception."""
        result = storage.get_by_id("this-id-does-not-exist")
        assert result is None

    def test_full_result_roundtrip(self, storage):
        """
        The full AnalysisResult object must survive the serialize → store → 
        deserialize roundtrip without any data loss.
        """
        original = make_record()
        saved_id = storage.save_analysis(original)
        fetched = storage.get_by_id(saved_id)

        # Deep-compare nested objects
        assert fetched.result.matched_skills == ["Python", "Django"]
        assert fetched.result.missing_skills[0].skill == "Docker"
        assert fetched.result.missing_skills[0].importance == "medium"
        assert fetched.result.suggestions[0].section == "Skills"
        assert fetched.result.category_scores.skills_match == 30.0
