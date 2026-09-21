from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracion de la API, sobreescribible por entorno o por .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MergePay API"
    database_url: str = "sqlite:///./mergepay.db"

    # Opcional: sin token se consultan repositorios publicos con el rate limit
    # anonimo de GitHub. Nunca se registra ni se serializa.
    github_token: str | None = None

    stellar_rpc_url: str = "https://soroban-testnet.stellar.org"
    stellar_network_passphrase: str = "Test SDF Network ; September 2015"

    # Opcionales a proposito: la app y los tests arrancan sin .env. Solo se
    # exigen al construir un StellarClient desde settings.
    stellar_contract_id: str | None = None
    stellar_verifier_secret: str | None = None


settings = Settings()
