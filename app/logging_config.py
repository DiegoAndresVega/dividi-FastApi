"""Que ningún secreto salga por el registro del contenedor.

Los logs de la API van a stdout y de ahí a `docker logs`, que los guarda en
disco sin cifrar y los lee cualquiera que llegue a la máquina. Un token o una
contraseña ahí dentro vale lo mismo que en la base de datos, pero sin ninguna
de sus protecciones.

La primera línea de defensa es no escribirlos: `Settings` guarda sus secretos
como `SecretStr`, y ningún sitio de la aplicación registra cuerpos de petición.
Esto es la segunda: un filtro que repasa cada línea antes de que salga, por si
alguien mete un `print` de depuración o una librería de terceros es más
habladora de lo que esperábamos.
"""

import logging
import re

MASCARA = "***"

# Cada patrón deja a la vista la parte que sirve para depurar —qué cabecera,
# qué campo, qué ruta— y tapa solo el valor.
PATRONES = (
    # Authorization: Bearer <token>, y la variante en JSON o en diccionario
    re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?\s*(?:bearer|basic)\s+)\S+"),
    # password, token, secret, api_key... en clave=valor o en JSON
    re.compile(
        r"(?i)([\"']?(?:password|contrasena|contraseña|secret|secret_key|token|"
        r"access_token|refresh_token|api_key|apikey)[\"']?\s*[:=]\s*)"
        r"[\"']?[^\s,;&}\"']+"
    ),
    # La contraseña dentro de una URL de conexión: esquema://usuario:AQUI@host
    re.compile(r"(?i)(\b[a-z0-9+.-]+://[^\s:/@]+:)[^\s@/]+(@)"),
    # El código de invitación va en la ruta, así que entra en el log de acceso
    # de uvicorn tal cual. Es de un solo uso, pero mientras no se gasta sirve
    # para registrarse en una instalación que es solo por invitación.
    re.compile(r"(?i)(/invitations/)[^/\s?\"]+"),
    # Cualquier cosa con forma de JWT, venga de donde venga
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
)


def enmascarar(texto: str) -> str:
    """Devuelve el texto con los valores sensibles sustituidos por `***`."""
    for patron in PATRONES:
        texto = patron.sub(_sustituir, texto)
    return texto


def _sustituir(coincidencia: re.Match[str]) -> str:
    # Los grupos capturados son las partes que se conservan (el nombre de la
    # cabecera, el del campo, el prefijo de la ruta); el resto se tapa.
    conservado = [grupo for grupo in coincidencia.groups() if grupo is not None]
    if not conservado:
        return MASCARA
    if len(conservado) == 1:
        return f"{conservado[0]}{MASCARA}"
    return f"{conservado[0]}{MASCARA}{''.join(conservado[1:])}"


class FiltroDeSecretos(logging.Filter):
    """Enmascara el mensaje de cada registro antes de que se escriba.

    Se aplica sobre el mensaje ya formateado y se guarda en `msg` con `args`
    vacío: si se dejaran los argumentos sin tocar, el formateo posterior
    volvería a insertar el valor original.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        original = record.getMessage()
        limpio = enmascarar(original)
        if limpio != original:
            record.msg = limpio
            record.args = ()
        return True


# Loggers que uvicorn crea por su cuenta, con `propagate` a False: sus líneas
# no pasan por la raíz, así que hay que colgarles el filtro aparte.
LOGGERS_DE_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configurar_logging() -> None:
    """Cuelga el filtro allí donde de verdad se escriben las líneas.

    El filtro va en los **manejadores**, no solo en los loggers. Un filtro
    puesto en un logger solo mira lo que se registra a través de ese logger:
    lo que sube propagado desde un hijo se lo salta y solo pasa por los
    manejadores de los antepasados. Colgándolo del logger se escaparía justo
    el caso que más importa —la traza de una librería cualquiera—, así que va
    en los dos sitios.
    """
    filtro = FiltroDeSecretos()

    raiz = logging.getLogger()
    if not raiz.handlers:
        # Sin manejadores no hay dónde colgar el filtro, y además las líneas se
        # perderían. Uno a stdout, que es de donde las recoge Docker.
        logging.basicConfig(level=logging.INFO)

    _colgar(filtro, raiz)
    for nombre in LOGGERS_DE_UVICORN:
        _colgar(filtro, logging.getLogger(nombre))


def _colgar(filtro: logging.Filter, registro: logging.Logger) -> None:
    if filtro not in registro.filters:
        registro.addFilter(filtro)
    for manejador in registro.handlers:
        if filtro not in manejador.filters:
            manejador.addFilter(filtro)
