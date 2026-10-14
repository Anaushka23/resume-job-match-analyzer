"""
storage/sqlite_store.py - SQLite implementation of BaseStorage.

WHY SQLITE?
SQLite is a file-based database built into Python's standard library (no 
installation needed). It stores everything in a single .db file. Perfect 
for a local, single-user app — no database server to run, no credentials 
to manage.

WHAT IS JSON SERIALIZATION HERE?
Our AnalysisResult object (from Pydantic) is a rich Python object with 
nested lists and objects. SQL databases store flat rows of simple types 
(text, numbers, dates). 

Strategy: Store the FULL analysis result as a single JSON text column.
Store the METADATA (score, job title, date) as separate columns so the
history table can be sorted and filtered without parsing the full JSON.

This is a practical trade-off: metadata is queryable, full detail is 
recoverable. Known as a "hybrid" storage pattern.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime

import config
from models.schemas import AnalysisRecord, AnalysisResult, CategoryScores, MissingSkill, Suggestion
from storage.base import BaseStorage

logger = logging.getLogger("ResumeAnalyzer.sqlite_store")


class SQLiteStorage(BaseStorage):
    """
    Concrete SQLite implementation of the BaseStorage contract.

    On instantiation, it ensures the database file and table exist.
    Uses Python's built-in sqlite3 module — no extra library needed.
    """

    def __init__(self, db_path: str | None = None):
        """
        Initializes the SQLite storage.

        Args:
            db_path: Path to the .db file. Defaults to the path in config.py.
                     Accepting a custom path makes this easy to test with a
                     temporary in-memory database (':memory:').

        WHY _persistent_conn FOR ':memory:'?
        Each sqlite3.connect(':memory:') call creates a BRAND NEW, separate
        in-memory database. So a table created in one connection is invisible
        to the next. For ':memory:' we must reuse the same connection object.
        For a real file database, each call opens the same file, so fresh
        connections are fine (and safer for threading).
        """
        self.db_path = str(db_path or config.DATABASE_PATH)
        # Keep a single persistent connection only for in-memory databases.
        self._persistent_conn: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._persistent_conn = self._make_raw_connection()
        self._ensure_table_exists()
        logger.info("SQLiteStorage initialized at: %s", self.db_path)

    def _make_raw_connection(self) -> sqlite3.Connection:
        """Creates a brand-new SQLite connection with Row factory enabled."""
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _get_connection(self) -> sqlite3.Connection:
        """
        Returns the correct connection for this database type.

        - ':memory:' databases: always return the same persistent connection.
        - File databases: create a fresh connection each time (thread-safe).

        WHY NOT STORE ONE CONNECTION AS self.conn FOR FILE DATABASES?
        SQLite connections are not thread-safe by default. Streamlit may
        run callbacks from multiple threads. Creating a fresh connection
        per operation is simpler and safer than managing thread locks.
        """
        if self._persistent_conn is not None:
            return self._persistent_conn
        return self._make_raw_connection()

    def _ensure_table_exists(self) -> None:
        """
        Creates the analyses table if it doesn't already exist.

        'CREATE TABLE IF NOT EXISTS' is idempotent — safe to call every
        time the app starts. It only creates the table on the first run.

        Column design rationale:
        - id: UUID string — globally unique, no sequential guessability.
        - created_at: ISO timestamp text for sorting by date.
        - job_title: Stored flat for fast display in the history table.
        - resume_source: Filename or "[Pasted Text]" for display.
        - overall_score: Integer stored separately for sorting/filtering.
        - result_json: The FULL AnalysisResult serialized to JSON text.
                       Lets us recover every field without a complex schema.
        """
        sql = """
        CREATE TABLE IF NOT EXISTS analyses (
            id            TEXT PRIMARY KEY,
            created_at    TEXT NOT NULL,
            job_title     TEXT NOT NULL,
            resume_source TEXT NOT NULL,
            overall_score INTEGER NOT NULL,
            result_json   TEXT NOT NULL
        );
        """
        with self._get_connection() as conn:
            conn.execute(sql)
            conn.commit()
        logger.debug("Database table 'analyses' is ready.")

    # ------------------------------------------------------------------
    # Public interface methods (implementing BaseStorage contract)
    # ------------------------------------------------------------------

    def save_analysis(self, record: AnalysisRecord) -> str:
        """
        Saves an AnalysisRecord to the SQLite database.

        Generates a UUID for the record ID if one was not already set.
        Serializes the AnalysisResult to JSON for the result_json column.

        Args:
            record: The AnalysisRecord to persist.

        Returns:
            The unique ID string assigned to this record.
        """
        # Generate a unique ID if the caller hasn't provided one.
        # UUID4 is random and collision-resistant — 2^122 possible values.
        record_id = record.id or str(uuid.uuid4())

        # Pydantic's model_dump() converts the object into a plain Python dict.
        # json.dumps() then converts the dict to a JSON string for storage.
        result_json = json.dumps(record.result.model_dump())

        sql = """
        INSERT INTO analyses (id, created_at, job_title, resume_source, overall_score, result_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        # Using ? placeholders (parameterized queries) instead of f-strings
        # prevents SQL injection — essential security practice.
        params = (
            record_id,
            record.created_at.isoformat(),
            record.job_title,
            record.resume_source,
            record.result.overall_score,
            result_json,
        )

        with self._get_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

        logger.info("Saved analysis record ID: %s (score: %d)", record_id, record.result.overall_score)
        return record_id

    def get_all(self) -> list[AnalysisRecord]:
        """
        Returns all analysis records, newest first.

        Used by the History page to render the summary table.
        """
        sql = "SELECT * FROM analyses ORDER BY created_at DESC"

        with self._get_connection() as conn:
            rows = conn.execute(sql).fetchall()

        records = [self._row_to_record(row) for row in rows]
        logger.info("Fetched %d analysis records from storage.", len(records))
        return records

    def get_by_id(self, record_id: str) -> AnalysisRecord | None:
        """
        Returns a single analysis record by ID, or None if not found.

        Used when the user clicks a row in the History table to view
        the full breakdown of a past analysis.
        """
        sql = "SELECT * FROM analyses WHERE id = ?"

        with self._get_connection() as conn:
            row = conn.execute(sql, (record_id,)).fetchone()

        if row is None:
            logger.warning("No record found with ID: %s", record_id)
            return None

        return self._row_to_record(row)

    # ------------------------------------------------------------------
    # Private helper
    # ------------------------------------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> AnalysisRecord:
        """
        Converts a raw SQLite row back into a full AnalysisRecord object.

        WHY THIS HELPER?
        Both get_all() and get_by_id() need to deserialize rows. Extracting
        this to a private method keeps both callers clean and avoids 
        duplicated deserialization logic.

        The process is the reverse of save_analysis():
          JSON text → Python dict → AnalysisResult (via Pydantic) → AnalysisRecord
        """
        # Parse the stored JSON string back into a Python dict
        result_dict = json.loads(row["result_json"])

        # Reconstruct the nested Pydantic object from the dict.
        # Pydantic handles the nested structure (CategoryScores, MissingSkill, etc.)
        # automatically when we call AnalysisResult(**result_dict).
        result = AnalysisResult(**result_dict)

        return AnalysisRecord(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            job_title=row["job_title"],
            resume_source=row["resume_source"],
            result=result,
        )
