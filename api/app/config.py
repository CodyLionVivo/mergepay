from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracion de la API, sobreescribible por entorno o por .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MergePay API"
    database_url: str = "sqlite:///./mergepay.db"

    # Opcional: sin token se consultan repositorios publicos con el rate limit
    # anonimo de GitHub. Nunca se registra ni se serializa.
    github_token: str | None = None


settings = Settings()
