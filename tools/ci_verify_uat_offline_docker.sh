#!/bin/bash
set -euo pipefail

# 只供 GitHub-hosted Linux Runner 使用。外层创建没有外部接口的网络命名空间，
# 内层启动独立 Docker daemon；导入、inspect 和身份探测始终使用同一 socket。
[[ "${GITHUB_ACTIONS:-}" == "true" && "${RUNNER_ENVIRONMENT:-}" == "github-hosted" ]] \
    || { echo "仅允许在GitHub-hosted Runner执行" >&2; exit 64; }
if [[ "${SMARTSCAN_OFFLINE_NETNS:-}" != "1" ]]; then
    exec sudo --preserve-env=GITHUB_WORKSPACE,RUNNER_TEMP,GITHUB_ACTIONS,RUNNER_ENVIRONMENT \
        unshare --net --mount-proc \
        env SMARTSCAN_OFFLINE_NETNS=1 GITHUB_WORKSPACE="$GITHUB_WORKSPACE" \
        RUNNER_TEMP="$RUNNER_TEMP" GITHUB_ACTIONS="$GITHUB_ACTIONS" \
        RUNNER_ENVIRONMENT="$RUNNER_ENVIRONMENT" bash "$0"
fi

readonly ARCHIVE_ROOT="$GITHUB_WORKSPACE/.smartscan-offline-transfer/images/smartscan-uat-2026-11-24"
readonly RUNTIME_ROOT="$RUNNER_TEMP/smartscan-offline-docker"
readonly DOCKER_SOCKET="$RUNTIME_ROOT/docker.sock"
readonly DOCKER_HOST_VALUE="unix://$DOCKER_SOCKET"

/usr/sbin/ip link set lo up
/usr/bin/mkdir -p "$RUNTIME_ROOT/data" "$RUNTIME_ROOT/exec"

/usr/bin/dockerd \
    --host="$DOCKER_HOST_VALUE" \
    --data-root="$RUNTIME_ROOT/data" \
    --exec-root="$RUNTIME_ROOT/exec" \
    --pidfile="$RUNTIME_ROOT/docker.pid" \
    --bridge=none \
    --iptables=false \
    --ip6tables=false \
    --ip-forward=false \
    --ip-masq=false \
    --userland-proxy=false \
    --storage-driver=vfs \
    >"$RUNTIME_ROOT/dockerd.log" 2>&1 &
readonly DOCKERD_PID=$!

cleanup() {
    /usr/bin/docker compose --project-name smartscan-uat \
        --env-file /etc/smartscan/uat/deploy.env \
        --env-file /etc/smartscan/uat/local-images.env \
        -f "$GITHUB_WORKSPACE/deploy/compose/docker-compose.uat.yml" \
        stop postgres >/dev/null 2>&1 || true
    /bin/kill "$DOCKERD_PID" 2>/dev/null || true
    wait "$DOCKERD_PID" 2>/dev/null || true
    /bin/rm -rf /etc/smartscan/uat /mnt/data/smartscan/uat
    /bin/rm -rf "$RUNTIME_ROOT"
}
trap cleanup EXIT

export DOCKER_HOST="$DOCKER_HOST_VALUE"
for _ in $(seq 1 60); do
    if /usr/bin/docker info >/dev/null 2>&1; then
        break
    fi
    if ! /bin/kill -0 "$DOCKERD_PID" 2>/dev/null; then
        /usr/bin/tail -n 80 "$RUNTIME_ROOT/dockerd.log" >&2
        exit 1
    fi
    /usr/bin/sleep 1
done
/usr/bin/docker info >/dev/null

/usr/bin/docker network create --driver bridge --subnet 172.31.250.0/28 smartscan-ci-sentinel >/dev/null
/usr/bin/docker network create --driver bridge --internal \
    --subnet 172.30.10.0/24 --gateway 172.30.10.1 \
    --label com.docker.compose.project=smartscan-uat \
    --label com.docker.compose.network=data \
    --label com.smartscan.environment=uat smartscan-uat-data >/dev/null
/usr/bin/docker network create --driver bridge --internal \
    --subnet 172.30.11.0/24 --gateway 172.30.11.1 \
    --label com.docker.compose.project=smartscan-uat \
    --label com.docker.compose.network=edge \
    --label com.smartscan.environment=uat smartscan-uat-edge >/dev/null
/usr/bin/docker network create --driver bridge \
    --subnet 172.30.12.0/24 --gateway 172.30.12.1 \
    --label com.docker.compose.project=smartscan-uat \
    --label com.docker.compose.network=egress \
    --label com.smartscan.environment=uat smartscan-uat-egress >/dev/null

export PYTHONPATH="$GITHUB_WORKSPACE"
/usr/bin/python3 "$GITHUB_WORKSPACE/tools/ci_verify_uatctl_checkpoint.py"

[[ "$(/usr/bin/docker network inspect --format '{{.Name}}' smartscan-ci-sentinel)" == "smartscan-ci-sentinel" ]]
[[ "$(/usr/bin/docker ps --filter name=smartscan-uat-postgres --format '{{.Status}}')" == *"healthy"* ]]
[[ "$(/usr/bin/docker ps -a --filter name=smartscan-uat-migrate --format '{{.Names}}' | /usr/bin/wc -l)" -eq 0 ]]
printf '{"daemon_network":"isolated","images":6,"state_machine":"migration_confirmation","status":"passed"}\n'
