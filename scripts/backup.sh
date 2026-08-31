#!/usr/bin/env bash
#
# Copia de seguridad diaria de Dividi: base de datos + fotos de tiques, en un
# único archivo cifrado con age.
#
# Retención: 7 diarias, 4 semanales, 6 mensuales.
#
# El cifrado es asimétrico a propósito: la VPS solo tiene la clave PÚBLICA, así
# que puede crear copias pero no leer las que ya existen. La clave privada vive
# fuera del servidor. Ver docs/restauracion.md.
#
# Uso:  ./backup.sh          (lo llama el cron; escribe en el log por stdout)

set -euo pipefail

# --- Configuración (todo sobreescribible por entorno) ------------------------

BACKUP_ROOT="${BACKUP_ROOT:-/opt/dividi/backups}"
RECIPIENT_FILE="${RECIPIENT_FILE:-/opt/dividi/scripts/backup-recipient.txt}"
DB_CONTAINER="${DB_CONTAINER:-dividi-db-1}"
DB_USER="${DB_USER:-dividi}"
DB_NAME="${DB_NAME:-dividi}"
RECEIPTS_VOLUME="${RECEIPTS_VOLUME:-dividi_receipts}"
# Imagen para manipular el volumen de tiques: la misma que ya corre la BD, así
# no hace falta descargar nada más.
HELPER_IMAGE="${HELPER_IMAGE:-postgres:16-alpine}"

KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-6}"
# Días que se considera vigente una prueba de restauración. Pasados estos, el
# log avisa en cada copia: un backup sin restauración probada no es un backup.
DIAS_VIGENCIA_PRUEBA="${DIAS_VIGENCIA_PRUEBA:-90}"

readonly DAILY_DIR="${BACKUP_ROOT}/diarias"
readonly WEEKLY_DIR="${BACKUP_ROOT}/semanales"
readonly MONTHLY_DIR="${BACKUP_ROOT}/mensuales"
readonly MANIFEST="${BACKUP_ROOT}/manifiesto.sha256"
readonly ULTIMA_PRUEBA="${BACKUP_ROOT}/ultima-restauracion.txt"

readonly STAMP="$(date +%Y-%m-%d_%H%M)"
readonly ARCHIVE_NAME="dividi-${STAMP}.tar.age"

# --- Utilidades --------------------------------------------------------------

log()  { echo "$(date -Is) $*"; }
fail() { echo "$(date -Is) ERROR: $*" >&2; exit 1; }

# Deja solo los $2 ficheros más recientes de $1.
prune_dir() {
  local dir="$1" keep="$2"
  [ -d "${dir}" ] || return 0
  ls -1t "${dir}" 2>/dev/null | tail -n "+$((keep + 1))" | while read -r old; do
    rm -f "${dir:?}/${old}"
    log "retención: eliminado ${dir}/${old}"
  done
}

# --- Comprobaciones previas --------------------------------------------------

command -v age >/dev/null 2>&1 || fail "falta el binario 'age' (apt install age)"
command -v docker >/dev/null 2>&1 || fail "falta docker"
[ -r "${RECIPIENT_FILE}" ] || fail "no se puede leer la clave pública en ${RECIPIENT_FILE}"

RECIPIENT="$(tr -d '[:space:]' < "${RECIPIENT_FILE}")"
[ -n "${RECIPIENT}" ] || fail "${RECIPIENT_FILE} está vacío"

docker inspect --format '{{.State.Running}}' "${DB_CONTAINER}" 2>/dev/null | grep -q true \
  || fail "el contenedor ${DB_CONTAINER} no está corriendo"

mkdir -p "${DAILY_DIR}" "${WEEKLY_DIR}" "${MONTHLY_DIR}"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# --- 1. Volcado de la base de datos ------------------------------------------

# Formato custom (-Fc): comprimido, y permite restaurar tablas sueltas.
docker exec "${DB_CONTAINER}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" -Fc \
  > "${WORK}/base-de-datos.dump" \
  || fail "pg_dump falló"

[ -s "${WORK}/base-de-datos.dump" ] || fail "el volcado salió vacío"

# Un volcado que no se puede leer no es un volcado. Se comprueba antes de
# aceptarlo como copia válida.
docker exec -i "${DB_CONTAINER}" pg_restore --list > /dev/null < "${WORK}/base-de-datos.dump" \
  || fail "el volcado está corrupto: pg_restore no puede leerlo"

log "volcado OK ($(du -h "${WORK}/base-de-datos.dump" | cut -f1))"

# --- 2. Fotos de los tiques ---------------------------------------------------

docker run --rm \
  -v "${RECEIPTS_VOLUME}:/tiques:ro" \
  -v "${WORK}:/salida" \
  "${HELPER_IMAGE}" \
  tar -czf /salida/tiques.tar.gz -C /tiques . \
  || fail "no se pudo empaquetar el volumen ${RECEIPTS_VOLUME}"

