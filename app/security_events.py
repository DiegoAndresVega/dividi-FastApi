"""Registro de eventos de seguridad, una línea de JSON por evento.

Las líneas de acceso de uvicorn dicen qué ruta se pidió, pero no quién. Sin
eso no se puede reconstruir qué pasó: «alguien borró el grupo» no es una
respuesta, «el usuario X lo borró desde la IP Y a las 04:12» sí.

Formato de una línea por evento y en JSON a propósito: `docker logs` los
entrega tal cual, `grep` sigue funcionando, y `jq` los filtra sin tener que
inventar un analizador para un formato de la casa.

**Qué no se escribe nunca aquí:** contraseñas, tokens, códigos de invitación
ni el cuerpo de ninguna petición. Lo que se guarda es el id del usuario, la IP
y qué hizo. Aun así, todo lo que sale pasa además por el filtro de
`app/logging_config.py`, porque la primera regla es no escribirlo y la segunda
es que si se escribe, no salga.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from starlette.requests import Request

registro = logging.getLogger("dividi.seguridad")

# Campos que jamás se copian a un evento, aunque alguien los pase por `datos`.
# La lista existe porque el descuido típico es pasar el objeto entero de una
# petición «para tener más contexto».
PROHIBIDOS = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "contrasena",
        "hashed_password",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "secret_key",
        "authorization",
        "code",
        "invite_code",
    }
)


def ip_de(request: Request | None) -> str:
    """IP del cliente, ya resuelta por uvicorn a partir del X-Forwarded-For.

    uvicorn corre con --proxy-headers y --forwarded-allow-ips acotado a la red
    de Caddy, así que `request.client.host` es la IP real y no la del proxy.
    """
    if request is None or request.client is None:
        return "desconocida"
    return request.client.host


def registrar(
    evento: str,
    request: Request | None = None,
    *,
    user_id: uuid.UUID | str | None = None,
    **datos: object,
) -> None:
    """Escribe un evento. Nunca levanta: un fallo aquí no puede tumbar la API."""
    try:
        linea = {
            "evento": evento,
            "momento": datetime.now(timezone.utc).isoformat(),
            "ip": ip_de(request),
        }
        if user_id is not None:
            linea["user_id"] = str(user_id)
        linea.update(_limpiar(datos))
        registro.info(json.dumps(linea, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        # Que no se pueda registrar un evento es un problema, pero menor que
        # devolverle un 500 al usuario por culpa del registro.
        registro.exception("no se pudo registrar el evento %s", evento)


def _limpiar(datos: dict[str, object]) -> dict[str, object]:
    return {
        clave: valor
        for clave, valor in datos.items()
        if clave.lower() not in PROHIBIDOS and valor is not None
    }
