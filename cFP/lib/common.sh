#!/usr/bin/env bash
# cFP 公共助手:统一的每步输出纪律 + fvm 定位。被各 script/*.sh source。
# 输出纪律:每个逻辑步骤打印一行 "标签... done";失败打印 "标签... FAILED" 并缩进附被吞 stderr;
# 命令本身的 stdout/stderr 默认静默,只有 FAILED 才浮现。

# 普通信息行(用于打印检测到的版本等)。
info() { printf '%s\n' "$*"; }

# step "标签" cmd [args...] —— 运行命令,静默输出;成功打印 "标签... done",
# 失败打印 "标签... FAILED" 并缩进附被吞的 stdout/stderr,返回原始退出码。
step() {
  local label="$1"; shift
  local out rc
  if out="$("$@" 2>&1)"; then
    printf '%s... done\n' "$label"
    return 0
  else
    rc=$?
    printf '%s... FAILED\n' "$label"
    printf '%s\n' "$out" | sed 's/^/    /'
    return "$rc"
  fi
}

# fvm_bin —— 解析 fvm 可执行路径:优先 PATH,其次官方脚本默认安装位 ~/fvm/bin/fvm。
# 找不到则回显空串(调用方据此判断未安装)。规避 harness 各 Bash 调用 PATH 不持久的问题。
fvm_bin() {
  if command -v fvm >/dev/null 2>&1; then
    command -v fvm
  elif [ -x "$HOME/fvm/bin/fvm" ]; then
    printf '%s\n' "$HOME/fvm/bin/fvm"
  fi
}
