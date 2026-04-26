from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    # GitHub App credentials
    github_app_id: str = ""
    github_private_key: str = ""  # PEM contents or path to .pem file
    github_webhook_secret: str = ""

    # Minis backend
    minis_api_url: str = "http://localhost:8000"
    trusted_service_secret: str = ""

    # Mini username suffix (e.g., "alliecatowo" -> check for "alliecatowo" mini)
    mini_mention_suffix: str = "-mini"

    # GitHub App bot login (e.g. "minis-app[bot]"). Used for idempotency checks when
    # determining which existing reviews were posted by this app.
    github_bot_login: str = "minis-app[bot]"


settings = Settings()
