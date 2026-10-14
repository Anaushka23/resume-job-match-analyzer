"""
storage/mongo_store.py - MongoDB implementation of BaseStorage using PyMongo.

WHY MONGODB FOR ANALYSIS RESULTS? (Document Databases vs Relational)
1. Native Hierarchical Data: Our AnalysisResult has rich nested structures
   (category_scores dictionary, lists of matched_skills, lists of MissingSkill
   objects with importance, and lists of Suggestion objects with sections).
   In SQLite, we had to dump this into a flat string column ('result_json').
   In MongoDB, the object graph maps 1:1 into a BSON/JSON document without flattening.
2. Queryability into Nested Fields: With MongoDB, you can easily query nested fields
   directly (e.g., db.analyses.find({"result.category_scores.skills_match": {"$gt": 30}}))
   without needing full-text searches or parsing JSON strings.
3. Schema Evolution: If we add a new evaluation category or new metric in the future,
   MongoDB is schemaless at the storage layer, allowing smooth migrations.
"""

import logging
import uuid
from datetime import datetime
from typing import Any
import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection

import config
from models.schemas import AnalysisRecord, AnalysisResult
from storage.base import BaseStorage

logger = logging.getLogger("ResumeAnalyzer.mongo_store")


class MongoStorage(BaseStorage):
    """
    MongoDB implementation of the BaseStorage contract.
    Persists analysis records into a MongoDB collection as native documents.
    """

    def __init__(
        self,
        mongo_uri: str | None = None,
        db_name: str | None = None,
        collection_name: str = "analyses",
        client: MongoClient | None = None
    ):
        """
        Initializes MongoDB client, database, and collection.

        Args:
            mongo_uri: Connection URI (defaults to config.MONGO_URI).
            db_name: Target database name (defaults to config.MONGO_DB_NAME).
            collection_name: Name of collection to store records (default: 'analyses').
            client: Optional pre-configured MongoClient (useful for testing/mocking).
        """
        self.mongo_uri = mongo_uri or config.MONGO_URI
        self.db_name = db_name or config.MONGO_DB_NAME
        self.collection_name = collection_name

        # Allow passing an existing client or instantiate a new one
        if client is not None:
            self.client = client
        else:
            self.client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=3000)

        self.db = self.client[self.db_name]
        self.collection: Collection = self.db[self.collection_name]

        # Ensure index on created_at for fast descending history queries
        try:
            self.collection.create_index([("created_at", pymongo.DESCENDING)])
            logger.info("MongoStorage connected to %s/%s", self.mongo_uri, self.db_name)
        except Exception as e:
            # We log as warning so offline/mock setups can still be initialized
            logger.warning("Could not connect to MongoDB server during init: %s", e)

    def save_analysis(self, record: AnalysisRecord) -> str:
        """
        Persists an AnalysisRecord as a native MongoDB document.

        Args:
            record: The validated AnalysisRecord to save.

        Returns:
            The unique string ID of the inserted document.
        """
        record_id = record.id or str(uuid.uuid4())

        # Store the result directly as a nested dict (BSON document)
        doc: dict[str, Any] = {
            "_id": record_id,
            "created_at": record.created_at,
            "job_title": record.job_title,
            "resume_source": record.resume_source,
            "overall_score": record.result.overall_score,
            # In MongoDB, we do NOT need json.dumps(); PyMongo stores nested dicts natively!
            "result": record.result.model_dump()
        }

        self.collection.insert_one(doc)
        logger.info("Saved analysis record to MongoDB with ID: %s", record_id)
        return record_id

    def get_all(self) -> list[AnalysisRecord]:
        """
        Retrieves all analysis records from MongoDB, sorted by created_at descending.

        Returns:
            List of AnalysisRecord objects.
        """
        cursor = self.collection.find().sort("created_at", pymongo.DESCENDING)
        records: list[AnalysisRecord] = []

        for doc in cursor:
            records.append(self._doc_to_record(doc))

        logger.info("Fetched %d records from MongoDB.", len(records))
        return records

    def get_by_id(self, record_id: str) -> AnalysisRecord | None:
        """
        Retrieves a single analysis record by its ID.

        Args:
            record_id: Unique record ID string.

        Returns:
            The AnalysisRecord if found, otherwise None.
        """
        doc = self.collection.find_one({"_id": record_id})
        if doc is None:
            logger.warning("No MongoDB document found for ID: %s", record_id)
            return None

        return self._doc_to_record(doc)

    def _doc_to_record(self, doc: dict[str, Any]) -> AnalysisRecord:
        """
        Helper that maps a raw MongoDB document back to an AnalysisRecord Pydantic model.
        """
        return AnalysisRecord(
            id=str(doc["_id"]),
            created_at=doc["created_at"],
            job_title=doc["job_title"],
            resume_source=doc["resume_source"],
            result=AnalysisResult(**doc["result"])
        )
