#!/bin/bash
set -euo pipefail

# 只供 GitHub-hosted Linux Runner 使用。外层创建没有外部接口的网络命名空间，
# 内层启动独立 Docker daemon；导入、inspect 和身份探测始终使用同一 socket。
if [[ "${SMARTSCAN_OFFLINE_NETNS:-}" != "1" ]]; then
    exec sudo --preserve-env=GITHUB_WORKSPACE,RUNNER_TEMP \
        unshare --net --mount-proc \
        env SMARTSCAN_OFFLINE_NETNS=1 GITHUB_WORKSPACE="$GITHUB_WORKSPACE" \
        RUNNER_TEMP="$RUNNER_TEMP" bash "$0"
fi

readonly ARCHIVE_ROOT="$GITHUB_WORKSPACE/.smartscan-offline-transfer/images/smartscan-uat-2026-11-24"
readonly RUNTIME_ROOT="$RUNNER_TEMP/smartscan-offline-docker"
readonly DOCKER_SOCKET="$RUNTIME_ROOT/docker.sock"
readonly DOCKER_HOST_VALUE="unix://$DOCKER_SOCKET"
readonly MAP_FILE="$ARCHIVE_ROOT/release-map.json"

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
    /bin/kill "$DOCKERD_PID" 2>/dev/null || true
    wait "$DOCKERD_PID" 2>/dev/null || true
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

while read -r archive tag image_id; do
    /usr/bin/docker load --input "$ARCHIVE_ROOT/$archive"
    [[ "$(/usr/bin/docker image inspect --format '{{.Id}}' "$tag")" == "$image_id" ]]
done < <(/usr/bin/python3 - "$MAP_FILE" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for image in value["images"]:
    print(image["archive_name"], image["local_tag"], image["image_id"])
PY
)

while read -r service tag; do
    common=(
        --rm --network none --read-only --cap-drop ALL
        --security-opt no-new-privileges:true --cpus 0.10 --memory 32m
        --pids-limit 16 --entrypoint /usr/bin/id
    )
    /usr/bin/docker run --name "smartscan-uat-ci-${service}-uid" "${common[@]}" "$tag" -u
    /usr/bin/docker run --name "smartscan-uat-ci-${service}-gid" "${common[@]}" "$tag" -g
done < <(/usr/bin/python3 - "$MAP_FILE" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for image in value["images"]:
    print(image["service"], image["local_tag"])
PY
)

printf '{"daemon_network":"isolated","images":6,"status":"passed"}\n'
