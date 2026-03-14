from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    anthropic_api_key: str = ""
    database_url: str = "postgresql://user:password@localhost:5432/earnings_lens"
    scrape_delay_seconds: int = 2


settings = Settings()
