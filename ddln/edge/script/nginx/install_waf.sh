#!/usr/bin/env bash
# dpt / edge / nginx / install_waf —— ModSecurity v3 引擎 + 编连接器(走探测 guard)+ OWASP CRS。
# 运营 cert + sudo(无 root)。用法: install_waf.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: install_waf.sh <profile>}"
export DPT_BOOT=sudo

section "WAF:ModSecurity v3 + OWASP CRS(默认 DetectionOnly)"

run "装引擎 + 构建依赖" rexec "DEBIAN_FRONTEND=noninteractive apt-get install -y \
  libmodsecurity3 libmodsecurity-dev gcc g++ make libpcre2-dev zlib1g-dev libssl-dev git wget ca-certificates >/dev/null 2>&1"

# 部署"探测优先"的连接器重建器(也被 apt 钩子复用)
show "部署连接器重建器 → /usr/local/sbin/dpt-modsec-rebuild" "tee /usr/local/sbin/dpt-modsec-rebuild ← edge/script/nginx/rebuild_modsec.sh"
if rexec_in "tee /usr/local/sbin/dpt-modsec-rebuild >/dev/null" < "$ROOT/edge/script/nginx/rebuild_modsec.sh" \
   && rexec "chmod 700 /usr/local/sbin/dpt-modsec-rebuild"; then printf '  → done\n'; else fail "部署重建器失败"; fi

run "注册 apt 钩子(nginx 升级后自动校正 .so)" rexec "printf 'DPkg::Post-Invoke { \"/usr/local/sbin/dpt-modsec-rebuild >/dev/null 2>&1 || true\"; };\n' > /etc/apt/apt.conf.d/99-dpt-modsec-rebuild"

# 编译较长 + 跨境取源 → 脱离会话(systemd-run --no-block)+ 轮询;断连不中断编译。
run "启动连接器首次构建(systemd-run --no-block 脱离会话)" rexec "
  systemctl reset-failed dpt-modsec-build 2>/dev/null || true
  systemctl stop dpt-modsec-build 2>/dev/null || true
  systemd-run --unit=dpt-modsec-build --collect --no-block /usr/local/sbin/dpt-modsec-rebuild"
step "等待连接器构建完成(轮询 dpt-modsec-build)"
for _ in $(seq 1 120); do
  st="$(rexec "systemctl show -p ActiveState --value dpt-modsec-build 2>/dev/null" | tr -d '[:space:]')"
  case "$st" in inactive|failed|'') break;; esac
  sleep 5
done
ok
res="$(rexec "systemctl show -p Result --value dpt-modsec-build 2>/dev/null" | tr -d '[:space:]')"
show "连接器构建结果" "systemctl show -p Result dpt-modsec-build"
if [ "$res" = success ] && rexec "test -f /etc/nginx/modules/ngx_http_modsecurity_module.so"; then printf '  → success ✓\n'
else printf '  → FAILED(%s);见 /var/log/dpt-modsec-rebuild.log:\n' "${res:-未知}"; rexec "tail -n 25 /var/log/dpt-modsec-rebuild.log 2>/dev/null" | sed 's/^/  └─ /'; exit 1; fi

run "取 modsecurity.conf-recommended + unicode.mapping(设 DetectionOnly)" rexec "
  cd /etc/nginx/modsec
  [ -f modsecurity.conf ] || curl -fsSL https://raw.githubusercontent.com/owasp-modsecurity/ModSecurity/v3/master/modsecurity.conf-recommended -o modsecurity.conf
  [ -f unicode.mapping ]  || curl -fsSL https://raw.githubusercontent.com/owasp-modsecurity/ModSecurity/v3/master/unicode.mapping -o unicode.mapping
  sed -ri 's/^SecRuleEngine .*/SecRuleEngine DetectionOnly/' modsecurity.conf
  sed -ri 's#^SecAuditLog [^ ].*#SecAuditLog /var/log/nginx/modsec_audit.log#' modsecurity.conf"

run "部署 OWASP CRS" rexec "
  d=/etc/nginx/modsec/crs
  if [ -d \$d/.git ]; then git -C \$d pull --ff-only >/dev/null 2>&1 || true
  else git clone --depth=1 https://github.com/coreruleset/coreruleset.git \$d >/dev/null 2>&1; fi
  [ -f \$d/crs-setup.conf ] || cp \$d/crs-setup.conf.example \$d/crs-setup.conf"

section "WAF 安装完成(DetectionOnly;调稳后把 modsecurity.conf 的 SecRuleEngine 改 On)"
