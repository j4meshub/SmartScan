#!/bin/bash
set -euo pipefail

# 只供 GitHub-hosted Linux Runner 使用。外层创建没有外部接口的网络命名空间，
# 内层启动独立 Docker daemon；导入、inspect 和身份探测始终使用同一 socket。
[[ "${GITHUB_ACTIONS:-}" == "true" && "${RUNNER_ENVIRONMENT:-}" == "github-hosted" ]] \
    || { echo "仅允许在GitHub-hosted Runner执行" >&2; exit 64; }
readonly CONTAINERD29_MODE="${SMARTSCAN_DOCKER29_CONTAINERD:-0}"
[[ "$CONTAINERD29_MODE" == "0" || "$CONTAINERD29_MODE" == "1" ]] \
    || { echo "Docker存储模式无效" >&2; exit 64; }
readonly DOCKERD_BIN="${SMARTSCAN_DOCKERD_BIN:-$(command -v dockerd)}"
[[ -x "$DOCKERD_BIN" ]] || { echo "dockerd不可执行" >&2; exit 64; }
if [[ "${SMARTSCAN_OFFLINE_NETNS:-}" != "1" ]]; then
    if [[ "$CONTAINERD29_MODE" == "1" ]]; then
        # setup-docker-action 创建的Docker 29 daemon和containerd必须处于同一
        # 主机网络命名空间，否则containerd无法启动受控探测容器。
        # daemon已由workflow配置为仅能连接本机失败代理，任何
        # Registry访问都会失败关闭；全断网导入仍由传统daemon路径验证。
        readonly setup_docker_host="$(/usr/bin/docker context inspect --format '{{.Endpoints.docker.Host}}')"
        [[ "$setup_docker_host" == unix://* ]] \
            || { echo "Docker 29 socket不是本机Unix socket" >&2; exit 64; }
        exec sudo --preserve-env=GITHUB_WORKSPACE,RUNNER_TEMP,GITHUB_ACTIONS,RUNNER_ENVIRONMENT \
            env SMARTSCAN_OFFLINE_NETNS=1 SMARTSCAN_EXTERNAL_DOCKER=1 \
            SMARTSCAN_DOCKER29_CONTAINERD=1 DOCKER_HOST="$setup_docker_host" \
            GITHUB_WORKSPACE="$GITHUB_WORKSPACE" RUNNER_TEMP="$RUNNER_TEMP" \
            GITHUB_ACTIONS="$GITHUB_ACTIONS" RUNNER_ENVIRONMENT="$RUNNER_ENVIRONMENT" bash "$0"
    fi
    export SMARTSCAN_DOCKERD_BIN="$DOCKERD_BIN" SMARTSCAN_DOCKER29_CONTAINERD="$CONTAINERD29_MODE"
    exec sudo --preserve-env=GITHUB_WORKSPACE,RUNNER_TEMP,GITHUB_ACTIONS,RUNNER_ENVIRONMENT,SMARTSCAN_DOCKERD_BIN,SMARTSCAN_DOCKER29_CONTAINERD \
        unshare --net --mount-proc \
        env SMARTSCAN_OFFLINE_NETNS=1 GITHUB_WORKSPACE="$GITHUB_WORKSPACE" \
        RUNNER_TEMP="$RUNNER_TEMP" GITHUB_ACTIONS="$GITHUB_ACTIONS" \
        RUNNER_ENVIRONMENT="$RUNNER_ENVIRONMENT" \
        SMARTSCAN_DOCKERD_BIN="$DOCKERD_BIN" \
        SMARTSCAN_DOCKER29_CONTAINERD="$CONTAINERD29_MODE" bash "$0"
fi

readonly ARCHIVE_ROOT="$GITHUB_WORKSPACE/.smartscan-offline-transfer/images/smartscan-uat-2026-11-24"
readonly RUNTIME_ROOT="$RUNNER_TEMP/smartscan-offline-docker"
readonly DOCKER_SOCKET="$RUNTIME_ROOT/docker.sock"
readonly DOCKER_HOST_VALUE="unix://$DOCKER_SOCKET"

readonly EXTERNAL_DOCKER="${SMARTSCAN_EXTERNAL_DOCKER:-0}"
DOCKERD_PID=""
if [[ "$EXTERNAL_DOCKER" == "0" ]]; then
    /usr/sbin/ip link set lo up
    /usr/bin/mkdir -p "$RUNTIME_ROOT/data" "$RUNTIME_ROOT/exec"
    "$DOCKERD_BIN" \
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
        --containerd-namespace=smartscan-ci-legacy \
        --containerd-plugins-namespace=smartscan-ci-legacy-plugins \
        --storage-driver=vfs \
        >"$RUNTIME_ROOT/dockerd.log" 2>&1 &
    DOCKERD_PID=$!
    export DOCKER_HOST="$DOCKER_HOST_VALUE"
fi

cleanup() {
    /usr/bin/docker compose --project-name smartscan-uat \
        --env-file /etc/smartscan/uat/deploy.env \
        --env-file /etc/smartscan/uat/local-images.env \
        -f "$GITHUB_WORKSPACE/deploy/compose/docker-compose.uat.yml" \
        stop nginx worker-cpu-2 worker-cpu-1 api migrate postgres >/dev/null 2>&1 || true
    for network in smartscan-uat-data smartscan-uat-edge smartscan-uat-egress smartscan-ci-sentinel; do
        /usr/bin/docker network rm "$network" >/dev/null 2>&1 || true
    done
    if [[ -n "$DOCKERD_PID" ]]; then
        /bin/kill "$DOCKERD_PID" 2>/dev/null || true
        wait "$DOCKERD_PID" 2>/dev/null || true
    fi
    /bin/rm -rf /etc/smartscan/uat /mnt/data/smartscan/uat
    /bin/rm -rf "$RUNTIME_ROOT"
}
trap cleanup EXIT

for _ in $(seq 1 60); do
    if /usr/bin/docker info >/dev/null 2>&1; then
        break
    fi
    if [[ -n "$DOCKERD_PID" ]] && ! /bin/kill -0 "$DOCKERD_PID" 2>/dev/null; then
        /usr/bin/tail -n 80 "$RUNTIME_ROOT/dockerd.log" >&2
        exit 1
    fi
    /usr/bin/sleep 1
done
/usr/bin/docker info >/dev/null
if [[ "$CONTAINERD29_MODE" == "1" ]]; then
    [[ "$(/usr/bin/docker version --format '{{.Server.Version}}')" == "29.0.2" ]] \
        || { printf 'Docker Server版本不是29.0.2\n' >&2; exit 1; }
    /usr/bin/docker info --format '{{json .DriverStatus}}' \
        | /bin/grep -F 'io.containerd.snapshotter.v1' >/dev/null \
        || { printf '未启用containerd image store\n' >&2; exit 1; }
fi

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

[[ "$(/usr/bin/docker network inspect --format '{{.Name}}' smartscan-ci-sentinel)" == "smartscan-ci-sentinel" ]] \
    || { printf '隔离Docker哨兵网络丢失\n' >&2; exit 1; }
mapfile -t postgres_ids < <(
    /usr/bin/docker ps -q \
        --filter label=com.docker.compose.project=smartscan-uat \
        --filter label=com.docker.compose.service=postgres
)
[[ "${#postgres_ids[@]}" -eq 1 ]] \
    || { printf 'PostgreSQL容器数量异常：%s\n' "${#postgres_ids[@]}" >&2; exit 1; }
postgres_health="starting"
for _ in $(seq 1 30); do
    postgres_health="$(
        /usr/bin/docker inspect \
            --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
            "${postgres_ids[0]}"
    )"
    [[ "$postgres_health" == "healthy" ]] && break
    /usr/bin/sleep 2
done
[[ "$postgres_health" == "healthy" ]] \
    || { printf 'PostgreSQL健康状态异常：%s\n' "$postgres_health" >&2; exit 1; }
mapfile -t migrate_ids < <(
    /usr/bin/docker ps -a -q \
        --filter label=com.docker.compose.project=smartscan-uat \
        --filter label=com.docker.compose.service=migrate
)
[[ "${#migrate_ids[@]}" -eq 1 ]] \
    || { printf '迁移服务容器数量异常：%s\n' "${#migrate_ids[@]}" >&2; exit 1; }
[[ "$(/usr/bin/docker inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "${migrate_ids[0]}")" == "exited:0" ]] \
    || { printf '迁移服务未以成功状态保留诊断对象\n' >&2; exit 1; }
mapfile -t core_services < <(
    /usr/bin/docker ps --format '{{.Label "com.docker.compose.service"}}' \
        --filter label=com.docker.compose.project=smartscan-uat
)
[[ "$(printf '%s\n' "${core_services[@]}" | /usr/bin/sort | /usr/bin/tr '\n' ' ')" == \
    "api nginx postgres worker-cpu-1 worker-cpu-2 " ]] \
    || { printf '核心服务集合异常\n' >&2; exit 1; }
printf '{"containerd_image_store":%s,"daemon_network":"isolated","images":6,"migration":"20261022_0024","state_machine":"nginx_activation_confirmation","status":"passed"}\n' \
    "$([[ "$CONTAINERD29_MODE" == "1" ]] && printf true || printf false)"
