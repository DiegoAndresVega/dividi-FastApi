#!/usr/bin/env bash
#
# Prueba de restauración de una copia de Dividi en una máquina limpia.
#
# Levanta un PostgreSQL 16 vacío en Docker, restaura la copia dentro, y verifica
# que lo restaurado coincide con lo que había: fila a fila en cada tabla, y hash
# a hash en cada tique.
#
# No toca producción. No toca ninguna base de datos existente.
#
# Uso:  ./restaurar-prueba.sh <copia.tar.age> <clave-privada.age>

set -euo pipefail

readonly ARCHIVE="${1:?falta la ruta de la copia .tar.age}"
readonly IDENTITY="${2:?falta la ruta de la clave privada age}"

readonly CONTAINER="dividi-restauracion-prueba"
readonly DB_USER="dividi"
readonly DB_NAME="dividi"
readonly IMAGE="postgres:16-alpine"
readonly ARRANQUE_MAX_INTENTOS=60

log()  { echo "$(date +%H:%M:%S) $*"; }
fail() { echo "$(date +%H:%M:%S) FALLO: $*" >&2; exit 1; }

[ -r "${ARCHIVE}" ]  || fail "no se puede leer ${ARCHIVE}"
[ -r "${IDENTITY}" ] || fail "no se puede leer ${IDENTITY}"
command -v age >/dev/null    || fail "falta el binario 'age' (brew install age)"
command -v docker >/dev/null || fail "falta docker"

WORK="$(mktemp -d)"
limpiar() {
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  rm -rf "${WORK}"
}
trap limpiar EXIT

readonly INICIO="$(date +%s)"

# --- 1. Descifrar y desempaquetar --------------------------------------------

log "descifrando ${ARCHIVE##*/}"
age --decrypt --identity "${IDENTITY}" --output "${WORK}/copia.tar" "${ARCHIVE}" \
  || fail "no se pudo descifrar (¿clave privada equivocada?)"

tar -xf "${WORK}/copia.tar" -C "${WORK}" || fail "el archivo está corrupto"

for f in base-de-datos.dump tiques.tar.gz filas.txt info.txt tiques.sha256; do
  [ -f "${WORK}/${f}" ] || fail "falta ${f} dentro de la copia"
done

log "contenido de la copia:"
sed 's/^/    /' "${WORK}/info.txt"

# --- 2. PostgreSQL limpio ------------------------------------------------------

docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true

log "levantando ${IMAGE} vacío"
docker run -d --name "${CONTAINER}" \
  -e POSTGRES_USER="${DB_USER}" \
  -e POSTGRES_PASSWORD=prueba \
  -e POSTGRES_DB="${DB_NAME}" \
  "${IMAGE}" >/dev/null || fail "no se pudo arrancar el contenedor"

# No vale pg_isready: durante la inicialización Postgres levanta un servidor
# temporal que ya responde, pero en el que la base todavía no existe. Se espera
# a que la base real acepte una consulta.
intento=0
until docker exec "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -c 'SELECT 1' >/dev/null 2>&1; do
  intento=$((intento + 1))
  [ "${intento}" -lt "${ARRANQUE_MAX_INTENTOS}" ] || fail "el contenedor no arrancó a tiempo"
  sleep 1
done
log "contenedor listo (${intento}s)"

# --- 3. Restaurar ---------------------------------------------------------------

log "restaurando el volcado"
docker exec -i "${CONTAINER}" \
  pg_restore -U "${DB_USER}" -d "${DB_NAME}" --no-owner --no-privileges \
  < "${WORK}/base-de-datos.dump" \
  || fail "pg_restore no pudo restaurar el volcado"

# --- 4. Verificar la base de datos ----------------------------------------------

docker exec "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -tAF' ' -c "
  SELECT relname,
         (xpath('/row/c/text()',
                query_to_xml(format('SELECT count(*) AS c FROM public.%I', relname),
                             false, true, '')))[1]::text::bigint
  FROM pg_stat_user_tables
  ORDER BY relname;
" > "${WORK}/filas-restauradas.txt"

if diff -u <(sort "${WORK}/filas.txt") <(sort "${WORK}/filas-restauradas.txt") > "${WORK}/diff-filas.txt"; then
  log "OK · las $(wc -l < "${WORK}/filas.txt" | tr -d ' ') tablas coinciden fila a fila"
  sed 's/^/    /' "${WORK}/filas-restauradas.txt"
else
  cat "${WORK}/diff-filas.txt"
  fail "el conteo de filas NO coincide con el de la copia"
fi

# --- 5. Verificar los tiques -----------------------------------------------------

mkdir -p "${WORK}/tiques"
tar -xzf "${WORK}/tiques.tar.gz" -C "${WORK}/tiques" || fail "el tar de tiques está corrupto"

(cd "${WORK}/tiques" && find . -type f -exec shasum -a 256 {} \; | sed 's/  */  /' | sort) \
  > "${WORK}/tiques-restaurados.sha256"

readonly N_ESPERADOS="$(grep -c . "${WORK}/tiques.sha256" || true)"
readonly N_OBTENIDOS="$(grep -c . "${WORK}/tiques-restaurados.sha256" || true)"

if [ "${N_ESPERADOS}" != "${N_OBTENIDOS}" ]; then
  fail "tiques: se esperaban ${N_ESPERADOS} ficheros y hay ${N_OBTENIDOS}"
fi

if [ "${N_ESPERADOS}" -eq 0 ]; then
  log "OK · no había tiques que restaurar (0 ficheros en origen)"
elif diff -u <(sort "${WORK}/tiques.sha256") <(sort "${WORK}/tiques-restaurados.sha256") > /dev/null; then
  log "OK · los ${N_ESPERADOS} tiques coinciden hash a hash"
else
  diff -u <(sort "${WORK}/tiques.sha256") <(sort "${WORK}/tiques-restaurados.sha256") || true
  fail "el contenido de algún tique NO coincide"
fi

# --- 6. Resultado -----------------------------------------------------------------

readonly SEGUNDOS=$(( $(date +%s) - INICIO ))

echo
echo "================================================================"
echo " RESTAURACIÓN VERIFICADA"
echo "   copia:    ${ARCHIVE##*/}"
echo "   probada:  $(date +%Y-%m-%d\ %H:%M)"
echo "   duración: ${SEGUNDOS}s"
echo "   tablas:   $(wc -l < "${WORK}/filas.txt" | tr -d ' ') coinciden"
echo "   tiques:   ${N_ESPERADOS} coinciden"
echo "================================================================"
