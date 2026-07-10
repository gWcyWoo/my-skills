#!/bin/sh
# dpt / edge / nginx / rebuild_modsec —— ModSecurity-nginx 连接器重建器(服务器端)。
# 由 install_waf 部署到服务器 /usr/local/sbin/dpt-modsec-rebuild,并挂在 apt 的
# DPkg::Post-Invoke 钩子上(nginx 升级后自动校正),也可手动跑。
#
# 探测优先(避免无谓编译):当前 nginx 能加载现有 .so 就跳过;只在缺失/ABI 不符时才编。
# nginx.org 二进制是 --with-compat 编的,连接器也 --with-compat,补丁/小版本更新通常无需重编。
set -u

SO=/etc/nginx/modules/ngx_http_modsecurity_module.so
LOADCONF=/etc/nginx/modules-enabled/50-modsecurity.conf
SRC=/usr/local/src/dpt-modsec
LOG=/var/log/dpt-modsec-rebuild.log
log() { echo "[$(date '+%F %T')] $*" >> "$LOG" 2>/dev/null; }

# fail-safe:重建失败且现有 .so 与当前 nginx 不兼容时,禁用 load_module,
# 让 nginx 能"无 WAF"启动(边缘可起 > 边缘宕)。修好后重跑本脚本恢复。
failsafe_disable() {
  if [ -f "$LOADCONF" ]; then
    mv -f "$LOADCONF" "$LOADCONF.disabled" 2>/dev/null || true
    log "FAIL-SAFE:已禁用 modsec load_module(WAF 关、保边缘可起);修好后重跑本脚本"
    echo "FAIL-SAFE: 已禁用 modsec 加载,nginx 可无 WAF 启动(WAF 暂关,请尽快修复)"
    systemctl reload nginx >/dev/null 2>&1 || nginx -s reload >/dev/null 2>&1 || true
  fi
}

command -v nginx >/dev/null 2>&1 || exit 0
NGINX_VER=$(nginx -v 2>&1 | sed -n 's#.*nginx/##p')

# ---- 探测:现有 .so 能否被当前 nginx 加载 ----
probe_ok() {
  [ -f "$SO" ] || return 1
  tmp=$(mktemp -d) || return 1
  printf 'load_module %s;\nevents{}\nhttp{}\n' "$SO" > "$tmp/probe.conf"
  if nginx -t -c "$tmp/probe.conf" >/dev/null 2>&1; then rm -rf "$tmp"; return 0; fi
  rm -rf "$tmp"; return 1
}

if probe_ok; then
  log "现有连接器可被 nginx $NGINX_VER 加载,跳过编译"
  echo "modsec 连接器已匹配 nginx $NGINX_VER,跳过编译"
  exit 0
fi
log "需要重建:nginx $NGINX_VER 无法加载现有连接器(缺失或 ABI 不符)"
echo "重建 modsec 连接器 for nginx $NGINX_VER ..."

# ---- 取源 ----
mkdir -p "$SRC"
if [ ! -d "$SRC/ModSecurity-nginx/.git" ]; then
  git clone --depth=1 https://github.com/owasp-modsecurity/ModSecurity-nginx.git "$SRC/ModSecurity-nginx" >>"$LOG" 2>&1 \
    || { log "克隆 ModSecurity-nginx 失败"; failsafe_disable; echo "FAIL: 克隆连接器源失败"; exit 1; }
else
  git -C "$SRC/ModSecurity-nginx" pull --ff-only >>"$LOG" 2>&1 || true
fi

NSRC="$SRC/nginx-$NGINX_VER"
if [ ! -d "$NSRC" ]; then
  ( cd "$SRC" && wget -q "https://nginx.org/download/nginx-$NGINX_VER.tar.gz" && tar xzf "nginx-$NGINX_VER.tar.gz" ) >>"$LOG" 2>&1 \
    || { log "下载/解压 nginx-$NGINX_VER 源失败"; failsafe_disable; echo "FAIL: 取 nginx 源失败"; exit 1; }
fi

# ---- 编译动态模块(--with-compat)----
if ( cd "$NSRC" && ./configure --with-compat --add-dynamic-module="$SRC/ModSecurity-nginx" >>"$LOG" 2>&1 && make modules >>"$LOG" 2>&1 ); then
  install -D -m 644 "$NSRC/objs/ngx_http_modsecurity_module.so" "$SO"
  printf 'load_module %s;\n' "$SO" > "$LOADCONF"
  if nginx -t >>"$LOG" 2>&1; then
    systemctl reload nginx >>"$LOG" 2>&1 || true
    log "重建成功 → nginx $NGINX_VER,已 reload"
    echo "OK: modsec 连接器重建成功 for nginx $NGINX_VER"
    exit 0
  else
    log "重建后 nginx -t 失败,未 reload(保留现网)"
    failsafe_disable
    echo "FAIL: 重建后 nginx -t 不过(见 $LOG)"
    exit 1
  fi
else
  log "编译失败(见 $LOG)"
  failsafe_disable
  echo "FAIL: 编译失败(见 $LOG)"
  exit 1
fi
