#!/usr/bin/env bash
# dDP 共享库:配置加载 + 输出风格 + 远端执行(全程 cert,绝不 root)。被 check/* 等脚本 source。
# 本文件在「你的本机」执行(macOS bash 3.2 兼容,勿用 ${var,,} 等 4.x 语法)。
#
# 连接模型:dDP 只部署到 dDLN 已准备好的机器(运营用户 + 证书 + rootless docker,root 已锁)。
# 因此**无 root 通道、无 connect.sh、不输密码**,只有两条 cert 通道:
#   rexec       —— 证书登录运营用户 + sudo(宿主侧只读检查,如 nginx -t / 读 /etc/nginx)。
#                  依赖 dDLN 暂留的 NOPASSWD;dDLN 最后模块撤销后此处会要密码(届时再议)。
#   rexec_user  —— 证书登录运营用户、**不 sudo**(rootless docker / systemctl --user),
#                  注入 XDG_RUNTIME_DIR/DBUS/DOCKER_HOST。
# 复用 dDLN 建好的 profile:~/.ssh/<profile>/dpt.conf(host/user/port)。

# ---- 配置加载 ----
# dpt_load <profile> —— source ~/.ssh/<profile>/dpt.conf(dDLN 写),再按目录推导本地路径。
dpt_load() {
  local dir="$HOME/.ssh/$1" conf="$HOME/.ssh/$1/dpt.conf"
  if [ ! -f "$conf" ]; then
    printf 'dDP: 找不到 profile 配置 %s —— 该 profile 须先由 dDLN 创建/准备。\n' "$conf" >&2
    exit 1
  fi
  . "$conf"
  export DPT_PROFILE="$1"
  export DPT_DIR="$dir"
  export DPT_KEY="$dir/${DPT_USER}_ed25519"
  export DPT_PWFILE="$dir/${DPT_USER}.sudo"
}

# ---- 输出风格(透明可审计:每步先回显命令,再执行) ----
section() { printf '\n# %s\n' "$1"; }

# dpt_mask <text> —— 回显前把运营密码值打码(dDP 不生成密码,纯保险)。
dpt_mask() {
  local t="$1" pw=
  if [ -n "${DPT_PWFILE:-}" ] && [ -f "$DPT_PWFILE" ]; then pw="$(cat "$DPT_PWFILE" 2>/dev/null)"; fi
  [ -n "$pw" ] && t="${t//$pw/*****}"
  printf '%s' "$t"
}
# show "<操作>" "<命令文本>" —— 审计行:`# <操作>,命令 <脱敏命令>`。
show() { printf '# %s,命令 %s\n' "$1" "$(dpt_mask "$2")"; }
note() { printf '%s\n' "$1"; }
fail() {
  printf 'FAILED\n'
  [ -n "${1:-}" ] && printf '%s\n' "$1" | sed 's/^/  └─ /'
  exit 1
}
# run "标签" cmd... —— 先回显命令再执行;成功 → done,失败 → FAILED+stderr 并退出。
run() {
  local label="$1"; shift
  show "$label" "$*"
  local out
  if out="$("$@" 2>&1)"; then printf '  → done\n'; else printf '  → '; fail "$out"; fi
}

# ---- 远端执行(全程 cert,无 root 分支) ----
# rexec "<shell 片段>" —— 证书登录运营用户 + sudo 跑(宿主侧)。片段从 stdin 喂给远端 `sudo bash`。
# 片段里要在「远端」展开的 $ 写成 \$;本机变量正常展开。
rexec() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -i "$DPT_KEY" -p "$DPT_PORT" \
      "$DPT_USER@$DPT_HOST" "sudo bash -s" <<<"$*"
}
# rexec_user "<shell 片段>" —— 证书登录运营用户、**不 sudo**(rootless docker / systemctl --user)。
# 注入 XDG_RUNTIME_DIR / DBUS / DOCKER_HOST(配合 dDLN 开的 enable-linger),非交互 ssh 下也能用。
rexec_user() {
  local pre='export XDG_RUNTIME_DIR=/run/user/$(id -u); export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus; export PATH=$HOME/bin:/usr/bin:/usr/sbin:$PATH; export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock'
  ssh -o BatchMode=yes -o ConnectTimeout=8 -i "$DPT_KEY" -p "$DPT_PORT" \
      "$DPT_USER@$DPT_HOST" "bash -s" <<<"$pre
$*"
}

