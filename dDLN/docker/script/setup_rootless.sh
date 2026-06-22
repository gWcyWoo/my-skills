#!/usr/bin/env bash
# dpt / docker / setup_rootless —— 以 opt 身份配 rootless dockerd + 加固 daemon.json + DOCKER_HOST。
# 运营 cert(**不 sudo**,走 rexec_user)。用法: setup_rootless.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: setup_rootless.sh <profile>}"

section "配置 rootless Docker(以 $DPT_USER,不 sudo)"

run "rootless setuptool install(幂等 --force)" rexec_user "dockerd-rootless-setuptool.sh install --force --skip-iptables >/dev/null 2>&1"

run "建 ~/.config/docker 与 systemd/user 目录" rexec_user "install -d -m700 \$HOME/.config/docker; install -d -m755 \$HOME/.config/systemd/user"

show "部署加固 daemon.json" "cat > ~/.config/docker/daemon.json ← docker/conf/daemon.json"
if rexec_user_in "cat > .config/docker/daemon.json" < "$ROOT/docker/conf/daemon.json"; then printf '  → done\n'; else fail "daemon.json 部署失败"; fi

run "设 DOCKER_HOST/PATH 到 ~/.bashrc(交互会话用,幂等)" rexec_user "
  grep -q 'DOCKER_HOST=unix' \$HOME/.bashrc 2>/dev/null || cat >> \$HOME/.bashrc <<'RC'
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
export DOCKER_HOST=unix:///run/user/\$(id -u)/docker.sock
export PATH=/usr/bin:/usr/sbin:\$PATH
RC"

run "启用 + 重启 rootless dockerd(systemctl --user)" rexec_user "
  systemctl --user enable docker >/dev/null 2>&1 || true
  systemctl --user restart docker
  sleep 3
  docker info >/dev/null 2>&1"

show "rootless docker 自检" "docker version --format 'Server {{.Server.Version}}' + docker info | grep rootless"
rexec_user "docker version --format 'Server {{.Server.Version}}' 2>/dev/null; docker info 2>/dev/null | grep -i rootless | head -1" | sed 's/^/  → /'

section "rootless Docker 配置完成"
