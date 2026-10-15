from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    database_url_unpooled: str | None = Field(default=None, validation_alias="DATABASE_URL_UNPOOLED")
    api_port: int = Field(default=8000, validation_alias="API_PORT")
    api_title: str = "NCDEX Trading System API"
    api_version: str = "0.2.0"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if v and not (v.startswith("postgresql://") or v.startswith("postgres://")):
            raise ValueError("DATABASE_URL must start with postgresql:// or postgres://")
        return v

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local", "../.env", "../.env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
