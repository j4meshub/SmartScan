#!/bin/bash
set -euo pipefail

# 在一次性的GitHub Ubuntu Runner/UTS命名空间内验证真实root所有权、sudo和精确模式。
[[ "${EUID}" -eq 0 ]] || { echo "需要root运行权限契约集成测试" >&2; exit 1; }
[[ "$(hostname -s)" == "ctiecaiserver" ]] || { echo "hostname_namespace_missing" >&2; exit 1; }

readonly ROOT="${GITHUB_WORKSPACE:?}"
readonly INSTALL_ROOT="/usr/local/libexec/smartscan"
readonly SUDOERS_FILE="/etc/sudoers.d/smartscan-uatctl"
readonly CANDIDATE="${INSTALL_ROOT}/uat-2026-11-26-worker-fix.json"
readonly INTERNAL_JSON="/tmp/smartscan-uatctl-internal-state.json"

cleanup() {
  rm -f "$INTERNAL_JSON" "${CANDIDATE}.hardlink"
  rm -f "$SUDOERS_FILE"
  rm -rf "$INSTALL_ROOT"
}
trap cleanup EXIT

id szhzx >/dev/null 2>&1 || useradd --no-create-home --shell /usr/sbin/nologin szhzx
install -d -o root -g root -m 0755 "$INSTALL_ROOT"
install -o root -g root -m 0755 "$ROOT/deploy/ops/smartscan-uatctl" "$INSTALL_ROOT/smartscan-uatctl"
install -o root -g root -m 0755 "$ROOT/deploy/ops/smartscan_uatctl.py" "$INSTALL_ROOT/smartscan_uatctl.py"
install -o root -g root -m 0644 "$ROOT/deploy/ops/smartscan_uat_validators.py" "$INSTALL_ROOT/smartscan_uat_validators.py"
install -o root -g root -m 0644 "$ROOT/deploy/compose/docker-compose.uat.yml" "$INSTALL_ROOT/docker-compose.uat.yml"
install -o root -g root -m 0644 "$ROOT/deploy/nginx/shared-8077-smartscan-location.conf.template" "$INSTALL_ROOT/shared-8077-smartscan-location.conf"
install -o root -g root -m 0644 "$ROOT/deploy/releases/uat-2026-11-26-worker-fix.json" "$CANDIDATE"
install -o root -g root -m 0440 "$ROOT/deploy/sudoers/smartscan-uatctl" "$SUDOERS_FILE"
visudo -cf "$SUDOERS_FILE" >/dev/null

# 包装器和Python加载器都必须接受唯一的root:root 0644候选清单。
sudo -u szhzx sudo -n "$INSTALL_ROOT/smartscan-uatctl" status >/tmp/smartscan-uatctl-status.json
python3 - "$CANDIDATE" "$INTERNAL_JSON" <<'PY'
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/usr/local/libexec/smartscan")
import smartscan_uatctl as uatctl

candidate = Path(sys.argv[1])
internal = Path(sys.argv[2])
value = uatctl._load_json(
    candidate,
    policy=uatctl.FixedFilePolicy.CANDIDATE_RELEASE_PUBLIC_ROOT_0644,
)
assert value["schema_version"] == "1.1"
internal.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")
os.chown(internal, 0, 0)
os.chmod(internal, 0o600)
assert uatctl._load_json(
    internal,
    policy=uatctl.FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
)["schema_version"] == "1.0"
os.chmod(internal, 0o644)
try:
    uatctl._load_json(
        internal,
        policy=uatctl.FixedFilePolicy.INTERNAL_STATE_ROOT_0600,
    )
except uatctl.ControllerError as exc:
    assert "fixed_json_mode_invalid" in str(exc)
else:
    raise AssertionError("sensitive_json_0644_was_accepted")
PY

for mode in 600 640 664 777; do
  chmod "$mode" "$CANDIDATE"
  if sudo -u szhzx sudo -n "$INSTALL_ROOT/smartscan-uatctl" status >/dev/null 2>&1; then
    echo "candidate_mode_was_accepted:${mode}" >&2
    exit 1
  fi
done
chmod 0644 "$CANDIDATE"

chown szhzx:szhzx "$CANDIDATE"
if sudo -u szhzx sudo -n "$INSTALL_ROOT/smartscan-uatctl" status >/dev/null 2>&1; then
  echo "candidate_nonroot_owner_was_accepted" >&2
  exit 1
fi
chown root:root "$CANDIDATE"

ln "$CANDIDATE" "${CANDIDATE}.hardlink"
if sudo -u szhzx sudo -n "$INSTALL_ROOT/smartscan-uatctl" status >/dev/null 2>&1; then
  echo "candidate_hardlink_was_accepted" >&2
  exit 1
fi
rm -f "${CANDIDATE}.hardlink"

mv "$CANDIDATE" "${CANDIDATE}.original"
ln -s "${CANDIDATE}.original" "$CANDIDATE"
if sudo -u szhzx sudo -n "$INSTALL_ROOT/smartscan-uatctl" status >/dev/null 2>&1; then
  echo "candidate_symlink_was_accepted" >&2
  exit 1
fi
rm -f "$CANDIDATE"
mv "${CANDIDATE}.original" "$CANDIDATE"

mv "$CANDIDATE" "${CANDIDATE}.original"
mkdir "$CANDIDATE"
if sudo -u szhzx sudo -n "$INSTALL_ROOT/smartscan-uatctl" status >/dev/null 2>&1; then
  echo "candidate_directory_was_accepted" >&2
  exit 1
fi
rmdir "$CANDIDATE"
mv "${CANDIDATE}.original" "$CANDIDATE"

cp -a "$CANDIDATE" "${CANDIDATE}.original"
printf '\n' >> "$CANDIDATE"
if sudo -u szhzx sudo -n "$INSTALL_ROOT/smartscan-uatctl" status >/dev/null 2>&1; then
  echo "candidate_digest_mismatch_was_accepted" >&2
  exit 1
fi
mv -f "${CANDIDATE}.original" "$CANDIDATE"

echo '{"status":"passed","candidate_mode":"0644","internal_mode":"0600","sudo":"real"}'
