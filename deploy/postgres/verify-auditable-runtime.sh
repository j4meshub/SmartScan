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

mkdir -p "${data_root}"
sudo chown 70:70 "${data_root}"
sudo chmod 0700 "${data_root}"
cat > "${init_sql}" <<'SQL'
CREATE TABLE public.smartscan_utf8_probe (
    id integer PRIMARY KEY,
    content text NOT NULL
);
INSERT INTO public.smartscan_utf8_probe (id, content) VALUES (1, '智能扫描验证');
SQL
chmod 0444 "${init_sql}"

docker network create "${network}" >/dev/null
docker run -d \
  --name "${container}" \
  --network "${network}" \
  --network-alias postgres \
  --user 70:70 \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --tmpfs /var/run/postgresql:rw,noexec,nosuid,nodev,size=16m,mode=0777 \
  --mount "type=bind,src=${data_root},dst=/var/lib/postgresql/data" \
  --mount "type=bind,src=${init_sql},dst=/docker-entrypoint-initdb.d/10-utf8.sql,readonly" \
  --env POSTGRES_DB=smartscan \
  --env POSTGRES_USER=smartscan \
  --env POSTGRES_PASSWORD=ci-audit-only \
  --env 'POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C' \
  "${image}" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "${container}" pg_isready -U smartscan -d smartscan >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${container}" pg_isready -U smartscan -d smartscan >/dev/null

test "$(docker inspect --format '{{.Config.User}}' "${container}")" = "70:70"
test "$(docker exec "${container}" id -u)" = "70"
test "$(docker exec "${container}" id -g)" = "70"
test "$(stat -c '%u:%g' "${data_root}")" = "70:70"
test "$(docker exec "${container}" sh -ec 'test ! -e /usr/local/bin/gosu; echo absent')" = "absent"
test "$(docker exec "${container}" psql -U smartscan -d smartscan -Atc 'SHOW server_encoding')" = "UTF8"
test "$(docker exec "${container}" psql -U smartscan -d smartscan -Atc 'SELECT content FROM public.smartscan_utf8_probe WHERE id=1')" = "智能扫描验证"

docker run --rm \
  --network "${network}" \
  --env SMARTSCAN_DATABASE_URL=postgresql+psycopg://smartscan:ci-audit-only@postgres:5432/smartscan \
  --env SMARTSCAN_ENV=production \
  --env SMARTSCAN_AUTO_MIGRATE=false \
  "${ops_image}" python -m services.api.app.migrations upgrade
test -n "$(docker exec "${container}" psql -U smartscan -d smartscan -Atc 'SELECT version_num FROM alembic_version')"

docker restart "${container}" >/dev/null
for _ in $(seq 1 60); do
  if docker exec "${container}" pg_isready -U smartscan -d smartscan >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
test "$(docker exec "${container}" psql -U smartscan -d smartscan -Atc 'SELECT content FROM public.smartscan_utf8_probe WHERE id=1')" = "智能扫描验证"

docker exec "${container}" pg_dump -U smartscan -d smartscan -Fc > "${dump_file}"
test -s "${dump_file}"
docker exec "${container}" createdb -U smartscan smartscan_restore
docker exec -i "${container}" pg_restore -U smartscan -d smartscan_restore < "${dump_file}"
test "$(docker exec "${container}" psql -U smartscan -d smartscan_restore -Atc 'SELECT content FROM public.smartscan_utf8_probe WHERE id=1')" = "智能扫描验证"

docker exec "${container}" sh -ec '
  rm -rf /tmp/basebackup
  pg_basebackup --host=/var/run/postgresql --username=smartscan --pgdata=/tmp/basebackup
  pg_verifybackup /tmp/basebackup
'

docker inspect "${container}" --format '{{json .HostConfig.ReadonlyRootfs}} {{json .HostConfig.Tmpfs}}' \
  | grep -F 'true' >/dev/null
printf '%s\n' 'result=passed' 'uid_gid=70:70' 'server_encoding=UTF8' \
  'initdb=passed' 'migration=passed' 'restart_persistence=passed' \
  'pg_dump_restore=passed' 'pg_basebackup_verify=passed' \
  'read_only_tmpfs=passed'
