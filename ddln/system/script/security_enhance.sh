#!/usr/bin/env bash
# dpt / system / security_enhance —— 系统级安全加固(SSH 已在 account 完成)。
# 运营 cert + sudo 执行(无 root)。用法: security_enhance.sh <profile> [--allow "80,443"]
# 命令式项在此;可规则化的(sysctl/模块/文件权限/服务)末尾交 run_checks --fix。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
PROFILE="${1:?用法: security_enhance.sh <profile> [--allow \"80,443\"] [--remove \"8080\"]}"; shift || true
ALLOW=""; REMOVE=""
while [ $# -gt 0 ]; do case "$1" in --allow) ALLOW="${2:-}"; shift 2;; --remove) REMOVE="${2:-}"; shift 2;; *) shift;; esac; done
dpt_load "$PROFILE"
export DPT_BOOT=sudo
export DPT_SYSCTL_FILE=/etc/sysctl.d/60-dpt-security.conf

# ============ A. 防火墙 ufw(防锁死)============
section "防火墙 ufw(默认拒绝 + 放行 SSH/业务端口)"
run "安装 ufw" rexec "DEBIAN_FRONTEND=noninteractive apt-get install -y ufw >/dev/null 2>&1"
run "默认 deny incoming / allow outgoing" rexec "ufw --force default deny incoming >/dev/null; ufw --force default allow outgoing >/dev/null"
run "放行 SSH 端口 $DPT_PORT(强制,先于 enable)" rexec "ufw allow $DPT_PORT/tcp >/dev/null"
if [ -n "$ALLOW" ]; then
  IFS=', ' read -r -a PORTS <<< "$ALLOW"
  for p in "${PORTS[@]}"; do
    [ -n "$p" ] || continue
    case "$p" in */*) spec="$p";; *) spec="$p/tcp";; esac
    run "放行用户端口 $spec" rexec "ufw allow $spec >/dev/null"
  done
fi
# 取消用户明确取消的端口(--remove);绝不动 SSH 端口
if [ -n "$REMOVE" ]; then
  IFS=', ' read -r -a RPORTS <<< "$REMOVE"
  for p in "${RPORTS[@]}"; do
    [ -n "$p" ] || continue
    case "$p" in */*) spec="$p";; *) spec="$p/tcp";; esac
    [ "$spec" = "$DPT_PORT/tcp" ] && { note "跳过取消 SSH 端口 $spec(强制保留)"; continue; }
    run "取消放行 $spec" rexec "ufw delete allow $spec >/dev/null 2>&1 || true; true"
  done
fi
run "开启 ufw 日志(low)" rexec "ufw logging low >/dev/null"
run "布防 dead-man's-switch(120s 后自动 disable)" rexec "systemctl stop dpt-ufw-deadman.timer 2>/dev/null || true; systemctl reset-failed dpt-ufw-deadman 2>/dev/null || true
  systemd-run --on-active=120 --unit=dpt-ufw-deadman --collect /usr/sbin/ufw --force disable >/dev/null 2>&1"
run "启用 ufw" rexec "ufw --force enable >/dev/null"
show "验证 ufw 启用后证书登录(端口 $DPT_PORT)" "ssh -i $DPT_KEY -p $DPT_PORT $DPT_USER@$DPT_HOST true"
if ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new \
       -i "$DPT_KEY" -p "$DPT_PORT" "$DPT_USER@$DPT_HOST" true 2>/dev/null; then
  printf '  → done\n'
  run "撤销 dead-man's-switch(验证通过)" rexec "systemctl stop dpt-ufw-deadman.timer 2>/dev/null || true; systemctl reset-failed dpt-ufw-deadman 2>/dev/null || true"
else
  printf '  → FAILED\n  └─ ufw 启用后证书登录失败;dead-man'\''s-switch 将在 120s 内自动 ufw disable 恢复。检查放行规则后重跑。\n'
  exit 1
fi