readonly N_TIQUES="$(docker run --rm -v "${RECEIPTS_VOLUME}:/tiques:ro" "${HELPER_IMAGE}" \
  sh -c 'find /tiques -type f | wc -l' | tr -d '[:space:]')"

log "tiques OK (${N_TIQUES} ficheros, $(du -h "${WORK}/tiques.tar.gz" | cut -f1))"

# --- 3. Inventario para verificar la restauración -----------------------------

# Conteo EXACTO de filas por tabla. No se usa n_live_tup porque es una
# estimación del recolector de estadísticas y en una base recién restaurada
# vale 0 hasta que pasa el ANALYZE: no serviría para comparar.
docker exec "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -tAF' ' -c "
  SELECT relname,
         (xpath('/row/c/text()',
                query_to_xml(format('SELECT count(*) AS c FROM public.%I', relname),
                             false, true, '')))[1]::text::bigint
  FROM pg_stat_user_tables
  ORDER BY relname;
" > "${WORK}/filas.txt" || fail "no se pudo inventariar las filas"

{
  echo "fecha=${STAMP}"
  echo "base_de_datos=${DB_NAME}"
  echo "postgres=$(docker exec "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -tAc 'SHOW server_version')"
  echo "ficheros_tiques=${N_TIQUES}"
} > "${WORK}/info.txt"

# Hash de cada tique, para detectar corrupción silenciosa al restaurar.
docker run --rm -v "${RECEIPTS_VOLUME}:/tiques:ro" "${HELPER_IMAGE}" \
  sh -c 'cd /tiques && find . -type f -exec sha256sum {} \; | sort' \
  > "${WORK}/tiques.sha256"

# --- 4. Empaquetar y cifrar ---------------------------------------------------

tar -cf "${WORK}/copia.tar" -C "${WORK}" \
  base-de-datos.dump tiques.tar.gz filas.txt info.txt tiques.sha256 \
  || fail "no se pudo empaquetar la copia"

age --encrypt --recipient "${RECIPIENT}" \
  --output "${WORK}/${ARCHIVE_NAME}" "${WORK}/copia.tar" \
  || fail "el cifrado con age falló"

[ -s "${WORK}/${ARCHIVE_NAME}" ] || fail "el archivo cifrado salió vacío"

mv "${WORK}/${ARCHIVE_NAME}" "${DAILY_DIR}/${ARCHIVE_NAME}"

# --- 5. Manifiesto de integridad ---------------------------------------------

(cd "${DAILY_DIR}" && sha256sum "${ARCHIVE_NAME}") >> "${MANIFEST}"

# --- 6. Retención 7 / 4 / 6 ---------------------------------------------------

# Los lunes la copia del día se promociona a semanal; el día 1, a mensual.
# Se usa enlace duro: no ocupa espacio extra y sobrevive al borrado de la diaria.
if [ "$(date +%u)" = "1" ]; then
  ln -f "${DAILY_DIR}/${ARCHIVE_NAME}" "${WEEKLY_DIR}/${ARCHIVE_NAME}"
  log "promocionada a semanal"
fi

if [ "$(date +%d)" = "01" ]; then
  ln -f "${DAILY_DIR}/${ARCHIVE_NAME}" "${MONTHLY_DIR}/${ARCHIVE_NAME}"
  log "promocionada a mensual"
fi

prune_dir "${DAILY_DIR}"   "${KEEP_DAILY}"
prune_dir "${WEEKLY_DIR}"  "${KEEP_WEEKLY}"
prune_dir "${MONTHLY_DIR}" "${KEEP_MONTHLY}"

log "copia OK -> ${DAILY_DIR}/${ARCHIVE_NAME} ($(du -h "${DAILY_DIR}/${ARCHIVE_NAME}" | cut -f1))"

# --- 7. Recordatorio de la prueba trimestral ---------------------------------

# El recordatorio vive aquí, en el log que ya se consulta, en vez de en un
# calendario aparte que nadie mira.
if [ -r "${ULTIMA_PRUEBA}" ]; then
  ultima="$(head -1 "${ULTIMA_PRUEBA}" | tr -d '[:space:]')"
  if dias_desde="$(( ( $(date +%s) - $(date -d "${ultima}" +%s) ) / 86400 ))" 2>/dev/null; then
    if [ "${dias_desde}" -gt "${DIAS_VIGENCIA_PRUEBA}" ]; then
      log "AVISO: la última restauración se probó hace ${dias_desde} días (${ultima})."
      log "AVISO: toca repetirla. Ver docs/restauracion.md."
    fi
  fi
else
  log "AVISO: no consta ninguna prueba de restauración. Ver docs/restauracion.md."
fi
