#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

read_env_value() {
  local file="$1"
  local key="$2"
  local line=""
  local value=""

  [[ -f "$file" ]] || return 0

  line="$(grep -E "^[[:space:]]*${key}=" "$file" | tail -n 1 || true)"
  [[ -n "$line" ]] || return 0

  value="${line#*=}"
  value="${value%$'\r'}"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "$value"
}

database_name_from_url() {
  local value="$1"
  [[ -n "$value" ]] || return 0

  value="${value%%\?*}"
  value="${value%/}"
  value="${value##*/}"
  [[ -n "$value" && "$value" != *:* ]] || return 0
  printf '%s' "$value"
}

API_ENV_FILE="${API_ENV_FILE:-config/.env}"
DATABASE_URL_VALUE="${DATABASE_URL:-$(read_env_value "$API_ENV_FILE" DATABASE_URL)}"
RESOLVED_DATABASE_NAME="$(database_name_from_url "$DATABASE_URL_VALUE")"

OLD_IMAGE="${POSTGRES_OLD_IMAGE:-postgres:17.9-bookworm}"
NEW_IMAGE="${POSTGRES_IMAGE:-postgres:18.3-bookworm}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-archetype}"
OLD_VOLUME="${POSTGRES_OLD_VOLUME:-${PROJECT_NAME}_postgres}"
NEW_VOLUME="${POSTGRES_NEW_VOLUME:-${PROJECT_NAME}_postgres18}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-${RESOLVED_DATABASE_NAME:-local}}"
DB_PASSWORD="${POSTGRES_PASSWORD:-password}"
DB_NAMES=()
DATABASE_SELECTION="auto-discover all non-template databases except postgres"

if [[ -n "${POSTGRES_DATABASES:-}" ]]; then
  IFS=',' read -r -a DB_NAMES <<< "$POSTGRES_DATABASES"
  DATABASE_SELECTION="${POSTGRES_DATABASES}"
elif [[ -n "${POSTGRES_DB+x}" ]]; then
  DB_NAMES=("$POSTGRES_DB")
  DATABASE_SELECTION="${POSTGRES_DB}"
fi

BACKUP_ROOT="${POSTGRES_UPGRADE_BACKUP_ROOT:-backups/postgres-upgrade}"
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP_DIR="${POSTGRES_UPGRADE_BACKUP_DIR:-${BACKUP_ROOT}/${STAMP}}"
OLD_CONTAINER="${POSTGRES_UPGRADE_OLD_CONTAINER:-${PROJECT_NAME}-postgres17-upgrade}"
RUN_MIGRATIONS=true
ASSUME_YES=false

usage() {
  cat <<EOF
Usage: $0 [--yes] [--skip-migrate]

Migrates the local Archetype Docker Compose database from the legacy
PostgreSQL 17 volume (${OLD_VOLUME}) into the PostgreSQL 18 volume
(${NEW_VOLUME}).

Environment overrides:
  POSTGRES_OLD_IMAGE          default: ${OLD_IMAGE}
  POSTGRES_IMAGE              default: ${NEW_IMAGE}
  POSTGRES_OLD_VOLUME         default: ${OLD_VOLUME}
  POSTGRES_NEW_VOLUME         default: ${NEW_VOLUME}
  POSTGRES_USER               default: ${DB_USER}
  POSTGRES_DB                 optional single database override
  POSTGRES_DATABASES          optional comma-separated override for multiple databases
  POSTGRES_PASSWORD           default: password
  POSTGRES_UPGRADE_BACKUP_DIR default: ${BACKUP_DIR}
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      ASSUME_YES=true
      ;;
    --skip-migrate)
      RUN_MIGRATIONS=false
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

