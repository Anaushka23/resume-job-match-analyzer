"""
Data persistence and storage package.
Exports BaseStorage, SQLiteStorage, and MongoStorage.
"""

from storage.base import BaseStorage
from storage.sqlite_store import SQLiteStorage
from storage.mongo_store import MongoStorage
import config

__all__ = ["BaseStorage", "SQLiteStorage", "MongoStorage", "get_storage"]


def get_storage(storage_type: str | None = None) -> BaseStorage:
    """
    Factory function returning the configured storage backend.
    
    Reads from config.STORAGE_TYPE ('sqlite' or 'mongodb') unless overridden.
    """
    backend = (storage_type or config.STORAGE_TYPE).lower()
    if backend == "mongodb" or backend == "mongo":
        return MongoStorage()
    return SQLiteStorage()
