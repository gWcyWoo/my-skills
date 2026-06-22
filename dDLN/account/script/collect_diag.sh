#!/usr/bin/env bash
# dpt / account / collect_diag —— 【只采证据,绝不修改】证书登录失败时给 skill 推理用。
# 输出原始证据(非 step 风格),供 Claude 判断真正原因、选择 apply_fix。用法: collect_diag.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: collect_diag.sh <profile>}"
export DPT_BOOT=root

echo "# 证书登录失败 —— 诊断证据(只读)"

echo
echo "[authlog] sshd 最近拒绝原因(最权威,优先看这条):"
rexec "{ journalctl -u ssh -u sshd -n 60 --no-pager 2>/dev/null || tail -n 60 /var/log/auth.log 2>/dev/null || tail -n 60 /var/log/secure 2>/dev/null; } | grep -iE 'sshd|authentic|publickey|refused|denied|bad ownership|bad modes|invalid user|not allowed' | tail -15"

echo
echo "[perms] 家目录 / ~/.ssh / authorized_keys:"
rexec "H=\"\$(getent passwd '$DPT_USER' | cut -d: -f6)\"; ls -ld \"\$H\" \"\$H/.ssh\" \"\$H/.ssh/authorized_keys\" 2>&1"

echo
echo "[sshd] 关键指令(sshd -T):"
rexec "sshd -T 2>/dev/null | grep -iE '^(pubkeyauthentication|authorizedkeysfile|allowusers|allowgroups|denyusers|denygroups|permitrootlogin|passwordauthentication|authenticationmethods) '"

echo
echo "[selinux] 状态:"
rexec "command -v getenforce >/dev/null 2>&1 && getenforce || echo 'no-selinux'"

echo
echo "[account] 锁定状态 / 登录 shell:"
rexec "passwd -S '$DPT_USER' 2>/dev/null; getent passwd '$DPT_USER' | cut -d: -f7"

echo
echo "[client] 客户端 ssh -vvv 末尾(看走到哪步被拒):"
ssh -vvv -o BatchMode=yes -o ConnectTimeout=8 -i "$DPT_KEY" -p "$DPT_PORT" "$DPT_USER@$DPT_HOST" true 2>&1 | tail -15

echo
echo "# 证据采集完毕。"
