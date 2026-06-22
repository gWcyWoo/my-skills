#!/usr/bin/env bash
# dpt / system / close —— 收尾检查:升级 + 性能 + 安全(只查不改)。运营 cert + sudo 复连。
# 用法: close_check.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: close_check.sh <profile>}"
export DPT_BOOT=sudo

FAILED=0
# yn "<标签>" "<远端命令>" —— 远端命令退出 0 = done,否则 FAILED。
yn() {
  show "$1" "$2"
  if rexec "$2" >/dev/null 2>&1; then printf '  → done\n'; else printf '  → FAILED\n'; FAILED=1; fi
}
# eqv "<标签>" "<期望>" "<远端命令>" —— 远端命令输出(去空白)== 期望。
eqv() {
  show "$1(期望 $2)" "$3"
  local got; got="$(rexec "$3" 2>/dev/null | tr -d '[:space:]')"
  if [ "$got" = "$2" ]; then printf '  → 实际 %s ✓\n' "$got"
  else printf '  → 实际 %s | 期望 %s | FAILED\n' "${got:-空}" "$2"; FAILED=1; fi
}

section "系统模块收尾检查(升级 + 性能 + 安全,只查)"

printf '## 升级\n'
yn  "无待重启标记" "test ! -f /var/run/reboot-required"
eqv "剩余安全更新数" "0" "apt list --upgradable 2>/dev/null | grep -ci security || true"

printf '\n## 性能\n'
yn  "swap 已启用" "swapon --show | grep -q ."
eqv "vm.swappiness" "10" "sysctl -n vm.swappiness"
eqv "TCP 拥塞控制 BBR" "bbr" "sysctl -n net.ipv4.tcp_congestion_control"
eqv "默认 qdisc fq" "fq" "sysctl -n net.core.default_qdisc"

printf '\n## 安全(规则逐条)\n'
bash "$ROOT/lib/run_checks.sh" --check "$ROOT/system/rule/security_hardening.rules" || FAILED=1

printf '\n## 安全(命令式专项)\n'
yn  "ufw 默认拒绝入站" "ufw status verbose | grep -q 'deny (incoming)'"
yn  "ufw 放行 SSH 端口 $DPT_PORT" "ufw status | grep -q '$DPT_PORT'"
yn  "fail2ban sshd jail 运行" "fail2ban-client status sshd >/dev/null 2>&1"
eqv "时间已同步" "yes" "timedatectl show -p NTPSynchronized --value"
yn  "AppArmor 已启用" "aa-status --enabled >/dev/null 2>&1"
yn  "/tmp 带 nodev,nosuid 且仍可执行" "o=\$(findmnt -no OPTIONS /tmp); echo \"\$o\" | grep -q nodev && echo \"\$o\" | grep -q nosuid && ! echo \"\$o\" | grep -q noexec"
eqv "login.defs PASS_MAX_DAYS" "365" "awk '/^PASS_MAX_DAYS/{v=\$2} END{print v}' /etc/login.defs"
eqv "login.defs UMASK" "027" "awk '/^UMASK/{v=\$2} END{print v}' /etc/login.defs"
yn  "coredump Storage=none" "grep -rqE '^Storage=none' /etc/systemd/coredump.conf /etc/systemd/coredump.conf.d/ 2>/dev/null"

printf '\n## 日志管理\n'
yn  "logrotate 已装" "dpkg-query -W -f='\${Status}' logrotate 2>/dev/null | grep -q 'install ok installed'"
yn  "journald 持久化" "test -d /var/log/journal"
yn  "journald 限额已设(SystemMaxUse=500M)" "grep -rq '^SystemMaxUse=500M' /etc/systemd/journald.conf.d/"
yn  "auditd 日志封顶(max_log_file=50)" "grep -qE '^max_log_file[[:space:]]*=[[:space:]]*50' /etc/audit/auditd.conf"
yn  "本地日志副本定时器启用" "systemctl is-enabled sys-cache-maint.timer >/dev/null 2>&1"
yn  "~/.cck 存在且 700" "d=\$(getent passwd $DPT_USER|cut -d: -f6)/.cck; test -d \$d && [ \$(stat -c %a \$d) = 700 ]"
yn  "已生成 .cck 日志副本" "ls \$(getent passwd $DPT_USER|cut -d: -f6)/.cck/*.cck >/dev/null 2>&1"

printf '\n## rootkit 检测 + 摘要\n'
yn  "rkhunter 已装" "dpkg-query -W -f='\${Status}' rkhunter 2>/dev/null | grep -q 'install ok installed'"
yn  "rkhunter 每日扫描已开" "grep -qE '^CRON_DAILY_RUN=\"true\"' /etc/default/rkhunter"
yn  "chkrootkit 已装" "dpkg-query -W -f='\${Status}' chkrootkit 2>/dev/null | grep -q 'install ok installed'"
yn  "logwatch 已装" "dpkg-query -W -f='\${Status}' logwatch 2>/dev/null | grep -q 'install ok installed'"

printf '\n'
if [ "$FAILED" -eq 0 ]; then printf '系统收尾检查全部通过 ✅\n'; exit 0
else printf '系统收尾检查存在未通过项 ❌(见上面 FAILED)\n'; exit 1; fi
