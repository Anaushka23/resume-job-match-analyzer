"""
storage/base.py - Abstract storage interface (the Repository Pattern).

WHY AN ABSTRACT CLASS?
Right now we use SQLite. In the future, you might switch to MongoDB, 
PostgreSQL, or a cloud database. 

If app.py called SQLite directly, swapping databases would mean rewriting 
the UI code too. That violates the Dependency Inversion Principle (the 'D'
in SOLID): high-level modules (the UI) should not depend on low-level details 
(a specific database).

By defining an interface here, app.py only ever talks to this contract.
Swapping databases = write one new class that implements these 3 methods.
The UI code never changes.

HOW IT WORKS IN PYTHON:
- We inherit from ABC (Abstract Base Class) in the standard library.
- Any method decorated with @abstractmethod MUST be implemented by any
  class that inherits from BaseStorage. If it is not, Python raises a 
  TypeError at import time — you can't even instantiate the incomplete class.
"""

from abc import ABC, abstractmethod
from models.schemas import AnalysisRecord


class BaseStorage(ABC):
    """
    Abstract contract that every storage backend must fulfill.
    Think of this as the "plug socket shape" — any database is the plug,
    as long as it has the right shape (implements these 3 methods).
    """

    @abstractmethod
    def save_analysis(self, record: AnalysisRecord) -> str:
        """
        Persists a completed analysis record to storage.

        Args:
            record: A fully validated AnalysisRecord object (from models/schemas.py).

        Returns:
            The unique ID string assigned to this record in storage.
            (The caller can use this ID to retrieve the record later.)
        """
        ...

    @abstractmethod
    def get_all(self) -> list[AnalysisRecord]:
        """
        Retrieves a summary list of all past analyses, ordered newest first.

        Returns:
            A list of AnalysisRecord objects.
            (For a history table, you only need a few fields, but returning
             the full object keeps the interface simple and consistent.)
        """
        ...

    @abstractmethod
    def get_by_id(self, record_id: str) -> AnalysisRecord | None:
        """
        Retrieves a single analysis record by its unique ID.

        Args:
            record_id: The unique string ID returned when the record was saved.

        Returns:
            The full AnalysisRecord object, or None if no record matches the ID.
            (Returning None instead of raising an exception is a common pattern —
             it lets the caller decide what "not found" means in context.)
        """
        ...
