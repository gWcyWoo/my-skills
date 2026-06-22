#!/usr/bin/env bash
# dDP / ci / cage_app —— 16a-3(每项目):ACL 权限笼 + opt 侧 USR2 reload 监听。
# ACL 走 rexec(sudo);reload 监听走 rexec_user(opt,systemd --user)。幂等。
# 用法: cage_app.sh <profile> <name>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: cage_app.sh <profile> <name>}"
NAME="${2:?缺 name}"
TPL="$ROOT/ci/templates"

HOME_DIR="$(rexec_user 'printf %s "$HOME"')"; [ -n "$HOME_DIR" ] || fail "无法解析运营用户家目录"
FW="$HOME_DIR/dpt-docker-framework"
SRC="$FW/apps/$NAME/src"

section "权限笼 + reload 监听: $NAME"

# ---- ACL 笼(root)----
run "祖先链仅 x(可穿不可枚举)" rexec "
  set -e
  setfacl -m u:gitlab-runner:x '$HOME_DIR' '$FW' '$FW/apps' '$FW/apps/$NAME'
"
run "src 给 gitlab-runner rwX(含默认 ACL)" rexec "
  set -e
  setfacl -R -m  u:gitlab-runner:rwX '$SRC'
  setfacl -R -d -m u:gitlab-runner:rwX '$SRC'
"
# [REVIEW:fix] rootless userns:容器内 33 → 宿主 uid = subuid_base + 32(实测 opt 100000 → 100032)。
# .env 属主设为该映射 uid + 0400 → 容器(app)可读;opt/gitlab-runner 非属主读不到;
# 再叠 ACL 拒 gitlab-runner(src 默认 ACL 会让新文件继承 rwX,必须显式覆盖)。
run ".env:容器可读 + 拒 CI(rootless 映射属主 0400 + ACL)" rexec "
  set -e
  base=\$(grep '^$DPT_USER:' /etc/subuid | head -1 | cut -d: -f2)
  [ -n \"\$base\" ] || { echo '无法解析 $DPT_USER 的 subuid base'; exit 1; }
  www=\$(( base + 32 ))
  [ -f '$SRC/.env' ] || : > '$SRC/.env'
  chown \"\$www\":\"\$www\" '$SRC/.env'
  chmod 0400 '$SRC/.env'
  setfacl -m u:gitlab-runner:--- '$SRC/.env'
"

# ---- opt 侧 reload 监听(systemd --user)----
run "建哨兵 + bin/ 目录(幂等:哨兵已存在不重触,免重跑多余 reload)" rexec_user "mkdir -p $FW/bin; [ -e $SRC/.reload-trigger ] || touch $SRC/.reload-trigger"
show "装 reload 执行器" "cat > $FW/bin/dpt-reload-on-trigger"
if rexec_user_in "cat > $FW/bin/dpt-reload-on-trigger && chmod 0755 $FW/bin/dpt-reload-on-trigger" < "$TPL/reload-on-trigger.sh"; then printf '  → done\n'; else fail "装执行器失败"; fi

put_unit() { # put_unit <模板> <单元文件名>
  show "装 $2" "cat > ~/.config/systemd/user/$2"
  if sed -e "s|__NAME__|$NAME|g" -e "s|__APP_SRC__|$SRC|g" "$TPL/$1" \
       | rexec_user_in "mkdir -p \$HOME/.config/systemd/user && cat > \$HOME/.config/systemd/user/$2"; then printf '  → done\n'; else fail "装 $2 失败"; fi
}
put_unit reload-listener.service.tmpl "dpt-reload-$NAME.service"
put_unit reload-listener.path.tmpl    "dpt-reload-$NAME.path"

run "启用 reload 监听" rexec_user "systemctl --user daemon-reload; systemctl --user enable --now dpt-reload-$NAME.path"
run "校验 监听 active" rexec_user "systemctl --user is-active dpt-reload-$NAME.path >/dev/null 2>&1"
printf '\n权限笼 + reload 监听完成 ✅(runner 只能写 %s;改码触哨兵 → USR2)\n' "apps/$NAME/src"
