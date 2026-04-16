from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://credit:credit@localhost:5432/credit_analysis"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    secret_key: str = "change-me-in-production"
    sec_user_agent: str = "CreditAnalysis admin@example.com"
    frontend_origin: str = "http://localhost:5173"

    # JWT settings
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # SEC rate limiting
    sec_requests_per_second: float = 8.0

    # Cache TTLs (seconds)
    cache_ttl_company_facts: int = 86400       # 24h
    cache_ttl_financials: int = 21600          # 6h
    cache_ttl_submissions: int = 43200         # 12h
    cache_ttl_debt: int = 43200                # 12h
    cache_ttl_search: int = 3600               # 1h


settings = Settings()
