from pydantic_settings import BaseSettings
from typing import List, Union
import json


def parse_origins(value: Union[str, List[str], None]) -> List[str]:
    """Accept a JSON array, a comma-separated string, or an actual list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except json.JSONDecodeError:
            raw = raw.strip("[]").replace('"', "").replace("'", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://autobim:autobim@localhost:5432/autobim"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "dev-secret-key"
    ENVIRONMENT: str = "development"

    # Deliberately a plain string, not List[str].
    #
    # pydantic-settings decodes any complex-typed field (List, Dict, ...) from
    # the environment as strict JSON inside EnvSettingsSource — which runs
    # BEFORE field validators, so a "before" validator cannot rescue it. With
    # List[str] here, setting CORS_ORIGINS to anything that is not valid JSON
    # killed the process at import:
    #
    #   SettingsError: error parsing value for field "CORS_ORIGINS"
    #
    # and main.py has always documented the comma-separated form for this very
    # variable. Keeping it a string means every sane format starts up; use
    # cors_origins_list to read it.
    CORS_ORIGINS: str = "http://localhost:3000"

    # Credentials must only come from the environment / backend/.env.  Never
    # ship a usable key as a source-code default.
    ANTHROPIC_API_KEY: str = ""
    BLENDER_RENDER_ENABLED: bool = False

    @property
    def cors_origins_list(self) -> List[str]:
        return parse_origins(self.CORS_ORIGINS)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
