#!/usr/bin/env bash
# dpt / system / performance —— 性能配置:swap + 网络/内核 sysctl 调优 + fd 上限。
# 运营 cert + sudo 执行(无 root)。用法: performance.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: performance.sh <profile>}"
export DPT_BOOT=sudo
SYSCTL=/etc/sysctl.d/70-dpt-performance.conf

section "性能配置(swap + sysctl 调优 + fd)"

# 1. swap:/swapfile 4GB(幂等:已挂则跳过)
run "创建并启用 4GB swapfile(幂等)" rexec "
  if ! swapon --show 2>/dev/null | grep -q '/swapfile'; then
    [ -f /swapfile ] || { fallocate -l 4G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none; }
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null 2>&1 || true
    swapon /swapfile
  fi
  grep -qE '^/swapfile[[:space:]]' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab"

# 2. 性能 sysctl drop-in(BBR/fq、并发、fd、脏页)
run "写入性能 sysctl drop-in" rexec "cat > '$SYSCTL' <<'CONF'
# dpt performance (managed). Remove to roll back.
vm.swappiness = 10
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 1024
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_max_syn_backlog = 4096
net.core.netdev_max_backlog = 5000
net.ipv4.ip_local_port_range = 1024 65535
fs.file-max = 1000000
CONF
modprobe tcp_bbr 2>/dev/null || true
sysctl --system >/dev/null 2>&1"

# 3. 文件描述符上限
run "设置 NOFILE 上限(limits.d)" rexec "cat > /etc/security/limits.d/90-dpt-nofile.conf <<'CONF'
*    soft  nofile  65535
*    hard  nofile  65535
root soft  nofile  65535
root hard  nofile  65535
CONF"

# 4. 验证 BBR 生效
show "验证 BBR 生效" "sysctl -n net.ipv4.tcp_congestion_control"
cc="$(rexec "sysctl -n net.ipv4.tcp_congestion_control" 2>/dev/null | tr -d '[:space:]')"
if [ "$cc" = bbr ]; then printf '  → 实际 bbr ✓\n'; else printf '  → 实际 %s | 期望 bbr | FAILED\n' "$cc"; fi

section "性能配置完成"
printf 'swap: /swapfile 4G;拥塞控制: %s\n' "$cc"
