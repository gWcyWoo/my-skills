## docker 模块编排(edge 之后;**只装 rootless Docker 环境 + 框架,容器留给后续 skill**)
**定位**:rootless Docker(daemon 以 opt 跑,逃逸≠宿主 root)+ Compose + 框架约束;具体容器(php-fpm/db/redis)由后续 skill 基于 `~/dpt-docker-framework/` 添加;容器全 `127.0.0.1`,宿主 nginx 是唯一公网边缘。

**Phase D0–D4(都幂等):**
- D0 `preflight.sh`
- D1 `install_docker.sh <profile>` —— **root 部分**(cert+sudo):Docker 官方源 + 引擎/compose/buildx + rootless 前置(uidmap/dbus-user-session/slirp4netns/fuse-overlayfs)+ 禁&mask rootful + subuid/subgid + `enable-linger`;装引擎 **detached**。
- D2 `setup_rootless.sh <profile>` —— **opt 部分**(走 `rexec_user`,不 sudo):`dockerd-rootless-setuptool.sh install` + 加固 `~/.config/docker/daemon.json` + `DOCKER_HOST` + `systemctl --user` 起 daemon。
- D3 `deploy_framework.sh <profile>` —— `FRAMEWORK.md` + 安全 `compose.skeleton.yaml` → `~/dpt-docker-framework/`。
- D4 `close/close_check.sh <profile>`。

**约定/取舍**:rootless(无 docker 组、每用户自管 → auditd 天然记账)· 日志 journald · 容器全 `127.0.0.1` · userns 保留 · 镜像钉版本+受控重建(**不归 unattended-upgrades,它只管宿主**)。

**本次踩到、已固化**:
- **`icc:false`/`userland-proxy:false` 在 rootless 下会让 daemon 起不来**(需 `/proc/sys/net/bridge/bridge-nf-call-iptables`,rootless netns 里没有)。daemon.json **去掉这两项**;网络隔离改靠"每栈显式 user 网络 + 不发布公网端口"。
- **用户态操作必须 `rexec_user`(不 sudo)**:rootless 的 setuptool / `systemctl --user` / `~/.config/docker` 都属 opt 自己的会话,要以 opt 跑并注入 `XDG_RUNTIME_DIR`/DBUS(配合 `enable-linger`),不能 sudo。
