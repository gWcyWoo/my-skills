# PHP 项目部署

8. **项目名**:仅询问缺失的 `<name>`(prose;用于 apps/<name>、容器/镜像名、vhost、端口)。
9. **是否 PHP + 版本**:复用已知项目类型与版本；非 PHP 暂不支持，版本缺失才询问(如 `7.4` / `8.3`)。
10. **探测参数**:跑 `bash ~/.agents/skills/ddp/deploy/probe.sh <profile>`,读末行 `PROBE port=.. mem=.. max_children=..`;把**端口**、**容器内存上限**与 **pm.max_children** 展示给用户**确认**(可改;prose,绝不自动定)。内存与 max_children 由「物理内存的同一预算」自洽推导(算法在 `lib/common.sh` 的 `dpt_calc_resources`,满足 `MEM=max_children×PER_WORKER+OVERHEAD`,构造上不 OOM)。
11. **域名**:问 vhost 的 `server_name`(TLS 先用自签证书,域名就绪后再 certbot 换真证)。
12. **scaffold(容器内安全+性能配置,先于 nginx)**:跑 `bash ~/.agents/skills/ddp/deploy/scaffold_app.sh <profile> <name> <ver> <port> <max_children> <mem_limit>`(`<mem_limit>` 取 probe 的 `mem=`,如 `2680m`)。
13. **build(跨境长操作 detached)**:跑 `bash ~/.agents/skills/ddp/deploy/build_image.sh <profile> <name>` —— **后台运行并查看状态与日志**;结尾非 `success` → STOP、贴日志。
14. **up**:跑 `bash ~/.agents/skills/ddp/deploy/up.sh <profile> <name>` —— 确保 `dpt-net`、`compose up -d`、等 healthy(空 src 也应 healthy)。未健康 → STOP、贴 `docker logs`。
15. **nginx vhost**:跑 `bash ~/.agents/skills/ddp/deploy/nginx_vhost.sh <profile> <name> <port> <domain>` —— 写宿主 vhost、`nginx -t`(失败自动删本 vhost 回滚)、reload。

CI/CD 仅在用户要求时读取 [ci.md](ci.md)。

17. 报告:容器已起 + vhost 已挂(443 → 127.0.0.1:port);**代码待 CI 交付**(src 暂空);TLS 自签待 certbot。
