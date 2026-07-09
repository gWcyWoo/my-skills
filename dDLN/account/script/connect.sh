#!/usr/bin/env bash
# dpt / account / connect —— 【你在自己终端运行】开一条 root 特权连接(输一次密码)。
# 密码不落盘:ssh 握手用完即丢,只留 ControlMaster socket 供后续脚本复用。
# 用法: connect.sh <profile> <host> <user> <port>
#   profile —— 凭据目录名,凭据存 ~/.ssh/<profile>/(如 nigeria)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"

PROFILE="${1:?用法: connect.sh <profile> <host> <user> <port> [boot-user]}"
HOST="${2:?缺少 host}"
USER_="${3:?缺少 user}"
PORT="${4:-22}"
# boot-user —— 建立特权 master 时用哪个登录用户。默认 root(root 直登);
# 若服务器禁 root 直登(如云 Ubuntu),传 ubuntu 等有 NOPASSWD sudo 的用户,
# rexec 会经同一 socket 走 `sudo` 提权。记入 dpt.conf 供后续脚本沿用。
BOOTUSER="${5:-root}"

DIR="$HOME/.ssh/$PROFILE"
install -d -m700 "$DIR"
CONF="$DIR/dpt.conf"

cat > "$CONF" <<EOF
# dpt 配置(connect.sh 生成;非密文,可读)
# 只存"服务器侧事实";本地路径(DIR/KEY/PWFILE/CTRL/PROFILE 名)一律由 dpt_load 按 profile 目录推导,
# 故 profile 目录可随意重命名/移动而不破——dpt.conf 不记自己的目录名/路径。
export DPT_HOST='$HOST'
export DPT_PORT='$PORT'
export DPT_USER='$USER_'
# 必须按字典序排在 cloud-init 的 50-cloud-init.conf 之前:sshd 对每个指令
# 「首个取到的值生效」(first-match-wins),Include 按文件名字典序加载。若排在 50
# 之后(如旧的 99-),cloud-init 的 PasswordAuthentication yes 会先被读到并胜出,
# 我们写的 no 形同虚设。故用 00- 前缀确保本加固 drop-in 最先被读、稳压 cloud-init。
export DPT_DROPIN='/etc/ssh/sshd_config.d/00-dpt-hardening.conf'
export DPT_BOOTUSER='$BOOTUSER'
EOF
chmod 600 "$CONF"
. "$CONF"

section "建立特权连接(profile: $PROFILE)"
# 不预先打印"请输入密码"——那会诱使你在 ssh 就绪前输入,导致明文回显。
# 让 ssh 自己弹原生密码提示(届时输入不回显)。
printf '正在连接 %s@%s:%s —— 等 ssh 弹出 "password:" 提示再输入(输入不回显)...\n' "$BOOTUSER" "$HOST" "$PORT"
if ssh -M -S "$DIR/ctrl.sock" -o ControlPersist=1h -o ConnectTimeout=10 -fN -p "$PORT" "$BOOTUSER@$HOST"; then
  printf '建立 root 连接... done\n'
  printf '凭据目录: %s\n' "$DIR"
  printf '已就绪 —— 回到 Claude,后续阶段由 skill 驱动(全程不再输密码)。\n'
else
  printf '建立 root 连接... FAILED\n'
  printf '  └─ 连接未建立。可能原因(从最可能起):\n'
  printf '     · sshd 没监听该端口 / 真实 SSH 端口不是 %s\n' "$PORT"
  printf '     · 防火墙·云安全组·anti-DDoS 拦了(TCP 能连但不回 banner 常属此类)\n'
  printf '     · 服务器不允许 root 密码登录\n'
  printf '     · 地址/端口/密码有误\n'
  exit 1
fi
