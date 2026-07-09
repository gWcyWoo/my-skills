#!/usr/bin/env bash
# dpt / docker / install_docker —— 装 Docker 引擎 + compose/buildx + rootless 前置;禁 rootful;配 subuid/lingering。
# 这是 root 部分(运营 cert + sudo)。rootless 用户态配置在 setup_rootless.sh。
# 用法: install_docker.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: install_docker.sh <profile>}"
export DPT_BOOT=sudo

section "安装 Docker(root 部分:引擎 + rootless 前置)"

run "rootless 前置包(uidmap/dbus-user-session/slirp4netns/fuse-overlayfs)" rexec "
  DEBIAN_FRONTEND=noninteractive apt-get install -y uidmap dbus-user-session slirp4netns fuse-overlayfs curl ca-certificates gnupg >/dev/null 2>&1"

run "Docker 官方 apt 源(GPG + 按代号)+ 落盘校验" rexec "
  install -d -m755 /etc/apt/keyrings /etc/apt/sources.list.d
  np=\$(. /etc/os-release; case \$ID in ubuntu) echo ubuntu;; *) echo debian;; esac)
  curl -fsSL https://download.docker.com/linux/\$np/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  cn=\$(. /etc/os-release; echo \$VERSION_CODENAME); arch=\$(dpkg --print-architecture)
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/%s %s stable\n' \"\$arch\" \"\$np\" \"\$cn\" > /etc/apt/sources.list.d/docker.list
  test -s /etc/apt/sources.list.d/docker.list && grep -q download.docker.com /etc/apt/sources.list.d/docker.list"

# 跨境 + 包多 → 脱离会话装(同'长操作脱离控制连接'铁律)
run "启动 Docker 安装(systemd-run --no-block 脱离会话)" rexec "
  systemctl reset-failed dpt-docker-install 2>/dev/null || true
  systemctl stop dpt-docker-install 2>/dev/null || true
  systemd-run --unit=dpt-docker-install --collect --no-block /bin/bash -c '
    DEBIAN_FRONTEND=noninteractive apt-get update -y >/var/log/dpt-docker-install.log 2>&1 &&
    DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras >>/var/log/dpt-docker-install.log 2>&1'"
step "等待 Docker 安装完成(轮询 dpt-docker-install)"
for _ in $(seq 1 120); do
  st="$(rexec "systemctl show -p ActiveState --value dpt-docker-install 2>/dev/null" | tr -d '[:space:]')"
  case "$st" in inactive|failed|'') break;; esac
  sleep 5
done
ok
res="$(rexec "systemctl show -p Result --value dpt-docker-install 2>/dev/null" | tr -d '[:space:]')"
show "Docker 安装结果" "systemctl show -p Result dpt-docker-install"
if [ "$res" = success ] && rexec "command -v docker >/dev/null 2>&1"; then printf '  → success ✓\n'
else printf '  → FAILED(%s);见日志:\n' "${res:-未知}"; rexec "tail -n 20 /var/log/dpt-docker-install.log 2>/dev/null" | sed 's/^/  └─ /'; exit 1; fi

run "禁用并 mask rootful 守护(只用 rootless)" rexec "
  systemctl disable --now docker.service docker.socket 2>/dev/null || true
  systemctl mask docker.service docker.socket 2>/dev/null || true"

run "subuid/subgid 含 $DPT_USER + 开 lingering(rootless 必需)" rexec "
  grep -q '^$DPT_USER:' /etc/subuid || echo '$DPT_USER:100000:65536' >> /etc/subuid
  grep -q '^$DPT_USER:' /etc/subgid || echo '$DPT_USER:100000:65536' >> /etc/subgid
  loginctl enable-linger '$DPT_USER'
  grep -q '^$DPT_USER:' /etc/subuid && grep -q '^$DPT_USER:' /etc/subgid"

section "Docker root 部分完成(下一步 setup_rootless.sh 以 $DPT_USER 配 rootless)"
