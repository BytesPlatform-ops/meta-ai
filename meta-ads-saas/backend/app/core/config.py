from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "Meta Ads AI"
    API_VERSION: str = "v1"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"

    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str          # server-side only — never expose to client
    SUPABASE_ANON_KEY: str

    # Meta / Facebook OAuth
    META_APP_ID: str
    META_APP_SECRET: str
    META_REDIRECT_URI: str = "http://localhost:54562/api/v1/oauth/meta/callback"
    META_API_VERSION: str = "v19.0"

    # OpenAI
    OPENAI_API_KEY: str = ""

    # Model Router — centralised model selection
    # Elite: complex reasoning, optimization analysis, structured JSON output
    ELITE_REASONING_MODEL: str = "gpt-5.4"
    # Creative: ad copy, marketing content (human tone, high fluency)
    CREATIVE_WRITING_MODEL: str = "gpt-5.3-chat-latest"
    # Cheap: simple extraction, classification, keyword generation
    CHEAP_FAST_MODEL: str = "gpt-5-mini"

    # MCP Server (Facebook Ads MCP)
    MCP_SERVER_URL: str = "http://mcp-server:8080"  # internal docker service
    MCP_SERVER_API_KEY: str = ""                     # global key if required by MCP host

    # Email (for developer instructions)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@metaadsai.com"

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:54561"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
