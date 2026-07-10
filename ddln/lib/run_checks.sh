#!/usr/bin/env bash
# dpt 通用检查执行器 —— 读 .rules 文件,逐条 check。
#   --fix    : 不合规则把期望值 stage 进加固 drop-in(不 reload,由调用方统一校验/reload/验证)
#   --check  : 只查不改,任一不合规则整体退出非零(收尾审计用)
# 在「你的本机」执行;远端比对走 rexec / sshd -T。需先 source lib/common.sh 并 export DPT_*。
#
# 规则行格式: kind|name|expected|severity|reference
#   kind=sshd  name=指令  expected=期望值(__USER__ 替换为运营用户)  —— sshd -T 比对,drop-in 修复
#   kind=file  name=路径  expected=mode:owner:group                 —— stat 比对,chmod/chown 修复
set -uo pipefail

MODE="${1:?用法: run_checks.sh --fix|--check <rules-file>}"
RULES="${2:?缺少 rules 文件}"
: "${DPT_USER:?}"; : "${DPT_DROPIN:?}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# 一次性抓取远端生效配置(sshd 规则用)
EFFCFG="$(rexec 'sshd -T 2>/dev/null')"
eff() { printf '%s\n' "$EFFCFG" | grep -i "^$1 " | head -1 | cut -d' ' -f2-; }

FAILED=0

while IFS='|' read -r kind name expected sev ref; do
  case "${kind:-}" in ''|\#*) continue;; esac
  expected="${expected//__USER__/$DPT_USER}"

  case "$kind" in
    sshd)
      cur="$(eff "$name")"
      show "检查 $name(期望 $expected)" "sshd -T | grep -i '^$name'"
      if [ "$(lower "$cur")" = "$(lower "$expected")" ]; then
        printf '  → 实际 %s ✓\n' "$cur"
      elif [ "$MODE" = --fix ]; then
        rexec "echo '$name $expected' >> '$DPT_DROPIN'" && printf '  → 实际 %s,已加固 → %s\n' "${cur:-未设置}" "$expected"
      else
        printf '  → 实际 %s | 期望 %s | FAILED [%s]\n' "${cur:-未设置}" "$expected" "$ref"; FAILED=1
      fi
      ;;
    file)
      mode="${expected%%:*}"; own="${expected#*:}"
      show "检查 $name 权限(期望 $mode $own)" "stat -c '%a %U:%G' '$name'"
      if ! rexec "test -e '$name'" >/dev/null 2>&1; then
        printf '  → 路径不存在,跳过(N/A)\n'
      else
        cur="$(rexec "stat -c '%a %U:%G' '$name' 2>/dev/null")"
        if [ "$cur" = "$mode $own" ]; then
          printf '  → 实际 %s ✓\n' "$cur"
        elif [ "$MODE" = --fix ]; then
          rexec "chmod $mode '$name'; chown $own '$name'" && printf '  → 实际 %s,已修正 → %s\n' "${cur:-缺失}" "$mode $own"
        else
          printf '  → 实际 %s | 期望 %s | FAILED [%s]\n' "${cur:-缺失}" "$mode $own" "$ref"; FAILED=1
        fi
      fi
      ;;
    sysctl)
      cur="$(rexec "sysctl -n '$name' 2>/dev/null")"
      show "检查 sysctl $name(期望 $expected)" "sysctl -n $name"
      if [ "$cur" = "$expected" ]; then
        printf '  → 实际 %s ✓\n' "$cur"
      elif [ "$MODE" = --fix ]; then
        rexec "f='${DPT_SYSCTL_FILE:-/etc/sysctl.d/60-dpt-security.conf}'
               touch \"\$f\"; sed -i \"\\#^[[:space:]]*$name[[:space:]]*=#d\" \"\$f\"
               printf '%s = %s\n' '$name' '$expected' >> \"\$f\"
               sysctl -w '$name=$expected' >/dev/null 2>&1" \
          && printf '  → 实际 %s,已加固 → %s\n' "${cur:-未设置}" "$expected"
      else
        printf '  → 实际 %s | 期望 %s | FAILED [%s]\n' "${cur:-未设置}" "$expected" "$ref"; FAILED=1
      fi
      ;;
    service)
      if [ "$expected" = active ]; then q=is-active; else q=is-enabled; fi
      cur="$(rexec "systemctl $q '$name' 2>/dev/null")"
      show "检查服务 $name(期望 $expected)" "systemctl $q $name"
      if [ "$cur" = "$expected" ] || { [ "$expected" = enabled ] && [ "$cur" = static ]; }; then
        printf '  → 实际 %s ✓\n' "$cur"
      elif [ "$MODE" = --fix ]; then
        rexec "systemctl enable --now '$name' >/dev/null 2>&1" && printf '  → 已 enable --now %s\n' "$name"
      else
        printf '  → 实际 %s | 期望 %s | FAILED [%s]\n' "${cur:-缺失}" "$expected" "$ref"; FAILED=1
      fi
      ;;
    pkg)
      cur="$(rexec "dpkg-query -W -f='\${Status}' '$name' 2>/dev/null | grep -q 'install ok installed' && echo installed || echo missing")"
      show "检查包 $name(期望 installed)" "dpkg -s $name | grep Status"
      if [ "$cur" = installed ]; then
        printf '  → 实际 installed ✓\n'
      elif [ "$MODE" = --fix ]; then
        rexec "DEBIAN_FRONTEND=noninteractive apt-get install -y '$name' >/dev/null 2>&1" && printf '  → 已安装 %s\n' "$name"
      else
        printf '  → 实际 %s | 期望 installed | FAILED [%s]\n' "$cur" "$ref"; FAILED=1
      fi
      ;;
    module)
      cur="$(rexec "modprobe -n -v '$name' 2>&1 | grep -qE 'install +/bin/(false|true)' && echo blacklisted || echo loadable")"
      show "检查模块 $name(期望 blacklisted)" "modprobe -n -v $name"
      if [ "$cur" = blacklisted ]; then
        printf '  → 实际 blacklisted ✓\n'
      elif [ "$MODE" = --fix ]; then
        rexec "f=/etc/modprobe.d/dpt-cis.conf; touch \"\$f\"
               grep -qx 'install $name /bin/false' \"\$f\" || echo 'install $name /bin/false' >> \"\$f\"
               grep -qx 'blacklist $name' \"\$f\" || echo 'blacklist $name' >> \"\$f\"" \
          && printf '  → 已黑名单 %s\n' "$name"
      else
        printf '  → 实际 %s | 期望 blacklisted | FAILED [%s]\n' "$cur" "$ref"; FAILED=1
      fi
      ;;
    *)
      note "未知规则 kind: $kind(跳过)"
      ;;
  esac
done < "$RULES"

exit $FAILED
