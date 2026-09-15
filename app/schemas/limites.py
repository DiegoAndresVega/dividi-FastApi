"""Topes compartidos por los esquemas de entrada.

Están aquí y no repartidos por cada fichero para que el número esté escrito una
sola vez: el máximo de miembros de un grupo es el mismo tope para la lista de
invitados iniciales, para los repartos de un gasto y para un rebalanceo, porque
las tres cosas cuentan lo mismo.

El límite de tamaño del cuerpo (8 MB) frena la petición gigante, pero dentro de
esos 8 MB caben decenas de miles de elementos en una lista, y cada uno acaba
siendo una fila. Los topes de aquí son los que hacen que eso no ocurra.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints


class RangoDeclarado:
    """Marca para el guardián de `tests/test_limites_entrada.py`.

    Un rango que comprueba un validador no se puede leer de los metadatos del
    campo, así que quien lo escribe lo deja dicho aquí. Pydantic ignora los
    elementos de `Annotated` que no entiende, de modo que esto no cambia nada
    en tiempo de ejecución.
    """

    def __init__(self, descripcion: str) -> None:
        self.descripcion = descripcion

    def __repr__(self) -> str:  # pragma: no cover - solo para depurar
        return f"RangoDeclarado({self.descripcion!r})"


# --------------------------------------------------------------- colecciones

# Un grupo de gastos compartidos es una cena, un piso o un viaje. Cincuenta
# personas es holgado para cualquiera de los tres, y es el tope que acota a la
# vez los invitados iniciales, los repartos de un gasto y un rebalanceo.
MAX_MIEMBROS_POR_GRUPO = 50
# Partes de un reparto por «shares» (dos noches frente a una: 2 y 1).
MAX_PARTES = 1_000
# Presupuestos por categoría en /me/finances.
MAX_PRESUPUESTOS = 100


# -------------------------------------------------------------------- dinero

MAX_IMPORTE = Decimal("9999999999")


# -------------------------------------------------------------------- fechas

# Un gasto se apunta tarde, no diez años tarde. Por delante solo se admite un
# día, que es margen para el reloj del teléfono, no para apuntar el futuro.
ANOS_HACIA_ATRAS = 10
MARGEN_HACIA_DELANTE = timedelta(days=1)


def _fecha_en_rango(valor: datetime) -> datetime:
    # La app manda unas fechas con zona y otras sin ella. Comparar una ingenua
    # con una consciente lanza TypeError, así que la ingenua se toma como UTC,
    # que es lo que asume el resto de la aplicación.
    referencia = valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    ahora = datetime.now(timezone.utc)

    if referencia > ahora + MARGEN_HACIA_DELANTE:
        raise ValueError("está en el futuro")
    if referencia < ahora - timedelta(days=365 * ANOS_HACIA_ATRAS):
        raise ValueError(f"es de hace más de {ANOS_HACIA_ATRAS} años")
    return valor


FechaRazonable = Annotated[
    datetime,
    AfterValidator(_fecha_en_rango),
    RangoDeclarado(f"entre hace {ANOS_HACIA_ATRAS} años y mañana"),
]


# ------------------------------------------------------------------- monedas

# Lista cerrada en vez de «tres letras mayúsculas»: así `ZZZ` no llega a la
# base de datos y la app puede fiarse de lo que le devuelve la API. Añadir una
# moneda es añadir su código aquí.
MONEDAS_ADMITIDAS = frozenset(
    {
        # zona euro y entorno
        "EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF",
        "RON", "BGN", "ISK", "TRY",
        # resto del mundo con presencia habitual
        "USD", "CAD", "AUD", "NZD", "JPY", "CNY", "MAD",
        # Latinoamérica
        "MXN", "ARS", "BRL", "CLP", "COP", "PEN", "UYU",
    }
)


def _moneda_admitida(valor: str) -> str:
    if valor not in MONEDAS_ADMITIDAS:
        raise ValueError(
            f"'{valor}' no es una moneda admitida; "
            f"usa una de: {', '.join(sorted(MONEDAS_ADMITIDAS))}"
        )
    return valor


CurrencyCode = Annotated[
    str,
    Field(pattern=r"^[A-Z]{3}$"),
    AfterValidator(_moneda_admitida),
    RangoDeclarado("una de MONEDAS_ADMITIDAS"),
]


# --------------------------------------------------------------------- texto

# `min_length=1` por sí solo deja pasar "   ": tres espacios miden tres. Con
# strip_whitespace el recorte va antes que la medida, así que un nombre que
# solo son espacios se queda en cero caracteres y no entra.
MAX_NOMBRE = 255
MAX_DESCRIPCION = 500
MAX_NOMBRE_PLAN = 120

Nombre = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NOMBRE)
]
Descripcion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_DESCRIPCION),
]
NombreDePlan = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NOMBRE_PLAN),
]
# Nota libre de un pago: puede ir vacía, pero no sin fin.
NotaLibre = Annotated[str, StringConstraints(max_length=MAX_DESCRIPCION)]


# -------------------------------------------------- credenciales que solo se
#                                                     comparan, no se guardan

# La contraseña actual solo se pasa por bcrypt, que ignora lo que sobre de 72
# bytes. El tope existe para no acarrear megas hasta ahí.
MAX_CONTRASENA_RECIBIDA = 1_024
# Un refresh token de esta API ronda los 400 bytes; 4 KB deja sitio de sobra
# para cualquier versión futura del payload.
MAX_TOKEN_RECIBIDO = 4_096

ContrasenaRecibida = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_CONTRASENA_RECIBIDA)
]
TokenRecibido = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_TOKEN_RECIBIDO)
]


# ------------------------------------------------------------------- periodos

# Mes en formato «2026-07». Estaba escrito igual en recurring.py y savings.py.
Periodo = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
