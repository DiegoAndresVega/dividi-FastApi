"""Restablece la contraseña de una cuenta desde el servidor.

Se usa cuando alguien pierde su contraseña: la API solo deja cambiarla
sabiendo la actual (POST /me/password) y el hash bcrypt no es reversible,
así que la única salida es escribir un hash nuevo en la base de datos.

Uso, dentro del contenedor de la API:

    # ver qué cuentas existen
    python scripts/reset_password.py

    # poner una contraseña nueva
    RESET_EMAIL=ana@example.com RESET_PASSWORD=nuevaclave123 \\
        python scripts/reset_password.py

La contraseña viaja por variable de entorno para no quedarse escrita en el
historial de comandos del servidor.
"""

import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.security import hash_password

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 72  # tope de bcrypt, el mismo que valida la API


def listar_cuentas(db: Session) -> int:
    """Muestra las cuentas registradas para saber cuál restablecer."""
    usuarios = db.scalars(select(User).order_by(User.created_at)).all()
    if not usuarios:
        print("No hay ninguna cuenta registrada.")
        return 0
    print(f"{len(usuarios)} cuenta(s):")
    for usuario in usuarios:
        creada = usuario.created_at.strftime("%d/%m/%Y")
        print(f"  - {usuario.email}  ({usuario.name}, alta {creada})")
    print(
        "\nPara cambiar una:\n"
        "  RESET_EMAIL=... RESET_PASSWORD=... python scripts/reset_password.py"
    )
    return 0


def restablecer(db: Session, email: str, password: str) -> int:
    """Escribe el hash de la contraseña nueva. Devuelve el código de salida."""
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        print(
            f"ERROR: la contraseña debe tener entre {PASSWORD_MIN_LENGTH} y "
            f"{PASSWORD_MAX_LENGTH} caracteres.",
            file=sys.stderr,
        )
        return 1

    usuario = db.scalar(select(User).where(User.email == email))
    if usuario is None:
        print(f"ERROR: no hay ninguna cuenta con el email {email}.", file=sys.stderr)
        return 1

    usuario.hashed_password = hash_password(password)
    db.commit()
    print(f"Contraseña restablecida para {usuario.email} ({usuario.name}).")
    print("Ya puedes iniciar sesión en la app con la contraseña nueva.")
    return 0


def main() -> int:
    from app.database import SessionLocal

    email = os.environ.get("RESET_EMAIL", "").strip()
    password = os.environ.get("RESET_PASSWORD", "")
    db = SessionLocal()
    try:
        if not email or not password:
            return listar_cuentas(db)
        return restablecer(db, email, password)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
