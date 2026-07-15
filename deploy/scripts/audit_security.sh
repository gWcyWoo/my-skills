#!/usr/bin/env bash
set -Eeuo pipefail

OPT_USER="${OPT_USER:-opt}"
BASE_DIR="${BASE_DIR:-/srv/docker-env}"
EXPECT_SSH_ALLOW_USERS="${EXPECT_SSH_ALLOW_USERS:-}"
AUDIT_ADMIN_USERS="${AUDIT_ADMIN_USERS:-${SUDO_USER:-}}"
FIREWALL_PROVIDER="${FIREWALL_PROVIDER:-host}"
BACKUP_AUDIT_STATUS="${BACKUP_AUDIT_STATUS:-not_verified}"
COMPOSE_AUDIT_STATUS="${COMPOSE_AUDIT_STATUS:-post_deploy}"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: run as root"; exit 1; }

P0_FAILS=0
P1_WARNS=0
P2_NOTES=0

emit() {
  printf '%s %-5s %s\n' "$1" "$2" "$3"
}

pass() {
  emit "PASS" "$1" "$2"
}

fail_p0() {
  P0_FAILS=$((P0_FAILS + 1))
  emit "FAIL" "P0" "$1"
}

warn_p1() {
  P1_WARNS=$((P1_WARNS + 1))
  emit "WARN" "P1" "$1"
}

note_p2() {
  P2_NOTES=$((P2_NOTES + 1))
  emit "NOTE" "P2" "$1"
}

unit_state() {
  local unit="$1"
  printf '%s:%s' \
    "$(systemctl is-enabled "${unit}" 2>/dev/null || true)" \
    "$(systemctl is-active "${unit}" 2>/dev/null || true)"
}

has_listener_port() {
  local port="$1"
  ss -H -tuln | awk -v port=":${port}" '$5 ~ port "$" {found=1} END {exit found ? 0 : 1}'
}

sshd_t="$(sshd -T 2>/dev/null || true)"

sshd_value() {
  local key="$1"
  awk -v key="${key}" '$1 == key {$1=""; sub(/^ /, ""); print; exit}' <<<"${sshd_t}"
}

sshd_values() {
  local key="$1"
  awk -v key="${key}" '
    $1 == key {
      $1=""
      sub(/^ /, "")
      out = out ? out " " $0 : $0
    }
    END { print out }
  ' <<<"${sshd_t}"
}

require_sshd_value() {
  local key="$1"
  local expected="$2"
  local label="$3"
  local actual
  actual="$(sshd_value "${key}")"

  if [[ "${actual}" == "${expected}" ]]; then
    pass "P0" "${label}: ${actual}"
  else
    fail_p0 "${label}: expected ${expected}, got ${actual:-unset}"
  fi
}

warn_sshd_value() {
  local key="$1"
  local expected="$2"
  local label="$3"
  local actual
  actual="$(sshd_value "${key}")"

  if [[ "${actual}" == "${expected}" ]]; then
    pass "P1" "${label}: ${actual}"
  else
    warn_p1 "${label}: expected ${expected}, got ${actual:-unset}"
  fi
}

warn_sshd_number_le() {
  local key="$1"
  local max="$2"
  local label="$3"
  local actual
  actual="$(sshd_value "${key}")"

  if [[ "${actual}" =~ ^[0-9]+$ && "${actual}" -le "${max}" ]]; then
    pass "P1" "${label}: ${actual}"
  else
    warn_p1 "${label}: expected <= ${max}, got ${actual:-unset}"
  fi
}

sysctl_expect() {
  local key="$1"
  local expected="$2"
  local actual
  actual="$(sysctl -n "${key}" 2>/dev/null || true)"

  if [[ "${actual}" == "${expected}" ]]; then
    pass "P1" "${key}=${actual}"
  else
    warn_p1 "${key}: expected ${expected}, got ${actual:-unset}"
  fi
}

sysctl_expect_one_of() {
  local key="$1"
  shift
  local actual
  local expected
  actual="$(sysctl -n "${key}" 2>/dev/null || true)"

  for expected in "$@"; do
    if [[ "${actual}" == "${expected}" ]]; then
      pass "P1" "${key}=${actual}"
      return 0
    fi
  done

  warn_p1 "${key}: expected one of $*, got ${actual:-unset}"
}

echo "Security audit for $(hostname)"
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  if [[ "${ID:-}" == "debian" ]]; then
    pass "P0" "OS is Debian ${VERSION_CODENAME:-unknown}"
  else
    fail_p0 "OS must be Debian, got ${ID:-unknown}"
  fi