# ============ B. fail2ban ============
section "fail2ban(systemd backend,防爆破)"
run "安装 fail2ban" rexec "DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban >/dev/null 2>&1"
run "写 jail.local(backend=systemd, sshd 端口 $DPT_PORT)" rexec "cat > /etc/fail2ban/jail.local <<CONF
[DEFAULT]
backend  = systemd
bantime  = 1h
findtime = 10m
maxretry = 5
ignoreip = 127.0.0.1/8 ::1
[sshd]
enabled = true
port    = $DPT_PORT
mode    = aggressive
CONF"
run "启用并重启 fail2ban" rexec "systemctl enable fail2ban >/dev/null 2>&1; systemctl restart fail2ban"

# ============ C. unattended-upgrades(自动安全更新)============
section "自动安全更新 unattended-upgrades"
run "安装 unattended-upgrades" rexec "DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades apt-listchanges >/dev/null 2>&1"
run "写 20auto-upgrades" rexec "cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists \"1\";
APT::Periodic::Unattended-Upgrade \"1\";
CONF"
run "写 52unattended-upgrades-local(自动重启 02:00)" rexec "cat > /etc/apt/apt.conf.d/52unattended-upgrades-local <<'CONF'
Unattended-Upgrade::Automatic-Reboot \"true\";
Unattended-Upgrade::Automatic-Reboot-Time \"02:00\";
Unattended-Upgrade::Remove-Unused-Dependencies \"true\";
CONF"
run "启用 apt-daily 定时器" rexec "systemctl enable apt-daily-upgrade.timer apt-daily.timer >/dev/null 2>&1"

