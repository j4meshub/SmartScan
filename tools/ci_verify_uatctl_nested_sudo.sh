#!/usr/bin/env bash
set -euo pipefail

# 仅在一次性GitHub Runner中验证真实sudo设置的SUDO_USER/SUDO_COMMAND。
# 旧执行器本体的摘要和授权规则由仓库测试锁定；这里用固定探针隔离真实主机存储与模型。
[[ "${EUID}" -eq 0 ]] || { echo "必须以root运行" >&2; exit 1; }

readonly REPO_ROOT="${1:?缺少仓库根目录}"
readonly LIBEXEC="/usr/local/libexec/smartscan"
readonly CONFIG_ROOT="/etc/smartscan/uat"
readonly MODE_FILE="/run/smartscan-uatctl-ci-mode"
readonly ORIGINAL_HOSTNAME="$(hostname -s)"

cleanup() {
    rm -f /etc/sudoers.d/smartscan-uatctl-ci \
        /etc/sudoers.d/smartscan-uat-loop-storage \
        /etc/sudoers.d/smartscan-uat-loop-storage.disabled \
        /etc/sudoers.d/smartscan-uat-ocr-model \
        "$MODE_FILE"
    rm -rf "$LIBEXEC" "$CONFIG_ROOT"
    userdel -r smartscan-intruder >/dev/null 2>&1 || true
    userdel -r szhzx >/dev/null 2>&1 || true
    hostname "$ORIGINAL_HOSTNAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

hostname ctiecaiserver
useradd --create-home --shell /bin/bash szhzx
useradd --create-home --shell /bin/bash smartscan-intruder
install -d -o root -g root -m 0755 "$LIBEXEC"
install -d -o root -g root -m 0700 "$CONFIG_ROOT"
install -o root -g root -m 0755 \
    "$REPO_ROOT/deploy/ops/smartscan-uatctl" "$LIBEXEC/smartscan-uatctl"
install -o root -g root -m 0755 \
    "$REPO_ROOT/deploy/ops/smartscan_uatctl.py" "$LIBEXEC/smartscan_uatctl.py"

# 先安装旧执行器真实字节及sudoers，证明双层sudo能通过其真实身份检查。
install -o root -g root -m 0755 \
    "$REPO_ROOT/deploy/ops/smartscan-uat-loop-storage" \
    "$LIBEXEC/smartscan-uat-loop-storage"
install -o root -g root -m 0755 \
    "$REPO_ROOT/deploy/ops/smartscan-uat-ocr-model" \
    "$LIBEXEC/smartscan-uat-ocr-model"
install -o root -g root -m 0644 \
    "$REPO_ROOT/deploy/ops/smartscan_uat_ocr_model.py" \
    "$LIBEXEC/smartscan_uat_ocr_model.py"
install -o root -g root -m 0440 \
    "$REPO_ROOT/deploy/sudoers/smartscan-uat-loop-storage" \
    /etc/sudoers.d/smartscan-uat-loop-storage
install -o root -g root -m 0440 \
    "$REPO_ROOT/deploy/ops/smartscan-uat-ocr-model.sudoers" \
    /etc/sudoers.d/smartscan-uat-ocr-model
install -o root -g root -m 0440 \
    "$REPO_ROOT/tests/fixtures/uatctl/controller.sudoers" \
    /etc/sudoers.d/smartscan-uatctl-ci
visudo -cf /etc/sudoers

set +e
loop_real_output="$(sudo -n -u szhzx -- /usr/bin/env -i \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin LANG=C LC_ALL=C \
    /usr/bin/sudo -n "$LIBEXEC/smartscan-uat-loop-storage" verify 2>&1)"
loop_real_code="$?"
model_real_output="$(sudo -n -u szhzx -- /usr/bin/env -i \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin LANG=C LC_ALL=C \
    /usr/bin/sudo -n "$LIBEXEC/smartscan-uat-ocr-model" verify 2>&1)"
model_real_code="$?"
set -e
[[ "$loop_real_code" -ne 0 && "$loop_real_output" != *"sudo_user_mismatch"* \
    && "$loop_real_output" != *"sudo_command_mismatch"* ]] || exit 96
[[ "$model_real_code" -ne 0 && "$model_real_output" != *"sudo_user_mismatch"* ]] || exit 97

# 真实执行器随后会因Runner没有生产loop/模型而按预期失败；固定探针只隔离数据面，
# 继续用真实sudo验证控制器的成功、异常和超时路径。
install -o root -g root -m 0755 \
    "$REPO_ROOT/tests/fixtures/uatctl/legacy-loop-probe" \
    "$LIBEXEC/smartscan-uat-loop-storage"
install -o root -g root -m 0755 \
    "$REPO_ROOT/tests/fixtures/uatctl/legacy-model-probe" \
    "$LIBEXEC/smartscan-uat-ocr-model"

# 正确调用由真实sudo设置两层SUDO_USER/SUDO_COMMAND，不伪造环境变量。
sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uatctl" verify-storage | grep -q '"status": "passed"'
sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uatctl" verify-models | grep -q '"status": "passed"'
sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uatctl" status | grep -q '"storage_verified"'
sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uatctl" status | grep -q '"models_verified"'

# 错误调用者、错误命令和额外参数均必须失败关闭。
if sudo -u smartscan-intruder sudo -n "$LIBEXEC/smartscan-uatctl" status >/dev/null 2>&1; then exit 101; fi
if sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uat-loop-storage" status >/dev/null 2>&1; then exit 102; fi
if sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uat-loop-storage" verify extra >/dev/null 2>&1; then exit 103; fi
if sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uatctl" verify-storage extra >/dev/null 2>&1; then exit 104; fi

# 缺少旧执行器sudoers、异常退出和固定30秒超时均失败关闭。
mv /etc/sudoers.d/smartscan-uat-loop-storage /etc/sudoers.d/smartscan-uat-loop-storage.disabled
if sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uatctl" verify-storage >/dev/null 2>&1; then exit 105; fi
mv /etc/sudoers.d/smartscan-uat-loop-storage.disabled /etc/sudoers.d/smartscan-uat-loop-storage
printf 'loop-fail\n' >"$MODE_FILE"
if sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uatctl" verify-storage >/dev/null 2>&1; then exit 106; fi
printf 'loop-timeout\n' >"$MODE_FILE"
started="$(date +%s)"
if sudo -u szhzx sudo -n "$LIBEXEC/smartscan-uatctl" verify-storage >/dev/null 2>&1; then exit 107; fi
elapsed="$(( $(date +%s) - started ))"
[[ "$elapsed" -ge 29 && "$elapsed" -le 34 ]] || { echo "超时边界异常：${elapsed}s" >&2; exit 108; }

echo "真实sudo双层调用链验证通过"