# rexec_in "<远端命令>" —— 证书 + sudo 跑远端命令,本函数 stdin 作其 stdin(写宿主 root 文件:`sudo tee`)。
rexec_in() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -i "$DPT_KEY" -p "$DPT_PORT" \
      "$DPT_USER@$DPT_HOST" "sudo $*"
}
# rexec_user_in "<远端命令>" —— 以运营用户(不 sudo)跑远端命令,本函数 stdin 作其 stdin(写 opt 文件:`cat > 文件`)。
rexec_user_in() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 -i "$DPT_KEY" -p "$DPT_PORT" \
      "$DPT_USER@$DPT_HOST" "$*"
}

# ---- 资源推导(物理内存 → 容器内存上限 + pm.max_children;一个预算驱动两者,构造上不 OOM) ----
# dpt_calc_resources [exclude_app] —— 读远端「物理总内存 MemTotal」(稳定,不随负载抖),扣掉给宿主的
# 预留 + 其它 app 已承诺的内存限额,得到本 app 预算;由预算同时反推 mem 与 max_children,二者恒满足
# 不变式  MEM = max_children × PER_WORKER + OVERHEAD  → 满载也不会超限 OOM。
# exclude_app:重算某 app 时排除其自身限额(避免把自己算进 COMMITTED);probe 新建时不传(计入全部已有)。
# 旋钮(单一真相源):PER_WORKER=单 worker 保守内存估(有真实负载后用 docker stats 校准);
#   OVERHEAD=fpm master + opcache 共享(128+16)+ buffer;RESERVE=给 OS+nginx+daemon 的预留(占比/下限取大)。
# 输出单行(供解析):CALC total=.. committed=.. reserve=.. budget=.. mem=<N>m max_children=<N>
dpt_calc_resources() {
  local exclude="${1:-__none__}"
  rexec_user '
    PER_WORKER_MB=80; OVERHEAD_MB=200; RESERVE_FRAC=30; RESERVE_FLOOR_MB=768; MC_MIN=4; MC_MAX=64
    TOTAL=$(free -m | awk "/^Mem:/{print \$2}")
    COMMITTED=0
    for f in "$HOME"/dpt-docker-framework/apps/*/compose.yaml; do
      [ -e "$f" ] || continue
      case "$f" in */'"$exclude"'/*) continue;; esac
      v=$(grep -oE "memory: *[0-9]+[mg]" "$f" 2>/dev/null | grep -oE "[0-9]+[mg]" | head -1)
      case "$v" in *g) v=$(( ${v%g} * 1024 ));; *m) v=${v%m};; *) v=0;; esac
      COMMITTED=$(( COMMITTED + v ))
    done
    RES_PCT=$(( TOTAL * RESERVE_FRAC / 100 ))
    RESERVE=$(( RES_PCT > RESERVE_FLOOR_MB ? RES_PCT : RESERVE_FLOOR_MB ))
    BUDGET=$(( TOTAL - RESERVE - COMMITTED ))
    MC=$(( (BUDGET - OVERHEAD_MB) / PER_WORKER_MB ))
    [ $MC -lt $MC_MIN ] && MC=$MC_MIN
    [ $MC -gt $MC_MAX ] && MC=$MC_MAX
    MEM=$(( MC * PER_WORKER_MB + OVERHEAD_MB ))
    printf "CALC total=%s committed=%s reserve=%s budget=%s mem=%sm max_children=%s\n" \
      "$TOTAL" "$COMMITTED" "$RESERVE" "$BUDGET" "$MEM" "$MC"
  '
}
