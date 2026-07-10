#!/usr/bin/env bash
# dDP / ci / install_toolchain —— 16a-1:装 CI 工具链(sury php<ver>-cli+扩展、composer、acl、rsync、gitlab-runner)。
# rexec(cert+sudo)。扩展清单对齐容器 Dockerfile。跨境长操作 → systemd-run 脱离 + 轮询。一次性、幂等。
# php 版本参数化(对齐应用/容器);7.4.33 取 major.minor=7.4。
# 用法: install_toolchain.sh <profile> <phpver>   例: install_toolchain.sh nigeria_api 7.4
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: install_toolchain.sh <profile> <phpver>}"
VER="${2:?缺 phpver(如 7.4 / 7.4.33)}"; MM="$(printf '%s' "$VER" | cut -d. -f1-2)"   # 7.4.33 → 7.4
UNIT="dpt-ci-toolchain"

section "安装 CI 工具链(php$MM,detached)"
run "加 sury(php)+ gitlab-runner 官方源" rexec "
  set -e
  install -d -m755 /etc/apt/keyrings
  DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null 2>&1
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates gnupg lsb-release apt-transport-https >/dev/null 2>&1
  np=\$(. /etc/os-release; echo \$ID)
  if [ \"\$np\" = ubuntu ]; then
    # Ubuntu:sury 的 debian 仓库无 ubuntu dist → 用 Launchpad PPA ppa:ondrej/php(同一维护者,含 php7.4)。
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends software-properties-common >/dev/null 2>&1
    add-apt-repository -y ppa:ondrej/php >/dev/null 2>&1
  else
    # Debian:sury。keyring 必须世界可读,否则 _apt 读不到 → NO_PUBKEY。
    curl -fsSL https://packages.sury.org/php/apt.gpg -o /etc/apt/keyrings/sury-php.gpg
    chmod 0644 /etc/apt/keyrings/sury-php.gpg
    echo \"deb [signed-by=/etc/apt/keyrings/sury-php.gpg] https://packages.sury.org/php/ \$(lsb_release -sc) main\" > /etc/apt/sources.list.d/sury-php.list
  fi
  curl -fsSL https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh | bash >/dev/null 2>&1
  DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null 2>&1
  apt-cache policy php${MM}-cli 2>/dev/null | grep -qE 'Candidate: [0-9]'
"

run "启动安装(脱离会话,php$MM + acl/rsync/gitlab-runner)" rexec "
  systemctl reset-failed $UNIT 2>/dev/null || true
  systemctl stop $UNIT 2>/dev/null || true
  systemd-run --unit=$UNIT --collect --no-block /bin/bash -c 'exec >/var/log/dpt-ci-toolchain.log 2>&1
    set -e
    DEBIAN_FRONTEND=noninteractive apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y php${MM}-cli php${MM}-mysql php${MM}-mbstring php${MM}-zip php${MM}-bcmath php${MM}-intl php${MM}-gd php${MM}-redis php${MM}-curl php${MM}-xml php${MM}-opcache acl rsync gitlab-runner'
"

printf '等待安装完成(轮询 %s,最多 ~12min)...' "$UNIT"
for i in $(seq 1 144); do
  st="$(rexec "systemctl show -p ActiveState --value $UNIT 2>/dev/null")"
  case "$st" in inactive|failed) break ;; esac
  sleep 5
done
printf ' done\n'

res="$(rexec "systemctl show -p Result --value $UNIT 2>/dev/null")"
show "安装结果" "systemctl show -p Result $UNIT"
if [ "$res" = success ]; then
  printf '  → 实际 %s ✓\n' "$res"
else
  printf '  → 实际 %s ❌\n  └─ 末尾日志:\n' "${res:-未知}"
  rexec "tail -30 /var/log/dpt-ci-toolchain.log 2>/dev/null" | sed 's/^/     /'
  exit 1
fi

# [REVIEW:fix] composer 改官方安装器 + sha384 校验(供应链),不再裸下 phar。php=sury 默认指向 php$MM。
run "装 composer(官方安装器 + sha384 校验)" rexec '
  set -e
  cd /tmp
  curl -fsSL https://getcomposer.org/installer -o composer-setup.php
  EXP=$(curl -fsSL https://composer.github.io/installer.sig)
  ACT=$(php -r "echo hash_file(\"sha384\", \"composer-setup.php\");")
  [ "$EXP" = "$ACT" ] || { echo "composer 安装器 sha384 校验失败"; exit 1; }
  php composer-setup.php --install-dir=/usr/local/bin --filename=composer >/dev/null
  rm -f composer-setup.php
'

run "校验 php$MM-cli"     rexec "php -v | head -1"
run "校验 composer"       rexec "composer --version"
run "校验 gitlab-runner"  rexec "gitlab-runner --version | head -1"
run "校验 setfacl/rsync"  rexec "command -v setfacl >/dev/null && command -v rsync >/dev/null"
printf '\nCI 工具链安装完成 ✅(php%s)\n' "$MM"