# ============ D. 口令与登录基线 ============
section "口令与登录基线"
run "login.defs 口令时效/UMASK(删所有重复→写唯一,幂等)" rexec "
  for kv in 'PASS_MAX_DAYS 365' 'PASS_MIN_DAYS 1' 'PASS_WARN_AGE 7' 'UMASK 027'; do
    k=\${kv%% *}; v=\${kv##* }
    sed -ri \"/^[[:space:]]*#?[[:space:]]*\${k}[[:space:]]/d\" /etc/login.defs
    printf '%s\t%s\n' \"\$k\" \"\$v\" >> /etc/login.defs
  done"
run "libpam-pwquality 强度策略" rexec "
  DEBIAN_FRONTEND=noninteractive apt-get install -y libpam-pwquality >/dev/null 2>&1
  mkdir -p /etc/security/pwquality.conf.d
  cat > /etc/security/pwquality.conf.d/dpt.conf <<'CONF'
minlen = 14
dcredit = -1
ucredit = -1
ocredit = -1
lcredit = -1
retry = 3
CONF"
note "账户锁定 pam_faillock 跳过(改 PAM 有锁死风险,且 fail2ban 已在网络层防爆破)"

# ============ E. 横幅 / cron 白名单 / core dump ============
section "横幅 / cron 白名单 / core dump"
run "清空登录横幅 OS 信息" rexec "
  for f in /etc/issue /etc/issue.net; do printf 'Authorized access only.\n' > \$f; chmod 644 \$f; done
  : > /etc/motd 2>/dev/null || true"
run "cron/at 白名单(仅 root)" rexec "
  rm -f /etc/cron.deny /etc/at.deny
  printf 'root\n' > /etc/cron.allow; chmod 600 /etc/cron.allow; chown root:root /etc/cron.allow
  printf 'root\n' > /etc/at.allow;  chmod 600 /etc/at.allow;  chown root:root /etc/at.allow"
run "core dump 收口" rexec "
  mkdir -p /etc/systemd/coredump.conf.d
  cat > /etc/systemd/coredump.conf.d/dpt.conf <<'CONF'
[Coredump]
Storage=none
ProcessSizeMax=0
CONF
  cat > /etc/security/limits.d/dpt-coredump.conf <<'CONF'
* hard core 0
CONF
  systemctl daemon-reload 2>/dev/null || true"

# ============ F. 临时目录挂载加固(nodev,nosuid;不加 noexec)============
section "/tmp /var/tmp /dev/shm 挂载加固(nodev,nosuid)"
run "/tmp bind 自挂 + nodev,nosuid(幂等:已挂只重挂选项,不叠层)" rexec "
  grep -qE '^/tmp[[:space:]]+/tmp[[:space:]]' /etc/fstab || echo '/tmp /tmp none bind,nodev,nosuid 0 0' >> /etc/fstab
  mountpoint -q /tmp || mount --bind /tmp /tmp
  mount -o remount,bind,nodev,nosuid /tmp"
run "/var/tmp bind 自挂 + nodev,nosuid(幂等)" rexec "
  grep -qE '^/var/tmp[[:space:]]+/var/tmp[[:space:]]' /etc/fstab || echo '/var/tmp /var/tmp none bind,nodev,nosuid 0 0' >> /etc/fstab
  mountpoint -q /var/tmp || mount --bind /var/tmp /var/tmp
  mount -o remount,bind,nodev,nosuid /var/tmp"
run "/dev/shm tmpfs nodev,nosuid" rexec "
  grep -qE '[[:space:]]/dev/shm[[:space:]]' /etc/fstab || echo 'tmpfs /dev/shm tmpfs rw,nosuid,nodev 0 0' >> /etc/fstab
  mount -o remount,nodev,nosuid /dev/shm 2>/dev/null || true"

# ============ G. auditd 审计 ============
section "auditd 审计(CIS 基线规则)"
run "安装 auditd" rexec "DEBIAN_FRONTEND=noninteractive apt-get install -y auditd audispd-plugins >/dev/null 2>&1"
run "部署 CIS 基线审计规则" rexec "cat > /etc/audit/rules.d/dpt-cis.rules <<'CONF'
-D
-b 8192
-f 1
-w /etc/passwd -p wa -k identity
-w /etc/group -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/gshadow -p wa -k identity
-w /etc/sudoers -p wa -k scope
-w /etc/sudoers.d/ -p wa -k scope
-w /var/log/lastlog -p wa -k logins
-a always,exit -F arch=b64 -S adjtimex,settimeofday,clock_settime -k time-change
-w /etc/hosts -p wa -k system-locale
-w /etc/crontab -p wa -k cron
-w /etc/cron.d/ -p wa -k cron
-a always,exit -F arch=b64 -S init_module,delete_module -k modules
-a always,exit -F arch=b64 -S mount -k mounts
CONF
  augenrules --load >/dev/null 2>&1 || true
  systemctl enable auditd >/dev/null 2>&1
  systemctl restart auditd 2>/dev/null || service auditd restart 2>/dev/null || true"

# ============ I. 日志管理(journald 限额 + logrotate + auditd 封顶 + 权限)============
section "日志管理(journald 限额 / logrotate / auditd 封顶)"
run "journald 限额(持久化 + 500M + 30天 + 压缩)" rexec "
  mkdir -p /etc/systemd/journald.conf.d
  cat > /etc/systemd/journald.conf.d/dpt.conf <<'CONF'
[Journal]
Storage=persistent
Compress=yes
SystemMaxUse=500M
MaxRetentionSec=30day
CONF
  systemctl restart systemd-journald 2>/dev/null || true"
run "安装 logrotate + 基础留存策略" rexec "
  DEBIAN_FRONTEND=noninteractive apt-get install -y logrotate >/dev/null 2>&1
  cat > /etc/logrotate.d/dpt <<'CONF'
/var/log/*.log {
  weekly
  rotate 8
  compress
  delaycompress
  missingok
  notifempty
  copytruncate
}
CONF"
run "auditd 日志封顶(50M x 5, ROTATE)" rexec "
  f=/etc/audit/auditd.conf
  sed -ri 's/^[#[:space:]]*max_log_file[[:space:]]*=.*/max_log_file = 50/' \$f
  sed -ri 's/^[#[:space:]]*num_logs[[:space:]]*=.*/num_logs = 5/' \$f
  sed -ri 's/^[#[:space:]]*max_log_file_action[[:space:]]*=.*/max_log_file_action = ROTATE/' \$f
  service auditd restart 2>/dev/null || systemctl restart auditd 2>/dev/null || true"
run "收紧 /var/log/*.log 非全局可读" rexec "
  find /var/log -type f -name '*.log' -perm /0004 -exec chmod o-rwx {} + 2>/dev/null || true"

# ============ J. 本地日志副本(障眼法:不显眼机制名 → ~/.cck/*.cck)============
# 这是 C(异地防篡改)之前的过渡:只防懒/自动清痕,root 仍可找到;真实用途见 SKILL.md。
# 机制名故意起作 sys-cache-maint(非 log/backup),让 list-timers 一瞥不露馅。
section "本地日志副本(systemd 定时 → ~/.cck/*.cck)"
run "部署日志维护脚本(伪装名 sys-cache-maint)" rexec "cat > /usr/local/lib/sys-cache-maint <<'CCKEOF'
#!/bin/sh
# system cache maintenance
d=\"\$(getent passwd $DPT_USER | cut -d: -f6)/.cck\"
mkdir -p \"\$d\"; chmod 700 \"\$d\"; chown $DPT_USER:$DPT_USER \"\$d\"
ts=\"\$(date +%F)\"
journalctl --since '1 day ago' --no-pager > \"\$d/journal-\$ts.cck\" 2>/dev/null
[ -f /var/log/audit/audit.log ] && cp -f /var/log/audit/audit.log \"\$d/audit-\$ts.cck\" 2>/dev/null
command -v logwatch >/dev/null 2>&1 && logwatch --output stdout --format text --detail Med --range yesterday > \"\$d/logwatch-\$ts.cck\" 2>/dev/null
[ -f /var/log/rkhunter.log ] && cp -f /var/log/rkhunter.log \"\$d/rkhunter-\$ts.cck\" 2>/dev/null
chown $DPT_USER:$DPT_USER \"\$d\"/*.cck 2>/dev/null
chmod 600 \"\$d\"/*.cck 2>/dev/null
find \"\$d\" -name '*.cck' -mtime +30 -delete 2>/dev/null
CCKEOF
chmod 700 /usr/local/lib/sys-cache-maint"
run "部署 systemd 定时器(每天)" rexec "
  cat > /etc/systemd/system/sys-cache-maint.service <<'CONF'
[Unit]
Description=System cache maintenance
[Service]
Type=oneshot
ExecStart=/usr/local/lib/sys-cache-maint
CONF
  cat > /etc/systemd/system/sys-cache-maint.timer <<'CONF'
[Unit]
Description=System cache maintenance schedule
[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=1h
[Install]
WantedBy=timers.target
CONF
  systemctl daemon-reload
  systemctl enable --now sys-cache-maint.timer >/dev/null 2>&1"
run "立即生成首份副本并查看" rexec "systemctl start sys-cache-maint.service; ls -1 \$(getent passwd $DPT_USER | cut -d: -f6)/.cck 2>/dev/null"

# ============ K. rootkit 检测 + 日志摘要(rkhunter / chkrootkit / logwatch)============
section "rootkit 检测 + 日志摘要(rkhunter / chkrootkit / logwatch)"
run "安装 rkhunter / chkrootkit / logwatch" rexec "DEBIAN_FRONTEND=noninteractive apt-get install -y rkhunter chkrootkit logwatch >/dev/null 2>&1"
run "rkhunter:初始化基线 + 开每日扫描 + apt 后自动更基线" rexec "
  sed -ri 's/^#?[[:space:]]*CRON_DAILY_RUN=.*/CRON_DAILY_RUN=\"true\"/' /etc/default/rkhunter 2>/dev/null || true
  sed -ri 's/^#?[[:space:]]*APT_AUTOGEN=.*/APT_AUTOGEN=\"true\"/'       /etc/default/rkhunter 2>/dev/null || true
  rkhunter --propupd >/dev/null 2>&1 || true"
run "chkrootkit:开每日扫描" rexec "
  for c in /etc/chkrootkit/chkrootkit.conf /etc/chkrootkit.conf; do
    [ -f \"\$c\" ] && { grep -q '^RUN_DAILY=' \"\$c\" && sed -ri 's/^RUN_DAILY=.*/RUN_DAILY=\"true\"/' \"\$c\" || echo 'RUN_DAILY=\"true\"' >> \"\$c\"; }
  done; true"
run "logwatch:停默认邮件 cron(摘要改由每日维护脚本写入 ~/.cck)" rexec "chmod -x /etc/cron.daily/00logwatch 2>/dev/null || true"

# ============ H. 规则基线逐条加固(sysctl/模块/文件权限/服务)============
section "套用规则基线(逐条 check → 不合规则修复)"
printf '\n'
bash "$ROOT/lib/run_checks.sh" --fix "$ROOT/system/rule/security_hardening.rules" || fail "规则加固执行失败"

section "安全加固完成"
