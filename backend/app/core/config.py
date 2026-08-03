from pydantic_settings import BaseSettings
from typing import List
import json

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://autobim:autobim@localhost:5432/autobim"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "dev-secret-key"
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    ANTHROPIC_API_KEY: str = "AQ.Ab8RN6IBgjwyLtUJCOk5Vkjo5ahJTcTF6Nx3fMp5iFLNZ89xEQ"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
