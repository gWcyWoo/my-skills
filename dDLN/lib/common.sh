#!/usr/bin/env bash
# dpt 共享库:配置加载 + 输出风格 + 远端特权执行。被各阶段脚本 source。
# 本文件在「你的本机」执行(macOS bash 3.2 兼容,勿用 ${var,,} 等 4.x 语法)。
#
# 输出契约(透明可审计):每步先回显脱敏命令 `# <操作>,命令 <cmd>`,再执行;
# 成功 → done / ✓,失败 → FAILED 并贴出 stderr。运营密码回显时打码为 *****,公钥过长截断。
#
# 连接模型:connect.sh 开一条 root ControlMaster(用户输一次密码,不落盘);
# 之后所有脚本经 socket 复用,无需再输密码。配置在 ~/.ssh/<profile>/dpt.conf。

# ---- 配置加载 ----
# dpt_load <profile> —— source ~/.ssh/<profile>/dpt.conf(由 connect.sh 写)。
dpt_load() {
  local p="${1:?dpt_load 需要 profile}" dir="$HOME/.ssh/$1" conf="$HOME/.ssh/$1/dpt.conf"
  if [ ! -f "$conf" ]; then
    printf 'dpt: 找不到配置 %s —— 请先运行 connect.sh\n' "$conf" >&2
    exit 1
  fi
  . "$conf"
  # 目录名 = 唯一真源:source 后重算所有"路径/名"类变量,使 profile 目录可随意重命名/移动而不破。
  # (服务器侧事实 DPT_HOST/PORT/USER/DROPIN 沿用文件里的值。)
  # 必须 export:这些原本由 dpt.conf 以 export 写出、被 run_checks.sh 等子进程继承;
  # 解耦后改在此推导,若不 export,子进程(set -u)里 $DPT_KEY/$DPT_CTRL 未绑定 → rexec 中止 → 审计假阴性。
  export DPT_PROFILE="$1"
  export DPT_DIR="$dir"
  export DPT_KEY="$dir/${DPT_USER}_ed25519"
  export DPT_PWFILE="$dir/${DPT_USER}.sudo"
  export DPT_CTRL="$dir/ctrl.sock"
}

# ---- 输出风格(透明可审计:每步先回显脱敏命令,再执行) ----
section() { printf '\n# %s\n' "$1"; }

# dpt_mask <text> —— 命令回显前,把运营密码值整体替换成 *****。
# 密码字符集(provision 生成)无 glob 元字符,${t//$pw/...} 按字面替换安全。
dpt_mask() {
  local t="$1" pw=
  if [ -n "${DPT_PWFILE:-}" ] && [ -f "$DPT_PWFILE" ]; then pw="$(cat "$DPT_PWFILE" 2>/dev/null)"; fi
  [ -n "$pw" ] && t="${t//$pw/*****}"
  printf '%s' "$t"
}
# show "<操作>" "<命令文本>" —— 审计行:`# <操作>,命令 <脱敏命令>`(供用户复核)。
# 密码 → *****;过长的公钥 base64 串截断(仅为可读,公钥非密),其余一律明文。
show() {
  local cmd; cmd="$(dpt_mask "$2")"
  cmd="$(printf '%s' "$cmd" | sed -E 's/(AAAA[A-Za-z0-9+/]{8})[A-Za-z0-9+/]{16,}/\1…/g')"
  printf '# %s,命令 %s\n' "$1" "$cmd"
}

step()    { printf '%s... ' "$1"; }               # 旧式紧凑单行(仍用于少数本地小步)
ok()      { printf 'done\n'; }
note()    { printf '%s\n' "$1"; }                 # 收敛步骤但带说明
fail()    {
  printf 'FAILED\n'
  [ -n "${1:-}" ] && printf '%s\n' "$1" | sed 's/^/  └─ /'
  exit 1
}
# run "标签" cmd... —— 先回显脱敏命令,再执行;成功 → done,失败 → FAILED+stderr 并退出。
run() {
  local label="$1"; shift
  show "$label" "$*"
  local out
  if out="$("$@" 2>&1)"; then printf '  → done\n'; else printf '  → '; fail "$out"; fi
}

