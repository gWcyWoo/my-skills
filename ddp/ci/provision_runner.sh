#!/usr/bin/env bash
# dDP / ci / provision_runner —— 16a-2:gitlab-runner 跑在非 root 账号 + 资源 slice。rexec(cert+sudo)。
# gitlab-runner 包已建 gitlab-runner 用户;此处确保:无 sudo/无 docker 组、服务以该账号跑、MemoryMax/CPUQuota。
# 一次性、幂等。用法: provision_runner.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: provision_runner.sh <profile>}"

section "配置 gitlab-runner(非 root user-mode + 资源笼)"

run "确保账号 gitlab-runner(无 sudo/无 docker 组)" rexec "
  set -e
  id gitlab-runner >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/gitlab-runner --shell /bin/bash gitlab-runner
  deluser gitlab-runner sudo   2>/dev/null || true
  deluser gitlab-runner docker 2>/dev/null || true
  install -d -m700 -o gitlab-runner -g gitlab-runner /home/gitlab-runner
"

run "安装服务以 gitlab-runner 账号跑" rexec "
  gitlab-runner stop 2>/dev/null || true
  gitlab-runner install --user gitlab-runner --working-directory /home/gitlab-runner 2>/dev/null || true
  systemctl enable gitlab-runner >/dev/null 2>&1 || true
"

run "资源 slice(MemoryMax=1G / CPUQuota=50%)" rexec "
  install -d -m755 /etc/systemd/system/gitlab-runner.service.d
  cat > /etc/systemd/system/gitlab-runner.service.d/dpt-resources.conf <<'CONF'
[Service]
MemoryMax=1G
CPUQuota=50%
CONF
  systemctl daemon-reload
  systemctl restart gitlab-runner
"

run "校验:服务 active"        rexec "systemctl is-active gitlab-runner >/dev/null 2>&1"
# [REVIEW:fix] 模型A(system-service):daemon 以 root 跑(正常),job 降权到 gitlab-runner。
# 校验「unit 配了 --user gitlab-runner」而非 daemon 进程属主(空闲时只有 root daemon)。
# 注:用 `systemctl show -p ExecStart`(argv 空格分隔)而非 `systemctl cat`(每 token 带引号
#     "--user" "gitlab-runner",正则匹配不到)—— 实测踩坑后修正。
run "校验:job 降权 gitlab-runner(unit --user)" rexec "systemctl show -p ExecStart --value gitlab-runner 2>/dev/null | grep -Eq -- '--user[[:space:]=]+gitlab-runner'"
run "校验:不在 docker 组"      rexec "! id -nG gitlab-runner | tr ' ' '\n' | grep -qx docker"
run "校验:不在 sudo 组"        rexec "! id -nG gitlab-runner | tr ' ' '\n' | grep -qx sudo"
printf '\ngitlab-runner 配置完成 ✅(daemon=root / job=gitlab-runner、无 docker/sudo、资源受限)\n'
