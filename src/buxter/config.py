from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MODEL_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}


def resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name, name)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    freecad_cmd: str | None = Field(default=None, alias="FREECAD_CMD")
    output_dir: Path = Field(default=Path("./out"), alias="BUXTER_OUTPUT_DIR")
    model: str = Field(default="opus", alias="BUXTER_MODEL")
    run_timeout: int = Field(default=120, alias="BUXTER_RUN_TIMEOUT")
    max_tokens: int = Field(default=8192, alias="BUXTER_MAX_TOKENS")


def load_settings() -> Settings:
    return Settings()
