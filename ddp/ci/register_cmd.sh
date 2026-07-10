#!/usr/bin/env bash
# dDP / ci / register_cmd —— 16c:打印 gitlab-runner register 命令(你在服务器终端跑,token 不进对话)。
# token 是密钥,只在你的终端输入,绝不发到这里(同 connect.sh 的安全边界)。用法: register_cmd.sh <profile> <tag>
# <tag> 必传,且须与 16b render_ci 生成的 pipeline tag 一字不差(规范 <app>-<env>-deploy,如 api-prod-deploy)。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: register_cmd.sh <profile> <tag>}"
TAG="${2:?缺 tag —— 用 16b 渲染出的那个(规范 <app>-<env>-deploy,如 api-prod-deploy)}"

section "注册 runner(你在服务器终端执行,token 自己输)"
cat <<EOF
[REVIEW:fix] GitLab 16+ 起「注册令牌(registration-token)」流程已废弃,18.x 默认禁用;
            必须用「新建 runner → 认证令牌(glrt-)」流程,否则注册会被拒。

1) 在 GitLab → 项目 Settings → CI/CD → Runners → "New project runner":
   · Tags 填: $TAG   · 取消 "Run untagged jobs"   · 勾 "Lock to current projects"
   创建后复制 runner 认证令牌(glrt- 开头)。
   ⚠️ Tags 必须【唯一】= 上面这个值(与 render_ci 生成的 pipeline tag 一致)。绝不要用 deploy 等通用 tag——
      共享 GitLab 上别的 runner 同名 tag 会抢走任务(落到没装 php/composer 的机器,job 必败)。
      且务必【取消 Run untagged jobs】,否则本 runner 还会去抢无 tag 任务。

2) 证书登录服务器:
   ssh -i $DPT_KEY -p $DPT_PORT $DPT_USER@$DPT_HOST

3) 注册(token 只在你终端输入,绝不发到这里;tag/locked 已在第 1 步 UI 设定):
   sudo gitlab-runner register \\
     --non-interactive \\
     --url http://gitlab.oklik.com \\
     --token '<glrt-你的认证令牌>' \\
     --executor shell \\
     --description "dDP shell runner ($DPT_HOST)"

注:① URL 用 http(据 ntest 实测该实例为 http;若你的实例已上 https 则改之)。
    ② 若 runner 改为「user-mode 非 root daemon」,上面 sudo 改为 sudo -u gitlab-runner(config 落 ~gitlab-runner/.gitlab-runner/)。
    ③ register 非幂等:重注册会向 config.toml 追加一个 [[runners]]。如需重注册,先
       sudo gitlab-runner unregister --name "dDP shell runner ($DPT_HOST)"  再重跑上面命令。
EOF