log() {
  printf '\n==> %s\n' "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

volume_exists() {
  docker volume inspect "$1" >/dev/null 2>&1
}

volume_pg_version() {
  local volume="$1"
  local image="$2"

  docker run --rm -v "${volume}:/volume:ro" "$image" bash -lc '
    if [[ -f /volume/PG_VERSION ]]; then
      cat /volume/PG_VERSION
      exit 0
    fi

    if [[ -f /volume/17/docker/PG_VERSION ]]; then
      cat /volume/17/docker/PG_VERSION
      exit 0
    fi

    if [[ -f /volume/18/docker/PG_VERSION ]]; then
      cat /volume/18/docker/PG_VERSION
      exit 0
    fi

    exit 1
  ' 2>/dev/null || true
}

wait_for_old_postgres() {
  for _ in {1..60}; do
    if docker exec "$OLD_CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  docker logs "$OLD_CONTAINER" >&2 || true
  die "Timed out waiting for temporary PostgreSQL 17 container."
}

wait_for_new_postgres() {
  for _ in {1..60}; do
    if docker compose exec -T postgres pg_isready -U "$DB_USER" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  docker compose logs postgres >&2 || true
  die "Timed out waiting for PostgreSQL 18 compose service."
}

cleanup_old_container() {
  docker rm -f "$OLD_CONTAINER" >/dev/null 2>&1 || true
}

require_command docker

if ! docker compose version >/dev/null 2>&1; then
  die "Docker Compose v2 is required."
fi

if ! volume_exists "$OLD_VOLUME"; then
  log "No legacy PostgreSQL 17 volume found (${OLD_VOLUME})."
  log "Starting a fresh PostgreSQL 18 database instead."
  POSTGRES_IMAGE="$NEW_IMAGE" docker compose up -d postgres
  wait_for_new_postgres
  docker compose exec -T postgres bash -c 'psql -U "$POSTGRES_USER" -d postgres -c "SHOW server_version;"'
  exit 0
fi

OLD_VERSION="$(volume_pg_version "$OLD_VOLUME" "$OLD_IMAGE")"
if [[ "$OLD_VERSION" != "17" ]]; then
  die "Expected ${OLD_VOLUME} to contain PostgreSQL 17 data, found '${OLD_VERSION:-unknown}'."
fi

if volume_exists "$NEW_VOLUME"; then
  NEW_VERSION="$(volume_pg_version "$NEW_VOLUME" "$NEW_IMAGE")"
  if [[ -n "$NEW_VERSION" ]]; then
    die "${NEW_VOLUME} already contains PostgreSQL ${NEW_VERSION} data. Refusing to overwrite it."
  fi
fi

cat <<EOF
This will migrate the local database:

  old image:       ${OLD_IMAGE}
  new image:       ${NEW_IMAGE}
  old volume:      ${OLD_VOLUME}
  new volume:      ${NEW_VOLUME}
  databases:       ${DATABASE_SELECTION}
  env file:        ${API_ENV_FILE}
  backup dir:      ${BACKUP_DIR}
  run migrations:  ${RUN_MIGRATIONS}

The old PostgreSQL 17 volume is not deleted.
EOF

if [[ "$ASSUME_YES" != "true" ]]; then
  printf '\nType "upgrade" to continue: '
  read -r reply
  [[ "$reply" == "upgrade" ]] || die "Aborted."
fi

mkdir -p "$BACKUP_DIR"
cat > "${BACKUP_DIR}/manifest.txt" <<EOF
timestamp=${STAMP}
old_image=${OLD_IMAGE}
new_image=${NEW_IMAGE}
old_volume=${OLD_VOLUME}
new_volume=${NEW_VOLUME}
database_selection=${DATABASE_SELECTION}
EOF

trap cleanup_old_container EXIT

log "Stopping compose services that may write to PostgreSQL."
docker compose stop api celery pg-admin postgres >/dev/null 2>&1 || true

log "Starting temporary PostgreSQL 17 container."
cleanup_old_container
docker run -d \
  --name "$OLD_CONTAINER" \
  -e POSTGRES_PASSWORD="$DB_PASSWORD" \
  -e POSTGRES_USER="$DB_USER" \
  -e POSTGRES_DB="$DB_NAME" \
  -v "${OLD_VOLUME}:/var/lib/postgresql/data" \
  "$OLD_IMAGE" >/dev/null

wait_for_old_postgres

if [[ ${#DB_NAMES[@]} -eq 0 ]]; then
  log "Discovering databases in PostgreSQL 17 volume."
  while IFS= read -r db_name; do
    [[ -n "$db_name" ]] && DB_NAMES+=("$db_name")
  done < <(
    docker exec "$OLD_CONTAINER" psql -U "$DB_USER" -d postgres -Atc \
      "SELECT datname FROM pg_database WHERE datistemplate = false AND datname <> 'postgres' ORDER BY datname;"
  )
fi

if [[ ${#DB_NAMES[@]} -eq 0 ]]; then
  die "No databases selected for migration."
fi

printf 'databases=%s\n' "${DB_NAMES[*]}" >> "${BACKUP_DIR}/manifest.txt"

docker exec "$OLD_CONTAINER" psql -U "$DB_USER" -d postgres -Atc "SHOW server_version;" \
  > "${BACKUP_DIR}/old-server-version.txt"

for db_name in "${DB_NAMES[@]}"; do
  dump_file="${BACKUP_DIR}/pg17-${db_name}.dump"

  log "Dumping PostgreSQL 17 database ${db_name} to ${dump_file}."
  docker exec "$OLD_CONTAINER" pg_dump \
    -U "$DB_USER" \
    --format=custom \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    "$db_name" > "$dump_file"

  [[ -s "$dump_file" ]] || die "Dump file is empty: ${dump_file}"
done

log "Stopping temporary PostgreSQL 17 container."
cleanup_old_container
trap - EXIT

log "Starting PostgreSQL 18 compose service."
POSTGRES_IMAGE="$NEW_IMAGE" docker compose up -d postgres
wait_for_new_postgres

docker compose exec -T postgres bash -c 'psql -U "$POSTGRES_USER" -d postgres -Atc "SHOW server_version;"' \
  > "${BACKUP_DIR}/new-server-version.txt"

if ! grep -q '^18\.' "${BACKUP_DIR}/new-server-version.txt"; then
  die "PostgreSQL 18 did not start. Version was: $(cat "${BACKUP_DIR}/new-server-version.txt")"
fi

for db_name in "${DB_NAMES[@]}"; do
  dump_file="${BACKUP_DIR}/pg17-${db_name}.dump"

  log "Ensuring target database ${db_name} exists in PostgreSQL 18."
  docker compose exec -T -e TARGET_DB="$db_name" postgres bash -c \
    'if ! psql -U "$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '\''$TARGET_DB'\''" | grep -qx 1; then createdb -U "$POSTGRES_USER" "$TARGET_DB"; fi'

  log "Restoring ${db_name} dump into PostgreSQL 18."
  docker compose exec -T -e TARGET_DB="$db_name" postgres bash -c \
    'pg_restore --exit-on-error --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" -d "$TARGET_DB"' \
    < "$dump_file"
done

log "Analyzing restored database."
docker compose exec -T postgres bash -c 'vacuumdb -U "$POSTGRES_USER" --all --analyze-in-stages'

if [[ "$RUN_MIGRATIONS" == "true" ]]; then
  log "Running Django migrations."
  docker compose run --rm api python manage.py migrate
fi

log "PostgreSQL 18 migration complete."
docker compose exec -T postgres bash -c 'psql -U "$POSTGRES_USER" -d postgres -c "SHOW server_version;"'

cat <<EOF

Backup artifacts:
  ${BACKUP_DIR}

The old PostgreSQL 17 volume remains available as:
  ${OLD_VOLUME}
EOF
