from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://gastos:gastos@localhost:5432/gastos"
    secret_key: str = "dev-secret-key-cambiar-en-produccion"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Registro invite-only: exige un código de invitación válido para registrarse.
    # El primer usuario del sistema (fundador) queda exento del requisito.
    require_invite: bool = True
    # Días por defecto de caducidad de una invitación (None = no caduca).
    invite_default_expire_days: int | None = None
    # Base URL del frontend para construir el enlace de invitación (opcional).
    frontend_base_url: str | None = None
    # Carpeta donde se guardan las fotos de los tiques (montada como volumen
    # en producción para sobrevivir a los rebuilds del contenedor).
    receipts_dir: str = "receipts"


settings = Settings()
