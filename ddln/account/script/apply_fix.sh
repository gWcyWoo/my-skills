#!/usr/bin/env bash
# dpt / account / apply_fix —— 定点修复菜单(确定性)。由 skill 按 collect_diag 证据选择调用。
# 只动「账号 / 权限 / sshd 认证项」,绝不做无关操作。
# 用法: apply_fix.sh <profile> <fix-name>
#   fix-name: ssh_dir_perms | authkeys_perms | ownership | home_writable
#             pubkey_auth | allowusers_add | selinux | unlock | set_shell
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: apply_fix.sh <profile> <fix-name>}"
FIX="${2:?缺少 fix 名称}"
export DPT_BOOT=root
U="$DPT_USER"
H="$(rexec "getent passwd '$U' | cut -d: -f6" | tr -d '\r')"

case "$FIX" in
  ssh_dir_perms)  run "修正 ~/.ssh = 700"           rexec "chmod 700 '$H/.ssh'";;
  authkeys_perms) run "修正 authorized_keys = 600"  rexec "chmod 600 '$H/.ssh/authorized_keys'";;
  ownership)      run "修正 ~/.ssh 属主 = $U"       rexec "chown -R '$U:$U' '$H/.ssh'";;
  home_writable)  run "收紧家目录 group/other 写位"  rexec "chmod g-w,o-w '$H'";;
  pubkey_auth)
      step "启用 PubkeyAuthentication"
      dropin_set pubkeyauthentication yes && reload_sshd && ok || fail "无法启用 PubkeyAuthentication";;
  allowusers_add)
      step "AllowUsers 加入 $U"
      au="$(eff_cfg allowusers)"
      dropin_set allowusers "${au:+$au }$U" && reload_sshd && ok || fail "无法加入 AllowUsers";;
  selinux)        run "SELinux restorecon ~/.ssh"   rexec "restorecon -R -F '$H/.ssh'";;
  unlock)         run "解锁账号 $U"                 rexec "usermod -U '$U'";;
  set_shell)      run "设登录 shell = /bin/bash"    rexec "usermod -s /bin/bash '$U'";;
  *)
      printf '未知 fix: %s\n' "$FIX"
      printf '可用: ssh_dir_perms authkeys_perms ownership home_writable pubkey_auth allowusers_add selinux unlock set_shell\n'
      exit 2;;
esac
