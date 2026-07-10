#!/usr/bin/env bash
# dpt / account / harden —— SSH 安全加固(确定性协议)。
# 套规则 → 单一 drop-in → sshd -t → reload → 全新连接验证 → 失败回滚(防锁死)。
# root 引导连接全程不断,作回滚生命线。用法: harden.sh <profile> [new-port]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: harden.sh <profile> [new-port]}"
NEWPORT="${2:-}"
export DPT_BOOT=root

section "SSH 安全加固(CIS 5.2 + Mozilla)"
EFFPORT="$DPT_PORT"
SOCK_DROPIN='/etc/systemd/system/ssh.socket.d/00-dpt-port.conf'
# 改端口前探测监听机制:Ubuntu 22.10+/24.04 默认 systemd socket 激活(ssh.socket),
# 监听端口由 ssh.socket 的 ListenStream 决定,sshd_config 的 Port 被忽略。
# SOCK_MODE 非空 → 端口走 socket drop-in;为空 → 经典 sshd 写 Port(与旧行为逐字节一致)。
SOCK_MODE=""
if [ -n "$NEWPORT" ] && rexec "systemctl is-active ssh.socket >/dev/null 2>&1"; then SOCK_MODE=1; fi

run "初始化加固 drop-in(可整体回滚)" rexec "
     install -m600 -o root -g root /dev/null '$DPT_DROPIN'
     printf '# dpt hardening (managed). Remove this file to roll back.\n' > '$DPT_DROPIN'"

if [ -n "$NEWPORT" ]; then
  if [ -n "$SOCK_MODE" ]; then
    run "写入新端口 $NEWPORT(ssh.socket ListenStream)" rexec "
       install -d -m755 /etc/systemd/system/ssh.socket.d
       printf '[Socket]\nListenStream=\nListenStream=%s\n' '$NEWPORT' > '$SOCK_DROPIN'
       systemctl daemon-reload"
  else
    run "写入新端口 $NEWPORT" rexec "echo 'Port $NEWPORT' >> '$DPT_DROPIN'"
  fi
  open_firewall "$NEWPORT"
  EFFPORT="$NEWPORT"
fi

printf '\n## 加固规则(逐条 check → stage 进 drop-in)\n'
bash "$ROOT/lib/run_checks.sh" --fix "$ROOT/account/rule/ssh_hardening.rules" || fail "加固规则执行失败"

printf '\n## 生效与验证\n'
run "校验 sshd 配置 (sshd -t)" rexec "sshd -t"
run "reload sshd(不断现有会话)" rexec "systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || service ssh reload"
if [ -n "$SOCK_MODE" ]; then
  run "重启 ssh.socket(切到端口 $EFFPORT,不断现有会话)" rexec "systemctl restart ssh.socket"
fi

show "验证加固后证书登录(端口 $EFFPORT)" "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -i $DPT_KEY -p $EFFPORT $DPT_USER@$DPT_HOST true"
if VERR="$(ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -i "$DPT_KEY" -p "$EFFPORT" "$DPT_USER@$DPT_HOST" true 2>&1)"; then
  printf '  → done\n'
else
  printf '  → FAILED\n'
  [ -n "$VERR" ] && printf '%s\n' "$VERR" | sed 's/^/  └─ /'
  rexec "rm -f '$DPT_DROPIN'
         if [ -n '$SOCK_MODE' ]; then rm -f '$SOCK_DROPIN'; systemctl daemon-reload; systemctl restart ssh.socket 2>/dev/null; fi
         systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || service ssh reload 2>/dev/null" >/dev/null 2>&1
  # 不轻信回滚:上面的 rexec 若因 master 掉线等静默失败(>/dev/null),drop-in 会残留而无人知。
  # 独立用 opt 证书连「旧端口」复核:① drop-in 真的删了吗 ② 登录还通吗 —— 再如实报告。
  # (harden 的前置是 test_login 已通,故此刻 opt 证书 + NOPASSWD sudo 必然可用,可作独立校验通道。)
  if ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
         -i "$DPT_KEY" -p "$DPT_PORT" "$DPT_USER@$DPT_HOST" "sudo test ! -f '$DPT_DROPIN'" 2>/dev/null; then
    printf '  └─ 已回滚:drop-in 已删除,旧端口 %s 证书登录已复验可用。\n' "$DPT_PORT"
  elif ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
         -i "$DPT_KEY" -p "$DPT_PORT" "$DPT_USER@$DPT_HOST" true 2>/dev/null; then
    printf '  └─ ⚠️ 回滚未确认:旧端口 %s 证书登录可用,但加固 drop-in 仍残留 %s ——服务器可能仍处加固态。请手工核查/删除该文件后再重试。\n' "$DPT_PORT" "$DPT_DROPIN"
  else
    printf '  └─ ❌ 回滚失败且旧端口 %s 证书登录不可用 ——服务器可能被锁死!请立即用云控制台/VNC 检查 %s 及 sshd/ssh.socket 状态。\n' "$DPT_PORT" "$DPT_DROPIN"
  fi
  printf '  └─ 常见原因:云安全组未放行端口 %s,或 AllowUsers 把 %s 排除了。\n' "$EFFPORT" "$DPT_USER"
  exit 1
fi

# 端口若变了,更新 conf 供后续脚本/收尾使用
if [ "$EFFPORT" != "$DPT_PORT" ]; then
  sed -i.bak "s/^export DPT_PORT=.*/export DPT_PORT='$EFFPORT'/" "$DPT_DIR/dpt.conf" && rm -f "$DPT_DIR/dpt.conf.bak"
  note "端口已更新到配置:$EFFPORT"
fi

section "加固完成"
printf '生效端口: %s\n' "$EFFPORT"
