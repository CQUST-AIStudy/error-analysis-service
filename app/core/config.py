from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"

    # Service
    service_host: str = "0.0.0.0"
    service_port: int = 8002

    # Tuning
    request_timeout: int = 30
    max_code_lines: int = 3000

    @property
    def cors_origins(self) -> list[str]:
        return ["*"]


def get_settings() -> Settings:
    return Settings()
