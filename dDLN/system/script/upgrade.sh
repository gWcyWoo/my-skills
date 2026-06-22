#!/usr/bin/env bash
# dpt / system / upgrade —— 全量升级(脱离 ssh 会话防中断)+ needrestart + 需要则重启重连。
# 运营 cert + sudo 执行(无 root)。用法: upgrade.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: upgrade.sh <profile>}"
export DPT_BOOT=sudo

section "系统升级(full-upgrade,防中断)"

run "apt update" rexec "DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null 2>&1"

# 升级前快照(审计参考)
show "升级前快照" "uname -r; dpkg --get-selections | wc -l"
rexec "echo 内核=\$(uname -r); echo 已装包=\$(dpkg --get-selections | wc -l)" | sed 's/^/  → /'

# full-upgrade 脱离 ssh 会话(systemd-run 瞬态单元):即便 needrestart 重启 sshd 也不中断升级
run "启动 full-upgrade(systemd-run 瞬态单元,--no-block 脱离会话,日志 /var/log/dpt-upgrade.log)" rexec "
  systemctl reset-failed dpt-upgrade 2>/dev/null || true
  systemctl stop dpt-upgrade 2>/dev/null || true
  systemd-run --unit=dpt-upgrade --collect --no-block \
    /bin/bash -c 'DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold full-upgrade >/var/log/dpt-upgrade.log 2>&1'"

# 轮询升级单元完成(最多约 10 分钟)
step "等待升级完成(轮询 dpt-upgrade)"
for _ in $(seq 1 120); do
  st="$(rexec "systemctl show -p ActiveState --value dpt-upgrade 2>/dev/null" | tr -d '[:space:]')"
  case "$st" in inactive|failed|'') break;; esac
  sleep 5
done
ok

res="$(rexec "systemctl show -p Result --value dpt-upgrade 2>/dev/null" | tr -d '[:space:]')"
show "升级结果" "systemctl show -p Result dpt-upgrade"
if [ "$res" = success ]; then
  printf '  → 实际 success ✓\n'
else
  printf '  → 实际 %s(详见 /var/log/dpt-upgrade.log)| FAILED\n' "${res:-未知}"
  rexec "tail -n 20 /var/log/dpt-upgrade.log 2>/dev/null" | sed 's/^/  └─ /'
  exit 1
fi

run "autoremove + clean" rexec "DEBIAN_FRONTEND=noninteractive apt-get -y autoremove --purge >/dev/null 2>&1; apt-get clean"
run "needrestart 受控重启变更服务" rexec "DEBIAN_FRONTEND=noninteractive apt-get install -y needrestart >/dev/null 2>&1; needrestart -r a >/dev/null 2>&1 || true"

# 需要重启?Debian 不一定建 /var/run/reboot-required → 同时比对运行内核 vs 最新已装内核
need_reboot=no
rexec "test -f /var/run/reboot-required" 2>/dev/null && need_reboot=yes
RUNNING="$(rexec 'uname -r' 2>/dev/null | tr -d '[:space:]')"
LATEST="$(rexec "ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's#.*/vmlinuz-##' | sort -V | tail -1" 2>/dev/null | tr -d '[:space:]')"
[ -n "$LATEST" ] && [ "$RUNNING" != "$LATEST" ] && need_reboot=yes

if [ "$need_reboot" = yes ]; then
  section "需要重启(运行内核 $RUNNING → 最新 $LATEST)"
  run "触发重启(2s 后,脱离会话)" rexec "systemd-run --on-active=2 --collect /bin/systemctl reboot >/dev/null 2>&1"
  # 以"内核变为最新"为重连成功标准:即便短暂 catch 到重启前的旧机,也会因内核不符而继续等
  # (ConnectTimeout 在掉线期提供节流,不依赖 sleep)。
  step "等待重启 + cert 轮询重连(端口 $DPT_PORT,目标内核 $LATEST)"
  rc=0; NOW=""
  for _ in $(seq 1 80); do
    NOW="$(ssh -o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new \
              -i "$DPT_KEY" -p "$DPT_PORT" "$DPT_USER@$DPT_HOST" 'uname -r' 2>/dev/null | tr -d '[:space:]')"
    [ -n "$NOW" ] && [ "$NOW" = "$LATEST" ] && { rc=1; break; }
    sleep 3
  done
  if [ "$rc" = 1 ]; then ok; printf '  → 重启后内核 %s ✓\n' "$LATEST"
  else printf 'FAILED\n  └─ 限期内未重连到目标内核(运行 %s / 目标 %s),请查云控制台。\n' "${NOW:-离线}" "$LATEST"; exit 1; fi
else
  note "无需重启(运行内核已是最新 $RUNNING)"
fi

section "升级完成"