# ---- 远端特权执行 ----
# rexec "<shell 片段>" —— 以特权身份在远端跑该片段(片段从 stdin 喂给远端 bash)。
# 片段里要在「远端」展开的 $ 写成 \$;本机变量正常展开。
rexec() {
  # 注:不在此处全局 set -e —— 多命令片段里"有意忽略错误 + 末尾 true"的惯用法(如 dead-man's-switch
  # 撤销)会被 set -e 误杀,且后果危险(撤销失败 → ufw 被自动 disable)。
  # 防"假绿"的正确做法:关键写入在该 step 末尾显式校验(如 'test -s <文件> && grep ...'),见 install_nginx。
  if [ "${DPT_BOOT:-root}" = root ]; then
    # 特权 master 分支:master 由 connect.sh 以 DPT_BOOTUSER 建立。
    # 引导用户是 root → 命令直接以 root 跑;非 root(如 ubuntu)→ 经同一 socket `sudo` 提权。
    local bu="${DPT_BOOTUSER:-root}"
    if [ "$bu" = root ]; then
      ssh -S "$DPT_CTRL" "root@$DPT_HOST" "bash -s" <<<"$*"
    else
      ssh -S "$DPT_CTRL" "$bu@$DPT_HOST" "sudo bash -s" <<<"$*"
    fi
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 -i "$DPT_KEY" -p "$DPT_PORT" \
        "$DPT_USER@$DPT_HOST" "sudo bash -s" <<<"$*"
  fi
}

# rexec_in "<远端命令>" —— 把本函数的 stdin 作为「远端命令」的 stdin(用于 chpasswd 等)。
rexec_in() {
  if [ "${DPT_BOOT:-root}" = root ]; then
    local bu="${DPT_BOOTUSER:-root}"
    if [ "$bu" = root ]; then
      ssh -S "$DPT_CTRL" "root@$DPT_HOST" "$*"
    else
      ssh -S "$DPT_CTRL" "$bu@$DPT_HOST" "sudo $*"
    fi
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 -i "$DPT_KEY" -p "$DPT_PORT" \
        "$DPT_USER@$DPT_HOST" "sudo $*"
  fi
}

# rexec_user "<shell 片段>" —— 以运营用户(opt)身份在远端跑(**不 sudo**),供 rootless docker
# 等用户态操作。自动注入 XDG_RUNTIME_DIR / DBUS(配合 enable-linger),让非交互 ssh 下
# `systemctl --user` / rootless 工具可用。片段里远端展开的 $ 写成 \$。
rexec_user() {
  local pre='export XDG_RUNTIME_DIR=/run/user/$(id -u); export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus; export PATH=$HOME/bin:/usr/bin:/usr/sbin:$PATH; export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock'
  ssh -o BatchMode=yes -o ConnectTimeout=8 -i "$DPT_KEY" -p "$DPT_PORT" \
      "$DPT_USER@$DPT_HOST" "bash -s" <<<"$pre
$*"
}

# rexec_user_in "<远端命令>" —— 以 opt 身份跑远端命令,本函数 stdin 作其 stdin(用于 `cat > 文件`)。
rexec_user_in() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -i "$DPT_KEY" -p "$DPT_PORT" "$DPT_USER@$DPT_HOST" "$*"
}

# eff_cfg <directive> —— 远端 `sshd -T` 里该指令的生效值(小写指令名匹配)。
eff_cfg() { rexec "sshd -T 2>/dev/null" | grep -i "^$1 " | head -1 | cut -d' ' -f2-; }

# dropin_set <directive> <value> —— 幂等写入加固 drop-in(不 reload)。
dropin_set() {
  rexec "test -f '$DPT_DROPIN' || { install -m600 -o root -g root /dev/null '$DPT_DROPIN'; printf '# dpt hardening (managed). Remove to roll back.\n' > '$DPT_DROPIN'; }
         sed -i \"/^$1 /Id\" '$DPT_DROPIN'
         echo '$1 $2' >> '$DPT_DROPIN'"
}

# reload_sshd —— 校验并 reload(不 restart,保留现有会话)。
reload_sshd() {
  rexec "sshd -t && { systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || service ssh reload 2>/dev/null; }"
}

# open_firewall <port> —— 放行服务器自带防火墙(云安全组需用户自行处理)。
open_firewall() {
  show "放行服务器防火墙端口 $1" "ufw allow $1/tcp 或 firewall-cmd --add-port=$1/tcp(按已装者执行)"
  rexec "command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active && ufw allow $1/tcp >/dev/null 2>&1
         command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1 && { firewall-cmd --permanent --add-port=$1/tcp >/dev/null 2>&1; firewall-cmd --reload >/dev/null 2>&1; }
         true" >/dev/null 2>&1
  printf '  → done\n'
  printf '  └─ 云厂商安全组需你自行放行端口 %s\n' "$1"
}
