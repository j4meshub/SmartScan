#!/usr/bin/env bash
set -euo pipefail

image="${SMARTSCAN_POSTGRES_IMAGE:?必须设置待验证PostgreSQL镜像}"
ops_image="${SMARTSCAN_OPS_IMAGE:?必须设置待验证Ops镜像}"
work_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/smartscan-postgres-runtime.XXXXXX")"
container="smartscan-postgres-audit-${GITHUB_RUN_ID:-local}"
network="smartscan-postgres-audit-${GITHUB_RUN_ID:-local}"
data_root="${work_root}/data"
init_sql="${work_root}/10-utf8.sql"
dump_file="${work_root}/smartscan.dump"
migration_env="${work_root}/migration.env"
stage="prepare"

wait_for_final_health() {
  for _ in $(seq 1 60); do
    if test "$(docker exec "${container}" cat /proc/1/comm 2>/dev/null)" = "postgres" \
      && test "$(docker inspect --format '{{.State.Health.Status}}' "${container}")" = "healthy" \
      && docker exec "${container}" pg_isready -U smartscan -d smartscan >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

on_error() {
  exit_code=$?
  line_number=$1
  printf 'result=failed\nstage=%s\nline=%s\nexit_code=%s\n' \
    "${stage}" "${line_number}" "${exit_code}" >&2
  docker logs --tail 100 "${container}" >&2 || true
  exit "${exit_code}"
}

cleanup() {
  docker rm -f "${container}" >/dev/null 2>&1 || true
  docker network rm "${network}" >/dev/null 2>&1 || true
  case "${work_root}" in
    "${RUNNER_TEMP:-/tmp}"/smartscan-postgres-runtime.*)
      sudo rm -rf -- "${work_root}"
      ;;
    *)
      printf '%s\n' '拒绝清理非预期临时目录' >&2
      return 1
      ;;
  esac
}
trap cleanup EXIT
trap 'on_error "${LINENO}"' ERR

stage="prepare_data_directory"
mkdir -p "${data_root}"
sudo chown 70:70 "${data_root}"
sudo chmod 0700 "${data_root}"
cat > "${init_sql}" <<'SQL'
DO $smartscan$
BEGIN
    IF current_setting('server_encoding') <> 'UTF8'
       OR convert_from(convert_to('智能扫描验证', 'UTF8'), 'UTF8') <> '智能扫描验证' THEN
        RAISE EXCEPTION 'SmartScan UTF-8 initdb probe failed';
    END IF;
    RAISE NOTICE 'smartscan_utf8_init_probe=passed';
END;
$smartscan$;
SQL
chmod 0444 "${init_sql}"
python - "${migration_env}" <<'PY'
import base64
import json
import secrets
import sys
from pathlib import Path

output = Path(sys.argv[1])
hmac_id = "ci-v1"
encryption_id = "phone-ci-v1"
values = {
    "SMARTSCAN_ENV": "production",
    "SMARTSCAN_DATABASE_URL": (
        "postgresql+psycopg://smartscan:ci-audit-only@postgres:5432/smartscan"
    ),
    "SMARTSCAN_AUTO_MIGRATE": "false",
    "SMARTSCAN_STORAGE_ROOT": "/tmp/smartscan-storage",
    "SMARTSCAN_SECRET_KEY": secrets.token_urlsafe(48),
    "SMARTSCAN_PHONE_HMAC_ACTIVE_KEY_ID": hmac_id,
    "SMARTSCAN_PHONE_HMAC_PEPPERS": json.dumps(
        {hmac_id: secrets.token_urlsafe(48)}, separators=(",", ":")
    ),
    "SMARTSCAN_PHONE_ENCRYPTION_ACTIVE_KEY_ID": encryption_id,
    "SMARTSCAN_PHONE_ENCRYPTION_KEYS": json.dumps(
        {
            encryption_id: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        },
        separators=(",", ":"),
    ),
    "SMARTSCAN_SUPERADMIN_PASSWORD": secrets.token_urlsafe(32),
    "SMARTSCAN_SMS_MODE": "disabled",
    "SMARTSCAN_WECOM_MODE": "disabled",
    "SMARTSCAN_OCR_ENABLED": "true",
}
output.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
PY
chmod 0600 "${migration_env}"

