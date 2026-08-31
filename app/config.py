import hashlib

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Claves de ejemplo que en algún momento estuvieron escritas en este repositorio.
# Siguen en el historial público de git, así que firmar tokens con una de ellas
# equivale a no firmarlos y se rechazan.
#
# Se guardan como SHA-256 y no en claro: así buscar la cadena en el código no
# devuelve nada, que es justo lo que pide el criterio del punto de seguridad.
CLAVES_PUBLICADAS = frozenset(
    {
        "6d1b95155d95af07ed06b2f3ff246d168fede353f1b8dcb0dde29f2cb6be9dc9",
        # El texto de relleno de .env.example: mide más de 32 bytes, así que
        # sin esto pasaría la validación y quedaría en producción sin querer.
        "4504577b15dc8a3a88e6cdd7a620d2eeaad1ac167ce63b01b596656aa2c5d4fc",
    }
)

# Mínimo de entropía exigido a la clave de firma, en BYTES (no caracteres).
LONGITUD_MINIMA_CLAVE = 32

ENTORNO_DESARROLLO = "dev"
ENTORNO_PRODUCCION = "prod"
ENTORNOS = (ENTORNO_DESARROLLO, ENTORNO_PRODUCCION)

_COMO_GENERARLA = 'python -c "import secrets; print(secrets.token_hex(32))"'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Sin valor por defecto a propósito: son obligatorias. Un valor por defecto
    # aquí significa que la API arranca igual con una configuración equivocada.
    database_url: str
    secret_key: str

    # Por defecto "prod": olvidar la variable debe dejar la app en su modo más
    # cerrado, no en el más cómodo.
    environment: str = ENTORNO_PRODUCCION

    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    # Sesión larga al estilo de las apps de uso diario: el refresh token dura
    # un año y se renueva en cada uso (rotación en /auth/refresh), así que
    # quien abre la app de vez en cuando no vuelve a ver la pantalla de login.
    refresh_token_expire_days: int = 365

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

    @property
    def es_desarrollo(self) -> bool:
        return self.environment == ENTORNO_DESARROLLO

    @field_validator("environment")
    @classmethod
    def _entorno_conocido(cls, valor: str) -> str:
        if valor not in ENTORNOS:
            raise ValueError(f"debe ser uno de {', '.join(ENTORNOS)}")
        return valor

    @field_validator("secret_key")
    @classmethod
    def _clave_de_firma_utilizable(cls, valor: str) -> str:
        if _esta_publicada(valor):
            raise ValueError(
                "es una clave de ejemplo del repositorio, que es pública; "
                f"genera una propia con: {_COMO_GENERARLA}"
            )

        if not valor.strip():
            raise ValueError("está en blanco")

        longitud = len(valor.encode("utf-8"))
        if longitud < LONGITUD_MINIMA_CLAVE:
            raise ValueError(
                f"mide {longitud} bytes y hacen falta {LONGITUD_MINIMA_CLAVE} "
                f"como mínimo; genera una con: {_COMO_GENERARLA}"
            )

        return valor


def _esta_publicada(valor: str) -> bool:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest() in CLAVES_PUBLICADAS


def _describir(error: ValidationError) -> str:
    """Convierte el error de Pydantic en algo que se entienda en un log."""
    lineas = []
    for fallo in error.errors():
        variable = str(fallo["loc"][0]).upper() if fallo["loc"] else "configuración"
        motivo = fallo["msg"].removeprefix("Value error, ")
        if fallo["type"] == "missing":
            motivo = "falta y es obligatoria"
        lineas.append(f"  - {variable}: {motivo}")

    return "\n".join(
        [
            "",
            "No se puede arrancar Dividi: la configuración no es válida.",
            "",
            *lineas,
            "",
            "Define esas variables en el fichero .env (ver .env.example).",
            "",
        ]
    )


def cargar_settings(env_file: str | None = ".env") -> Settings:
    """Carga la configuración, o aborta el arranque explicando qué falta."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as error:
        raise SystemExit(_describir(error)) from error


settings = cargar_settings()
