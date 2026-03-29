import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_base: str = os.getenv("AI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    api_key: str = os.getenv("AI_API_KEY", "")
    model: str = os.getenv("AI_MODEL", "deepseek-v3.1")
    db_path: str = os.getenv("SQLITE_DB_PATH", "data/bookmark_ai.sqlite3")
    daily_limit: int = int(os.getenv("DAILY_REQUEST_LIMIT", "8"))
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))


settings = Settings()
