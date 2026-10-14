"""
config.py - Centralized configuration and logging setup.

WHY THIS DESIGN?
Centralizing configuration in one file prevents 'magic numbers' and hardcoded 
secrets scattered across the codebase. Downstream files import settings from here, 
ensuring a Single Source of Truth (SSOT).
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# 1. Project Root Directory
# Using Path(__file__).resolve().parent gives an absolute, OS-agnostic path 
# to the 'resume-analyzer' folder.
BASE_DIR = Path(__file__).resolve().parent

# 2. Load Environment Variables from .env
# load_dotenv reads key-value pairs from .env and injects them into os.environ.
ENV_FILE = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE)

# 3. Core API and Model Settings
# NEVER hardcode the key; always read from environment.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Default to gemini-2.5-flash: high speed, low cost, native structured output support
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

# 4. Text Length Boundaries (Sanity checks)
# Protects against empty inputs or huge documents that exhaust token budgets
MIN_RESUME_CHARS = 50
MIN_JOB_DESC_CHARS = 30
MAX_TEXT_CHARS = 30000

# 5. Category Scoring Weights (Total must equal 100)
# These represent the exact scoring rubric weights specified in requirements.
WEIGHT_SKILLS_MATCH = 40.0
WEIGHT_EXPERIENCE_RELEVANCE = 25.0
WEIGHT_KEYWORDS_ATS = 20.0
WEIGHT_EDUCATION_PROJECTS = 15.0
MAX_OVERALL_SCORE = 100.0

# 6. Database & Storage Settings
DATABASE_PATH = BASE_DIR / "resume_analyzer.db"

# Setting to choose storage backend: 'sqlite' or 'mongodb' (defaults to 'sqlite')
STORAGE_TYPE = os.getenv("STORAGE_TYPE", "sqlite").strip().lower()

# MongoDB settings (defaults to localhost:27017 and resumeAnalyzerDB)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017").strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "resumeAnalyzerDB").strip()

# 7. Logging Configuration
# Logs errors and warnings to a file so we can debug production issues 
# without showing raw tracebacks to end users.
LOG_FILE = BASE_DIR / "resume_analyzer.log"
LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("ResumeAnalyzer")

def validate_config() -> tuple[bool, str]:
    """
    Validates that essential configurations (like the API key) are present.
    Returns (is_valid, error_message).
    
    WHY: Catch missing configuration at startup before user actions fail.
    NOTE: Never logs or prints the actual API key string for security.
    """
    if not GEMINI_API_KEY:
        msg = "GEMINI_API_KEY is missing. Please add your key to the .env file."
        logger.warning(msg)
        return False, msg
    return True, "Configuration is valid."
