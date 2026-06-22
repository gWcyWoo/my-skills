# dpt Docker 框架约束（后续每个容器/compose 服务必须遵守）

本机只部署 **Docker rootless 环境 + 框架**；具体容器由后续 skill 基于此框架添加。
隔离形态：**rootless**（daemon 以 `opt` 跑，逃逸≠宿主 root）。宿主 nginx 是唯一公网边缘，
**所有容器只 `127.0.0.1` 或仅内网，绝不对公网发布端口**。

## daemon 层已强制（`~/.config/docker/daemon.json`，对所有容器生效）
- `no-new-privileges: true` —— 容器禁提权
- `log-driver: journald` —— 并入宿主 journald（已限额），杜绝日志撑盘
- 网络隔离靠**每栈显式 user 网络 + 不发布公网端口**（rootless 下 `icc:false`/`userland-proxy:false` 不可用——要 `bridge-nf-call-iptables`，rootless netns 里没有，会让 daemon 起不来）
- `default-ulimits.nofile 65535`、`default-address-pools`

## 每个服务必须满足（compose 里，见 compose.skeleton.yaml）
- 镜像**钉 digest**（`image: name@sha256:...`），禁 `:latest`；多阶段构建;上线前 **Trivy 扫**
- `read_only: true` + tmpfs/named volume；`cap_drop: [ALL]` 再按需最小 `cap_add`
- `security_opt: [no-new-privileges:true]`；非 root `user:`
- `deploy.resources.limits.memory` 设上限；`healthcheck` + `restart: unless-stopped`
- 端口：**只有给宿主 nginx 的 `127.0.0.1:9000`（php-fpm）之类**;db/redis 仅内网不发布
- secrets 走 docker secrets / 文件挂载，**绝不进 env/Dockerfile**
- 禁 `network_mode: host`、禁挂 `/var/run/docker.sock`、禁 `privileged: true`

## rootless 注意
- 绑端口 <1024 不行 → 不需要（宿主 nginx 绑 443，容器只 127.0.0.1 高端口）
- 真实客户端 IP 由宿主 nginx 透传（`X-Forwarded-For`），容器侧别依赖 remote_addr
- 镜像更新**不归 unattended-upgrades**（那只管宿主）→ 钉版本 + 受控重建（CI/手动）
- 中国网络:Docker Hub 可能慢/被墙 → 业务上线时按需在 daemon.json 加 `registry-mirrors`
