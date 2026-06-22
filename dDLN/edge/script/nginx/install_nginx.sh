#!/usr/bin/env bash
# dpt / edge / nginx / install_nginx —— 装 nginx.org stable + 纳入 unattended-upgrades 自动更新。
# 运营 cert + sudo(无 root)。用法: install_nginx.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: install_nginx.sh <profile>}"
export DPT_BOOT=sudo

section "安装 nginx(nginx.org stable + 自动更新)"

run "装前置(curl/gnupg/ca-certificates)" rexec "DEBIAN_FRONTEND=noninteractive apt-get install -y curl gnupg2 ca-certificates >/dev/null 2>&1"

run "导入 nginx.org 签名密钥" rexec "
  install -d -m755 /usr/share/keyrings
  curl -fsSL https://nginx.org/keys/nginx_signing.key | gpg --dearmor -o /usr/share/keyrings/nginx-archive-keyring.gpg
  test -s /usr/share/keyrings/nginx-archive-keyring.gpg"

run "写 apt 源(stable,按发行代号)+ pin 优先 nginx.org(并校验落盘)" rexec "
  install -d -m755 /etc/apt/sources.list.d /etc/apt/preferences.d
  cn=\$(. /etc/os-release; echo \$VERSION_CODENAME)
  printf 'deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/debian %s nginx\n' \"\$cn\" > /etc/apt/sources.list.d/nginx.list
  printf 'Package: *\nPin: origin nginx.org\nPin-Priority: 900\n' > /etc/apt/preferences.d/99nginx
  test -s /etc/apt/sources.list.d/nginx.list && grep -q nginx.org /etc/apt/sources.list.d/nginx.list"

# 跨境 ssh 易断 → 安装走 systemd-run 脱离会话(同'长操作脱离控制连接'铁律),断连不中断安装。
run "启动 nginx 安装(systemd-run --no-block 脱离会话)" rexec "
  systemctl reset-failed dpt-nginx-install 2>/dev/null || true
  systemctl stop dpt-nginx-install 2>/dev/null || true
  systemd-run --unit=dpt-nginx-install --collect --no-block /bin/bash -c '
    DEBIAN_FRONTEND=noninteractive apt-get update -y >/var/log/dpt-nginx-install.log 2>&1 &&
    DEBIAN_FRONTEND=noninteractive apt-get install -y nginx >>/var/log/dpt-nginx-install.log 2>&1'"

step "等待 nginx 安装完成(轮询 dpt-nginx-install)"
for _ in $(seq 1 90); do
  st="$(rexec "systemctl show -p ActiveState --value dpt-nginx-install 2>/dev/null" | tr -d '[:space:]')"
  case "$st" in inactive|failed|'') break;; esac
  sleep 4
done
ok
res="$(rexec "systemctl show -p Result --value dpt-nginx-install 2>/dev/null" | tr -d '[:space:]')"
show "nginx 安装结果" "systemctl show -p Result dpt-nginx-install"
if [ "$res" = success ] && rexec "dpkg -s nginx >/dev/null 2>&1"; then printf '  → success ✓\n'
else printf '  → FAILED(%s);见日志:\n' "${res:-未知}"; rexec "tail -n 20 /var/log/dpt-nginx-install.log 2>/dev/null" | sed 's/^/  └─ /'; exit 1; fi

# 用 edge 自己的独立 drop-in,不去 append 系统模块拥有/覆盖写的 52 文件(否则被其 cat> 覆盖掉)。
run "把 nginx 源纳入 unattended-upgrades(独立 drop-in)" rexec "
  printf 'Unattended-Upgrade::Origins-Pattern { \"origin=nginx\"; };\n' > /etc/apt/apt.conf.d/53unattended-upgrades-nginx"

run "建配置目录 + 启用 nginx" rexec "
  install -d -m755 /etc/nginx/snippets /etc/nginx/modsec /etc/nginx/modules-enabled /etc/nginx/conf.d /etc/nginx/ssl /var/www/html
  systemctl enable nginx >/dev/null 2>&1 || true"

show "nginx 版本" "nginx -v"
rexec "nginx -v 2>&1" | sed 's/^/  → /'
section "nginx 安装完成"
