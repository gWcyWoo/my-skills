#!/usr/bin/env bash
# dDLN / account / nopasswd_cmd —— 打印「临时开/关 opt 的 sudo NOPASSWD」命令(你在自己终端跑;密码不进对话)。
# 不执行、不碰服务器:只读 profile 拼出现成命令。on=免密 sudo(临时运维写宿主用);off=恢复加固态(sudo 需口令)。
# 命令用 mktemp + visudo -cf 校验后再 install,防写坏 sudoers 把自己锁出。
# 用法: nopasswd_cmd.sh <profile> [on|off]   (不给 on/off 则两个都打印)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: nopasswd_cmd.sh <profile> [on|off]}"
WHICH="${2:-both}"
SUDOERS="/etc/sudoers.d/dpt-$DPT_USER"

section "sudo NOPASSWD 开关命令($DPT_USER@$DPT_HOST;在你自己终端跑,密码不进对话)"

[ "$WHICH" != off ] && cat <<EOF
【开启 NOPASSWD —— 临时免密 sudo(用于 dDP 写宿主 / 配证书等运维)】
  ssh -i $DPT_KEY -p $DPT_PORT $DPT_USER@$DPT_HOST
  # 登上去后(当前若需口令会提示输入):
  t=\$(mktemp) && printf '$DPT_USER ALL=(ALL) NOPASSWD:ALL\\n' > "\$t" && sudo visudo -cf "\$t" && sudo install -m0440 -o root -g root "\$t" $SUDOERS && rm -f "\$t" && echo 'NOPASSWD on'
EOF

[ "$WHICH" = both ] && printf '\n'

[ "$WHICH" != on ] && cat <<EOF
【关闭 NOPASSWD —— 恢复加固态(sudo 仍可用但需口令)】
  ssh -i $DPT_KEY -p $DPT_PORT $DPT_USER@$DPT_HOST
  t=\$(mktemp) && printf '$DPT_USER ALL=(ALL) ALL\\n' > "\$t" && sudo visudo -cf "\$t" && sudo install -m0440 -o root -g root "\$t" $SUDOERS && rm -f "\$t" && echo 'NOPASSWD off'
EOF

printf '\n注:① 命令先 mktemp+visudo 校验再安装,语法错不会写坏 sudoers。② off 后 opt 仍能 sudo,只是要口令;\n'
printf '    绝不会删 %s(opt 不在 sudo 组,删了会彻底失去 sudo)。③ root 已锁,务必保证 opt 始终能 sudo。\n' "$SUDOERS"
