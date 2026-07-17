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

    # --- Endurecimiento (anti-abuso / anti-DoS) ---
    # Límite de peticiones por IP. Se desactiva en los tests.
    rate_limit_enabled: bool = True
    # Endpoints normales: generoso, solo frena martilleo automatizado.
    default_rate_limit: str = "240/minute"
    # Login/registro: estrictos, frenan fuerza bruta (bcrypt es caro a propósito).
    auth_rate_limit: str = "10/minute"
    # Tamaño máximo de cuerpo de una petición (bytes). Cubre el tique de 5 MB
    # con holgura para el envoltorio multipart; rechaza cuerpos enormes antes
    # de leerlos en memoria.
    max_request_bytes: int = 8 * 1024 * 1024
    # Un gasto recurrente no puede materializar más de estos meses de golpe:
    # frena que una regla con fecha de inicio muy antigua cree cientos de gastos.
    recurring_max_catchup_months: int = 12


settings = Settings()
