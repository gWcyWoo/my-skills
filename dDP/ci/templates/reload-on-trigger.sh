#!/usr/bin/env bash
# dDP opt 侧 reload 执行器 —— CI 触哨兵后,优雅 reload php-fpm(USR2:清 opcache、近零停机),
# 再写"落地标记" .reload-done 供 CI 等待:确认 reload 已执行,免健康检查抢跑旧 opcache 代码。
# 装到运营用户 ~/dpt-docker-framework/bin/dpt-reload-on-trigger,由 systemd --user path 单元调起。
set -u
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/docker.sock"
name="${1:?need app name}"
docker kill -s USR2 "${name}-php" >/dev/null 2>&1 || true
sleep 2   # 等 graceful reload 落地(worker 重启、opcache 清空)再标记
# 落地标记写进 src(CI 经 ACL 可读);mtime 单调递增,供 deploy 判"reload 已执行"。
src="$HOME/dpt-docker-framework/apps/${name}/src"
[ -d "$src" ] && touch "$src/.reload-done" 2>/dev/null || true
