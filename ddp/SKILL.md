---
name: ddp
description: Deploy a PHP Docker project, configure its env/CI, or retune resources on an existing dDLN server.
---

# dDP

在 dDLN 已准备的服务器上部署 PHP Docker 项目，或执行明确的 env、CI、资源重调子动作。

## 连接与范围

- 只复用 `~/.ssh/<profile>/` 的运营用户证书连接；不用 root、不处理密码、不新建 profile。用 `lib/list_profiles.sh` 验证用户指定的 profile；仅目标未明确时询问。
- 部署前用 `script/preflight.sh`、`check/login.sh`、`check/nginx.sh`、`check/docker.sh` 检查就绪条件。登录失败就停止远端后续检查；登录成功后合并报告 nginx/Docker 缺项。
- 环境检查只查不修，缺项由对应 dDLN 模块处理。部署可以写本项目 nginx vhost；“不修环境”不禁止已授权的项目配置。
- 默认布局 `~/dpt-docker-framework/apps/<name>/{src,deploy,compose.yaml}`。保留 rootless、只读代码挂载、容器最小权限和 loopback 发布端口。db/redis 不归本流程。
- 复用已明确的 app、PHP 版本、域名、端口和资源预算。新资源计划或目标变化时展示具体值确认；同一已授权计划的 scaffold/build/up/vhost/健康检查连续完成。
- 不打印 `.env`、私钥或 runner token；仅接收路径，秘密由既有脚本直传。保留备份、nginx 校验回滚及健康检查。

## 路由

- 完整部署：就绪检查后读 [deploy.md](references/deploy.md)。
- 仅 CI：核实目标 profile/app/分支后读 [ci.md](references/ci.md)，不执行部署流程。
- `retune <app>`：运行 `deploy/retune.sh <profile> <name>`，保留脚本的资源重算、备份和按需重建，报告 `RETUNE` 摘要。
- 仅配置 `.env`：确认目标 profile/app 与本地文件路径后运行 `ci/set_env.sh <profile> <name> <path>`。路径与写入目标已明确授权就执行；没有路径时给出手动命令。保留旧文件备份、reload 和健康验证，不读出内容。

所有脚本相对于本技能目录。对话报告实际结果、失败原因和产物路径，不逐条复述脚本进度。容器健康、代码已交付和 TLS 生效是不同边界，分别按证据说明。
