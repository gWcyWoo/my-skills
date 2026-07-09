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
run "祖先链仅 x(gitlab-runner CI + www-data 宿主 nginx 边缘,可穿不可枚举)" rexec "
  set -e
  setfacl -m u:gitlab-runner:x -m u:www-data:x '$HOME_DIR' '$FW' '$FW/apps' '$FW/apps/$NAME'
"
run "src ACL:CI 写 + 容器 php-fpm 读 + 宿主 nginx 读(含默认 ACL,CI 新建文件继承)" rexec "
  set -e
  # 加固机(opt 家 750 / umask 027)下,src 下 other::--- 会挡死两个'other'身份的读者:
  #   ① rootless 容器 www —— 宿主 uid = subuid_base + 32(容器内 33 的映射),读代码执行;
  #   ② 宿主 nginx(www-data)—— 读 docroot(src/public)做静态 / try_files。
  # 二者都非属主非组 → 必须显式授 ACL(access + default,default 供 CI 新建的 public/ 等继承)。
  base=\$(grep '^$DPT_USER:' /etc/subuid | head -1 | cut -d: -f2)
  [ -n \"\$base\" ] || { echo '无法解析 $DPT_USER 的 subuid base'; exit 1; }
  www=\$(( base + 32 ))
  setfacl -R -m  u:gitlab-runner:rwX -m u:\$www:rX -m u:www-data:rX '$SRC'
  setfacl -R -d -m u:gitlab-runner:rwX -m u:\$www:rX -m u:www-data:rX '$SRC'
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
  # 只允许容器 www 读 .env(它是属主);src 默认 ACL 会让 .env 继承 gitlab-runner/www-data 的 rX,
  # 必须显式拒 —— 否则 CI(gitlab-runner)或宿主 nginx(www-data)能读到生产密钥。
  setfacl -m u:gitlab-runner:--- -m u:www-data:--- '$SRC/.env'
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
