#!/usr/bin/env bash
# dDC 共享库:profile 加载 + 【只读】远端执行 + 检查/打印助手。被 dDC.sh 与 lib/checks.sh source。
# 本文件在「你的本机」执行(macOS bash 3.2 兼容,勿用 ${v,,} 等 4.x 语法)。
#
# 【硬边界 · 无豁免】dDC 对【被审服务器】只读:仅发送读取/查询/校验/GET 类命令。
#   绝不:sudo 写、tee/sed -i/cp/mkdir/rm(远端)、docker run/build/up/create/rm/exec-写、systemctl 改状态。
#   仅本地会创建一个审计日志(./audit/check/<profile>_<date>.log)—— 那是规定产物,不是对目标的修改。
# 连接模型复用 dDLN/dDP 同一套 profile(~/.ssh/<profile>/dpt.conf;cert-only,绝不 root、绝不密码)。
#   rexec       —— 证书登录运营用户 + sudo,只用于【读取】root 文件(cat/grep/test/sshd -T/nginx -t)。
#   rexec_user  —— 证书登录运营用户、不 sudo(rootless docker / 用户态),注入 docker env,只发只读命令。

dpt_load() {
  local dir="$HOME/.ssh/$1" conf="$HOME/.ssh/$1/dpt.conf"
  [ -f "$conf" ] || { printf 'dDC: 找不到 profile 配置 %s —— 该 profile 须先由 dDLN 创建。\n' "$conf" >&2; exit 1; }
  . "$conf"
  export DPT_PROFILE="$1" DPT_DIR="$dir" DPT_KEY="$dir/${DPT_USER}_ed25519"
  # ssh 选项:含连接复用(ControlMaster),让数十次只读探测共用一条 TCP,显著提速。
  SSHO=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new
        -o ControlMaster=auto -o ControlPath=/tmp/dDC-cm-%C -o ControlPersist=30
        -i "$DPT_KEY" -p "$DPT_PORT")
}

# 只读:cert + sudo 读宿主 root 文件。片段从 stdin 喂给远端 `sudo bash -s`。
rexec()      { ssh "${SSHO[@]}" "$DPT_USER@$DPT_HOST" "sudo bash -s" <<<"$*"; }
# 只读:cert,不 sudo;注入 XDG_RUNTIME_DIR/DBUS/DOCKER_HOST(rootless docker / systemctl --user)。
rexec_user() {
  local pre='export XDG_RUNTIME_DIR=/run/user/$(id -u); export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus; export PATH=$HOME/bin:/usr/bin:/usr/sbin:$PATH; export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock'
  ssh "${SSHO[@]}" "$DPT_USER@$DPT_HOST" "bash -s" <<<"$pre
$*"
}

section() { printf '\n========== %s ==========\n' "$1"; }

DDC_PASS=0; DDC_FAIL=0
# chk <r|u> "<检查项>" "<检查目的>" "<远端只读测试>"
#   远端测试约定:合规 → 退出 0、不输出;不合规 → echo 原因(写明实际值 vs 期望)并 exit 1。
#   打印格式: 检查项(检查目的)-----success|fail;fail 时缩进打印原因。
chk() {
  local mode="$1" item="$2" purpose="$3" cmd="$4" out rc
  if [ "$mode" = r ]; then out="$(rexec "$cmd" 2>&1)"; rc=$?; else out="$(rexec_user "$cmd" 2>&1)"; rc=$?; fi
  if [ "$rc" -eq 0 ]; then
    DDC_PASS=$((DDC_PASS + 1))
    printf '%s(%s)-----success\n' "$item" "$purpose"
  else
    DDC_FAIL=$((DDC_FAIL + 1))
    printf '%s(%s)-----fail\n' "$item" "$purpose"
    printf '%s\n' "${out:-检查命令返回非零(无输出)}" | sed 's/^/    /'
  fi
}

# 已部署 app 枚举(rootless,只读)。无 app 时无输出。
dDC_apps() { rexec_user 'ls -1 "$HOME"/dpt-docker-framework/apps 2>/dev/null'; }