else
  fail_p0 "missing /etc/os-release"
fi

echo
echo "[P0] Required baseline"
if sshd -t >/dev/null 2>&1; then
  pass "P0" "sshd syntax is valid"
else
  fail_p0 "sshd syntax check failed"
fi

require_sshd_value "permitrootlogin" "no" "SSH root login disabled"
require_sshd_value "passwordauthentication" "no" "SSH password auth disabled"
require_sshd_value "kbdinteractiveauthentication" "no" "SSH keyboard-interactive auth disabled"
require_sshd_value "permitemptypasswords" "no" "SSH empty passwords disabled"
require_sshd_value "pubkeyauthentication" "yes" "SSH public key auth enabled"

allow_users="$(sshd_values allowusers)"
if [[ -n "${allow_users}" ]]; then
  pass "P0" "SSH AllowUsers configured: ${allow_users}"
else
  fail_p0 "SSH AllowUsers is not configured"
fi

if [[ -n "${EXPECT_SSH_ALLOW_USERS}" ]]; then
  for expected_user in ${EXPECT_SSH_ALLOW_USERS//,/ }; do
    if [[ " ${allow_users} " == *" ${expected_user} "* ]]; then
      pass "P0" "SSH AllowUsers contains ${expected_user}"
    else
      fail_p0 "SSH AllowUsers missing expected user ${expected_user}"
    fi
  done
else
  warn_p1 "EXPECT_SSH_ALLOW_USERS not provided; observed AllowUsers=${allow_users:-unset}"
fi

deny_users="$(sshd_values denyusers)"
if [[ " ${deny_users} " == *" ${OPT_USER} "* ]]; then
  pass "P0" "SSH DenyUsers contains ${OPT_USER}"
else
  fail_p0 "SSH DenyUsers does not contain ${OPT_USER}"
fi

if has_listener_port 5355; then
  fail_p0 "LLMNR port 5355 is listening"
else
  pass "P0" "LLMNR port 5355 is not listening"
fi

if systemctl is-active --quiet fail2ban; then
  pass "P0" "fail2ban service is active"
else
  fail_p0 "fail2ban service is not active"
fi

if command -v fail2ban-client >/dev/null 2>&1 && fail2ban-client status sshd >/dev/null 2>&1; then
  pass "P0" "fail2ban sshd jail is active"
else
  fail_p0 "fail2ban sshd jail is not active"
fi

if id "${OPT_USER}" >/dev/null 2>&1; then
  opt_shell="$(getent passwd "${OPT_USER}" | awk -F: '{print $7}')"
  if [[ "${opt_shell}" == "/usr/sbin/nologin" ]]; then
    pass "P0" "${OPT_USER} shell is /usr/sbin/nologin"
  else
    fail_p0 "${OPT_USER} shell expected /usr/sbin/nologin, got ${opt_shell}"
  fi

  opt_passwd_state="$(passwd -S "${OPT_USER}" 2>/dev/null | awk '{print $2}' || true)"
  if [[ "${opt_passwd_state}" == "L" ]]; then
    pass "P0" "${OPT_USER} password is locked"
  else
    fail_p0 "${OPT_USER} password is not locked"
  fi

  opt_groups="$(id -nG "${OPT_USER}")"
  for restricted_group in sudo docker adm systemd-journal lxd; do
    if [[ " ${opt_groups} " == *" ${restricted_group} "* ]]; then
      fail_p0 "${OPT_USER} is in restricted group ${restricted_group}"
    fi
  done
  pass "P0" "${OPT_USER} group membership: ${opt_groups}"

  opt_uid="$(id -u "${OPT_USER}")"
  if [[ -S "/run/user/${opt_uid}/docker.sock" ]]; then
    pass "P0" "rootless Docker socket exists for ${OPT_USER}"
  else
    fail_p0 "rootless Docker socket missing for ${OPT_USER}"
  fi
else
  fail_p0 "${OPT_USER} user is missing"
fi

if [[ -S /var/run/docker.sock ]]; then
  fail_p0 "/var/run/docker.sock exists"
else
  pass "P0" "/var/run/docker.sock is absent"
fi

if [[ "$(unit_state docker.service)" == "masked:inactive" ]]; then
  pass "P0" "rootful docker.service is masked:inactive"
else
  fail_p0 "rootful docker.service state is $(unit_state docker.service)"
fi

if [[ "$(unit_state docker.socket)" == "masked:inactive" ]]; then
  pass "P0" "rootful docker.socket is masked:inactive"
else
  fail_p0 "rootful docker.socket state is $(unit_state docker.socket)"
fi

if [[ -x /usr/local/sbin/opt-compose ]] && /usr/local/sbin/opt-compose version >/dev/null 2>&1; then
  pass "P0" "opt-compose wrapper works"
else
  fail_p0 "opt-compose wrapper is missing or failing"
fi

echo
echo "[P1] Recommended hardening"
if [[ "${FIREWALL_PROVIDER}" == "cloud" ]]; then
  pass "P1" "host firewall delegated to cloud provider"
elif systemctl is-active --quiet nftables; then
  pass "P1" "nftables is active"
elif command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | awk 'tolower($0) ~ /^status: active$/ {found=1} END {exit found ? 0 : 1}'; then
  pass "P1" "ufw is active"
else
  warn_p1 "no active host firewall detected"
fi

if systemctl is-active --quiet unattended-upgrades; then
  pass "P1" "unattended-upgrades is active"
else
  warn_p1 "unattended-upgrades is not active"
fi

warn_sshd_number_le "maxauthtries" "3" "SSH MaxAuthTries"
warn_sshd_number_le "logingracetime" "30" "SSH LoginGraceTime"
warn_sshd_value "x11forwarding" "no" "SSH X11Forwarding"
warn_sshd_value "permittunnel" "no" "SSH PermitTunnel"
warn_sshd_value "allowtcpforwarding" "no" "SSH AllowTcpForwarding"
warn_sshd_value "allowagentforwarding" "no" "SSH AllowAgentForwarding"

if [[ -d /var/log/journal ]]; then
  pass "P1" "persistent journald directory exists"
else
  warn_p1 "persistent journald directory /var/log/journal is missing"
fi

sysctl_expect "net.ipv4.ip_forward" "0"
sysctl_expect "net.ipv4.conf.all.accept_redirects" "0"
sysctl_expect "net.ipv4.conf.default.accept_redirects" "0"
sysctl_expect "net.ipv4.conf.all.send_redirects" "0"
sysctl_expect "net.ipv4.conf.all.accept_source_route" "0"
sysctl_expect_one_of "net.ipv4.conf.all.rp_filter" "1" "2"
sysctl_expect "net.ipv4.tcp_syncookies" "1"

echo
echo "[P2] Operational review"
note_p2 "listening ports:"
ss -tulpn | awk 'NR == 1 || /LISTEN/ {print "  " $0}'

if ss -H -tln | awk '$5 ~ /:25$/ && $5 !~ /^(127\.0\.0\.1|\[::1\]):25$/ {found=1} END {exit found ? 0 : 1}'; then
  warn_p1 "SMTP port 25 is listening on a non-loopback address"
else
  note_p2 "SMTP, if present, is not listening on a non-loopback TCP address"
fi

for group_name in docker lxd; do
  if getent group "${group_name}" >/dev/null; then
    members="$(getent group "${group_name}" | awk -F: '{print $4}')"
    if [[ -n "${members}" ]]; then
      note_p2 "members of high-privilege group ${group_name}: ${members}"
    else
      note_p2 "high-privilege group ${group_name} has no listed members"
    fi
  fi
done

if [[ -n "${AUDIT_ADMIN_USERS}" ]]; then
  for admin_user in ${AUDIT_ADMIN_USERS//,/ }; do
    if id "${admin_user}" >/dev/null 2>&1; then
      note_p2 "admin user ${admin_user} groups: $(id -nG "${admin_user}")"
    fi
  done
fi

case "${BACKUP_AUDIT_STATUS}" in
  deferred)
    note_p2 "backup coverage audit is deferred by operator decision"
    ;;
  verified)
    pass "P2" "backup coverage marked verified by operator input"
    ;;
  *)
    note_p2 "backup coverage is not verified by this script"
    ;;
esac

case "${COMPOSE_AUDIT_STATUS}" in
  post_deploy)
    note_p2 "application container compose policy audit is scheduled after app deployment"
    ;;
  verified)
    pass "P2" "application container compose policy marked verified by operator input"
    ;;
  *)
    note_p2 "application container compose policies are not verified by this script"
    ;;
esac

echo
echo "Summary: P0 failures=${P0_FAILS}, P1 warnings=${P1_WARNS}, P2 notes=${P2_NOTES}"
if [[ "${P0_FAILS}" -gt 0 ]]; then
  exit 1
fi