stage="create_test_network"
docker network create "${network}" >/dev/null
stage="start_postgres"
docker run -d \
  --name "${container}" \
  --network "${network}" \
  --network-alias postgres \
  --user 70:70 \
  --read-only \
  --health-cmd 'pg_isready -U smartscan -d smartscan' \
  --health-interval 1s \
  --health-timeout 5s \
  --health-retries 60 \
  --health-start-period 1s \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --tmpfs /var/run/postgresql:rw,noexec,nosuid,nodev,size=16m,mode=3775,uid=70,gid=70 \
  --mount "type=bind,src=${data_root},dst=/var/lib/postgresql/data" \
  --mount "type=bind,src=${init_sql},dst=/docker-entrypoint-initdb.d/10-utf8.sql,readonly" \
  --env POSTGRES_DB=smartscan \
  --env POSTGRES_USER=smartscan \
  --env POSTGRES_PASSWORD=ci-audit-only \
  --env 'POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C' \
  "${image}" >/dev/null

stage="wait_for_health"
wait_for_final_health

stage="verify_identity_and_utf8"
test "$(docker inspect --format '{{.Config.User}}' "${container}")" = "70:70"
test "$(docker exec "${container}" id -u)" = "70"
test "$(docker exec "${container}" id -g)" = "70"
test "$(stat -c '%u:%g' "${data_root}")" = "70:70"
test "$(docker exec "${container}" sh -ec 'test ! -e /usr/local/bin/gosu; echo absent')" = "absent"
test "$(docker exec "${container}" psql -U smartscan -d smartscan -Atc 'SHOW server_encoding')" = "UTF8"

stage="run_smartscan_migrations"
docker run --rm \
  --network "${network}" \
  --env-file "${migration_env}" \
  "${ops_image}" -m services.api.app.migrations upgrade
test -n "$(docker exec "${container}" psql -U smartscan -d smartscan -Atc 'SELECT version_num FROM alembic_version')"
docker exec "${container}" psql -U smartscan -d smartscan -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE public.smartscan_utf8_probe (id integer PRIMARY KEY, content text NOT NULL); INSERT INTO public.smartscan_utf8_probe (id, content) VALUES (1, '智能扫描验证');" \
  >/dev/null
test "$(docker exec "${container}" psql -U smartscan -d smartscan -Atc 'SELECT content FROM public.smartscan_utf8_probe WHERE id=1')" = "智能扫描验证"

stage="restart_and_verify_persistence"
docker restart "${container}" >/dev/null
wait_for_final_health
test "$(docker exec "${container}" psql -U smartscan -d smartscan -Atc 'SELECT content FROM public.smartscan_utf8_probe WHERE id=1')" = "智能扫描验证"

stage="dump_and_restore"
docker exec "${container}" pg_dump -U smartscan -d smartscan -Fc > "${dump_file}"
test -s "${dump_file}"
docker exec "${container}" createdb -U smartscan smartscan_restore
docker exec -i "${container}" pg_restore -U smartscan -d smartscan_restore < "${dump_file}"
test "$(docker exec "${container}" psql -U smartscan -d smartscan_restore -Atc 'SELECT content FROM public.smartscan_utf8_probe WHERE id=1')" = "智能扫描验证"

stage="basebackup_and_verify"
docker exec "${container}" sh -ec '
  rm -rf /tmp/basebackup
  pg_basebackup --host=/var/run/postgresql --username=smartscan --pgdata=/tmp/basebackup
  pg_verifybackup /tmp/basebackup
'

stage="verify_read_only_runtime"
docker inspect "${container}" --format '{{json .HostConfig.ReadonlyRootfs}} {{json .HostConfig.Tmpfs}}' \
  | grep -F 'true' >/dev/null
printf '%s\n' 'result=passed' 'uid_gid=70:70' 'server_encoding=UTF8' \
  'initdb=passed' 'migration=passed' 'restart_persistence=passed' \
  'pg_dump_restore=passed' 'pg_basebackup_verify=passed' \
  'read_only_tmpfs=passed'
