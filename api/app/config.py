from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracion de la API, sobreescribible por entorno o por .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MergePay API"
    database_url: str = "sqlite:///./mergepay.db"

    # Origenes del navegador que pueden llamar a la API, separados por comas.
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Opcional: sin token se consultan repositorios publicos con el rate limit
    # anonimo de GitHub. Nunca se registra ni se serializa.
    github_token: str | None = None

    stellar_rpc_url: str = "https://soroban-testnet.stellar.org"
    stellar_network_passphrase: str = "Test SDF Network ; September 2015"

    # Opcionales a proposito: la app y los tests arrancan sin .env. Solo se
    # exigen al construir un StellarClient desde settings.
    stellar_contract_id: str | None = None
    stellar_verifier_secret: str | None = None

    google_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"

    @property
    def cors_origins(self) -> list[str]:
        """La lista limpia: sin espacios, sin vacios y sin repetidos.

        "*" no vale. MergePay sirve tasks privadas con Bearer, asi que los
        origenes se declaran uno a uno; si aparece, la app falla al arrancar.
        """
        origins: list[str] = []

        for entry in self.cors_allowed_origins.split(","):
            origin = entry.strip()

            if not origin:
                continue

            if origin == "*":
                raise ValueError(
                    "cors_allowed_origins must list explicit origins, not '*'"
                )

            if origin not in origins:
                origins.append(origin)

        return origins


settings = Settings()
