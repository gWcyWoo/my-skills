#!/usr/bin/env bash
# dpt / account / provision —— 确定性:生成密钥+密码、建用户、设密码(存盘)、NOPASSWD sudo、装公钥。
# 经 connect.sh 已开的 root ControlMaster 执行。用法: provision_user.sh <profile>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: provision_user.sh <profile>}"
export DPT_BOOT=root

section "配置运营用户 $DPT_USER"

# 1. 本地生成密钥(不回显内容,只报路径)
show "生成 SSH 密钥对 (ed25519)" "ssh-keygen -t ed25519 -N '' -C dpt-$DPT_USER -f $DPT_KEY"
if [ -f "$DPT_KEY" ]; then printf '  → 已存在,复用:%s\n' "$DPT_KEY"
elif ssh-keygen -t ed25519 -N '' -C "dpt-$DPT_USER" -f "$DPT_KEY" >/dev/null 2>&1; then
  chmod 600 "$DPT_KEY"; printf '  → done(%s)\n' "$DPT_KEY"
else fail "ssh-keygen 失败"; fi

# 2. 本地生成强随机密码(不回显,只写 600 文件)
show "生成运营用户密码" "tr -dc <强随机字符集> </dev/urandom | head -c28 > $DPT_PWFILE  (***** 不回显,chmod 600)"
if [ -f "$DPT_PWFILE" ]; then printf '  → 已存在,复用:%s\n' "$DPT_PWFILE"
else
  PW="$(LC_ALL=C tr -dc 'A-Za-z0-9!@%^_=+-' < /dev/urandom | head -c 28)"
  ( umask 077; printf '%s\n' "$PW" > "$DPT_PWFILE" )
  PW=""
  printf '  → done(已存 %s,600;不回显)\n' "$DPT_PWFILE"
fi

# 3. 远端创建用户(幂等)
run "创建运营用户 $DPT_USER" rexec "id -u '$DPT_USER' >/dev/null 2>&1 || useradd -m -s /bin/bash '$DPT_USER'"

# 4. 设服务器端密码(明文经管道喂 chpasswd,服务器只留哈希,不进 argv/终端/Codex)
show "设置服务器端密码(只留哈希)" "printf '$DPT_USER:*****' | chpasswd   (密码经 stdin,服务器只留哈希,不进 argv)"
if printf '%s:%s' "$DPT_USER" "$(cat "$DPT_PWFILE")" | rexec_in "chpasswd"; then printf '  → done\n'
else fail "chpasswd 失败"; fi

# 5. NOPASSWD sudo(部署期脚手架,最后一步撤销)
run "授予 NOPASSWD sudo(部署期)" rexec "
     printf '%s ALL=(ALL) NOPASSWD:ALL\n' '$DPT_USER' > /etc/sudoers.d/dpt-$DPT_USER
     chmod 440 /etc/sudoers.d/dpt-$DPT_USER
     visudo -cf /etc/sudoers.d/dpt-$DPT_USER >/dev/null"

# 6. 装公钥(去重、属主/权限),家目录从 passwd 实取
PUB="$(cat "$DPT_KEY.pub")"
run "部署公钥到 authorized_keys" rexec "
     H=\"\$(getent passwd '$DPT_USER' | cut -d: -f6)\"
     install -d -m700 -o '$DPT_USER' -g '$DPT_USER' \"\$H/.ssh\"
     touch \"\$H/.ssh/authorized_keys\"
     grep -qxF '$PUB' \"\$H/.ssh/authorized_keys\" || echo '$PUB' >> \"\$H/.ssh/authorized_keys\"
     chmod 600 \"\$H/.ssh/authorized_keys\"
     chown -R '$DPT_USER:$DPT_USER' \"\$H/.ssh\""

section "运营用户配置完成"
printf '私钥: %s\n' "$DPT_KEY"
printf '密码: %s(600 明文;部署期走 NOPASSWD 不读它,撤销后 sudo 用)\n' "$DPT_PWFILE"
