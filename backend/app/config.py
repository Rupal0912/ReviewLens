"""Settings read from environment variables (server-side only)."""
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DB_PATH = os.getenv("DB_PATH", "reviewlens.db")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
MAX_REVIEW_CHARS = 1000      # longer reviews are truncated before reaching the LLM
MAX_UPLOAD_BYTES = 2_000_000
