#!/usr/bin/env bash
# dDLN / edge / nginx / configure_cert —— 子动作:给某 app 的 nginx vhost 配置【真实 TLS 证书】(替占位自签)。
# 部署后操作:cert 登录 opt + sudo(DPT_BOOT=sudo,无 root)。证书=公开;私钥=机密(rexec_in 管道直传、绝不打印)。
# 需 opt 的 sudo NOPASSWD 暂时开启(写 /etc/nginx/ssl + reload);本脚本配完【自动关闭 NOPASSWD 并验证】。
# 用法: configure_cert.sh <profile> <name> <证书文件路径> <私钥文件路径>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
. "$ROOT/lib/common.sh"
dpt_load "${1:?用法: configure_cert.sh <profile> <name> <证书路径> <私钥路径>}"
export DPT_BOOT=sudo                      # 部署后:cert 登录 opt + sudo(不走 root ControlMaster)
NAME="${2:?缺 name}"; CERT="${3:?缺 证书路径}"; KEY="${4:?缺 私钥路径}"

VHOST="/etc/nginx/conf.d/$NAME.conf"
DCRT="/etc/nginx/ssl/$NAME.crt"
DKEY="/etc/nginx/ssl/$NAME.key"
SUDOERS="/etc/sudoers.d/dpt-$DPT_USER"

section "配置 $NAME 的 TLS 证书(cert+sudo;私钥管道直传不显示)"

# [1/7] 本地校验证书+私钥(匹配 + 未加密)—— 失败 fast,不碰服务器
printf '[1/7] 本地校验证书/私钥\n'
[ -f "$CERT" ] || fail "证书文件不存在: $CERT"
[ -f "$KEY" ]  || fail "私钥文件不存在: $KEY"
grep -qi 'ENCRYPTED' "$KEY" && fail "私钥被口令加密;nginx 需无口令私钥,请先 openssl 解密后再配。"
cpub="$(openssl x509 -in "$CERT" -pubkey -noout 2>/dev/null)" || fail "证书无法解析(非 PEM x509?): $CERT"
kpub="$(openssl pkey -in "$KEY" -pubout 2>/dev/null)" || fail "私钥无法解析(格式错?): $KEY"
{ [ -n "$cpub" ] && [ "$cpub" = "$kpub" ]; } || fail "证书与私钥不匹配(公钥不一致)"
subj="$(openssl x509 -in "$CERT" -noout -subject 2>/dev/null | sed 's/^subject= *//')"
exp="$(openssl x509 -in "$CERT" -noout -enddate 2>/dev/null | sed 's/^notAfter=//')"
printf '  → 匹配 ✓  subject: %s  到期: %s\n' "$subj" "$exp"

# [2/7] 前置:sudo NOPASSWD 可用 + vhost 存在
printf '[2/7] 前置检查(sudo NOPASSWD 可用 + vhost 存在)\n'
sudostate="$(rexec_user 'sudo -n true 2>/dev/null && echo OK || echo NEEDPW')"
if [ "$sudostate" != OK ]; then
  printf '  → ✗ opt 当前【没有】NOPASSWD sudo。请你先在服务器手动【临时开启】,再重跑本动作:\n\n'
  printf '    ssh -i %s -p %s %s@%s\n' "$DPT_KEY" "$DPT_PORT" "$DPT_USER" "$DPT_HOST"
  printf "    echo '%s ALL=(ALL) NOPASSWD:ALL' | sudo tee %s >/dev/null && sudo chmod 0440 %s && echo enabled\n" "$DPT_USER" "$SUDOERS" "$SUDOERS"
  printf '\n  (开这一次即可;本脚本配完会【自动关闭】NOPASSWD。)\n'
  exit 2
fi
rexec "test -f '$VHOST'" >/dev/null 2>&1 || fail "找不到 vhost $VHOST —— 该 app 未由 dDP 部署?先部署再配证书。"
printf '  → sudo NOPASSWD 可用 ✓;vhost %s 存在 ✓\n' "$VHOST"

# [3/7] 上传证书(0644)+ 私钥(0600,机密管道直传不显示),属主 root
printf '[3/7] 上传证书/私钥到 /etc/nginx/ssl(私钥内容不显示)\n'
rexec_in "install -o root -g root -m 0644 /dev/stdin '$DCRT'" < "$CERT" || fail "上传证书失败"
rexec_in "install -o root -g root -m 0600 /dev/stdin '$DKEY'" < "$KEY"  || fail "上传私钥失败"
printf '  → %s (0644) + %s (0600 root) ✓\n' "$DCRT" "$DKEY"

# [4/7] 备份并改 vhost 指向新证书
printf '[4/7] 备份并更新 vhost 的 ssl_certificate / ssl_certificate_key\n'
ts="$(rexec 'date +%Y%m%d%H%M%S')"
rexec "cp -a '$VHOST' '$VHOST.bak.$ts'" >/dev/null 2>&1 || fail "备份 vhost 失败"
rexec "sed -i -E \"s|^([[:space:]]*)ssl_certificate[[:space:]]+[^;]+;|\\1ssl_certificate     $DCRT;|; s|^([[:space:]]*)ssl_certificate_key[[:space:]]+[^;]+;|\\1ssl_certificate_key $DKEY;|\" '$VHOST'" >/dev/null 2>&1 || fail "改 vhost 失败"
printf '  → 已改(备份 %s.bak.%s)✓\n' "$VHOST" "$ts"

# [5/7] nginx -t,失败回滚 vhost
printf '[5/7] nginx -t 校验\n'
if rexec "nginx -t" >/dev/null 2>&1; then
  printf '  → 通过 ✓\n'
else
  errout="$(rexec 'nginx -t 2>&1' | tail -3)"
  rexec "cp -a '$VHOST.bak.$ts' '$VHOST'" >/dev/null 2>&1
  fail "nginx -t 失败,已回滚 vhost。错误:$errout"
fi

# [6/7] reload nginx
printf '[6/7] reload nginx\n'
rexec "systemctl reload nginx" >/dev/null 2>&1 || fail "reload nginx 失败"
printf '  → 已 reload ✓\n'

# [7/7] 自动关闭 NOPASSWD(恢复加固态:改 sudoers 为需口令)+ 验证
printf '[7/7] 关闭 sudo NOPASSWD + 验证\n'
rexec "t=\$(mktemp); printf '%s ALL=(ALL) ALL\n' '$DPT_USER' > \"\$t\"; if visudo -cf \"\$t\"; then install -m0440 -o root -g root \"\$t\" '$SUDOERS'; rc=\$?; else rc=1; fi; rm -f \"\$t\"; exit \$rc" >/dev/null 2>&1 || fail "关闭 NOPASSWD 失败(sudoers 未改;可重试)"
after="$(rexec_user 'sudo -n true 2>/dev/null && echo STILL_ON || echo OFF')"
if [ "$after" = OFF ]; then printf '  → 已关闭(sudo -n 失效)✓\n'; else printf '  → ⚠️ 似乎仍生效(%s),请手动核对 %s\n' "$after" "$SUDOERS"; fi

printf '\n✅ 完成 —— %s 已启用真实 TLS 证书\n' "$NAME"
printf '  证书   : subject %s | 到期 %s\n' "$subj" "$exp"
printf '  vhost  : %s → %s / %s;nginx 已 reload\n' "$VHOST" "$DCRT" "$DKEY"
printf '  NOPASSWD: 已关闭(下次再配证书需先手动开启)\n'
printf '  回滚vhost: 服务器上 sudo cp -a %s.bak.%s %s && sudo nginx -t && sudo systemctl reload nginx\n' "$VHOST" "$ts" "$VHOST"
