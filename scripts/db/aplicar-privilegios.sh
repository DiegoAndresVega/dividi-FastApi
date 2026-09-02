#!/usr/bin/env bash
#
# Crea (o corrige) el rol con el que se conecta la API y le deja solo permisos
# de datos. Idempotente: se puede repetir sin miedo.
#
# Después de aplicarlo comprueba lo que importa contra la base real: que el rol
# entra, que no puede crear tablas y que no puede borrarlas.
#
# Uso:
#   CLAVE_APP='...' ./scripts/db/aplicar-privilegios.sh
#
# Por defecto apunta al despliegue (usuario y base `dividi`). Para el compose
# de desarrollo:
#   DB_USER=gastos DB_NAME=gastos ROL_APP=gastos_app CLAVE_APP=gastos_app \
#     ./scripts/db/aplicar-privilegios.sh

set -euo pipefail

# --- Configuración (todo sobreescribible por entorno) ------------------------

DB_CONTAINER="${DB_CONTAINER:-dividi-db-1}"
# El dueño de las tablas: es quien tiene que ejecutar el script, porque los
# permisos por defecto se aplican a lo que cree el rol que los fija.
DB_USER="${DB_USER:-dividi}"
DB_NAME="${DB_NAME:-dividi}"
ROL_APP="${ROL_APP:-dividi_app}"
CLAVE_APP="${CLAVE_APP:?define CLAVE_APP con la contraseña del rol de la API}"

readonly SQL="$(dirname "$0")/privilegios.sql"
readonly TABLA_DE_PRUEBA="prueba_de_privilegios"

# --- Utilidades --------------------------------------------------------------

# Ejecuta SQL como dueño de la base.
duena() {
    docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -q \
        -U "$DB_USER" -d "$DB_NAME" "$@"
}

# Ejecuta SQL como el rol de la API. Devuelve el error en stdout para poder
# comprobarlo, y nunca aborta el script: aquí fallar es lo que se espera.
como_app() {
    docker exec -i -e PGPASSWORD="$CLAVE_APP" "$DB_CONTAINER" psql -q \
        -U "$ROL_APP" -d "$DB_NAME" -h 127.0.0.1 -c "$1" 2>&1 || true
}

# Postgres rechaza cada cosa con su propio mensaje: falta de permiso para
# crear en el esquema, y falta de propiedad para alterar o borrar una tabla.
# Se aceptan los dos, en inglés y en español, porque el idioma depende del
# locale del contenedor.
readonly RECHAZOS='permission denied|permiso denegado|must be owner|debe ser el propietario'

# Falla el script si la salida no es un rechazo de la base de datos.
exigir_rechazo() {
    local descripcion="$1" salida="$2"
    if grep -qiE "$RECHAZOS" <<<"$salida"; then
        echo "  ok · $descripcion: denegado"
        return 0
    fi
    echo "  FALLO · $descripcion no fue denegado:" >&2
    echo "$salida" >&2
    exit 1
}

# --- Aplicar -----------------------------------------------------------------

echo "Aplicando privilegios a '$ROL_APP' en $DB_NAME ($DB_CONTAINER)..."
duena -v rol_app="$ROL_APP" -v clave_app="$CLAVE_APP" -f - <"$SQL"

# --- Comprobar ---------------------------------------------------------------

echo "Comprobando lo que el rol puede y no puede hacer:"

entrada="$(como_app 'SELECT 1')"
if ! grep -q "1 row" <<<"$entrada"; then
    echo "  FALLO · el rol no consigue conectarse:" >&2
    echo "$entrada" >&2
    exit 1
fi
echo "  ok · entra y consulta"

exigir_rechazo "CREATE TABLE" \
    "$(como_app "CREATE TABLE ${TABLA_DE_PRUEBA} (x int)")"

# DROP sobre una tabla real, dentro de una transacción que se deshace: si algún
# día el permiso estuviera mal, el ROLLBACK evita el estropicio.
if [[ -n "$(duena -tAc "SELECT to_regclass('public.users')")" ]]; then
    exigir_rechazo "DROP TABLE users" \
        "$(como_app 'BEGIN; DROP TABLE users; ROLLBACK;')"
    exigir_rechazo "TRUNCATE users" \
        "$(como_app 'BEGIN; TRUNCATE users; ROLLBACK;')"
    exigir_rechazo "ALTER TABLE users" \
        "$(como_app 'BEGIN; ALTER TABLE users ADD COLUMN colada text; ROLLBACK;')"
    # Y lo que sí tiene que poder: cambiar y borrar filas. También dentro de
    # una transacción que se deshace, para no dejar rastro.
    escritura="$(como_app "BEGIN; UPDATE users SET email = email WHERE id = -1; DELETE FROM users WHERE id = -1; ROLLBACK;")"
    if grep -qiE "$RECHAZOS" <<<"$escritura"; then
        echo "  FALLO · el rol no puede escribir:" >&2
        echo "$escritura" >&2
        exit 1
    fi
    echo "  ok · escribe filas"
    # Un INSERT necesita además la secuencia que da el id. Gastar un valor solo
    # deja un hueco en la numeración, que es inofensivo.
    secuencia="$(como_app "SELECT nextval(pg_get_serial_sequence('public.users','id'))")"
    if grep -qiE "$RECHAZOS" <<<"$secuencia"; then
        echo "  FALLO · el rol no puede usar la secuencia de ids:" >&2
        echo "$secuencia" >&2
        exit 1
    fi
    echo "  ok · usa las secuencias de ids"
else
    echo "  (sin tablas todavía: el DROP se comprueba tras la primera migración)"
fi

echo "Listo."
