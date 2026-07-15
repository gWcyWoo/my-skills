#!/usr/bin/env bash
set -Eeuo pipefail

FAIL2BAN_SSHD_PORT="${FAIL2BAN_SSHD_PORT:-ssh}"
FAIL2BAN_BACKEND="${FAIL2BAN_BACKEND:-systemd}"
FAIL2BAN_MAXRETRY="${FAIL2BAN_MAXRETRY:-5}"
FAIL2BAN_FINDTIME="${FAIL2BAN_FINDTIME:-10m}"
FAIL2BAN_BANTIME="${FAIL2BAN_BANTIME:-1h}"
FAIL2BAN_IGNOREIP="${FAIL2BAN_IGNOREIP:-}"
DISABLE_LLMNR="${DISABLE_LLMNR:-1}"
REQUIRE_SSH_ALLOW_USERS="${REQUIRE_SSH_ALLOW_USERS:-1}"
SSH_ALLOW_USERS="${SSH_ALLOW_USERS:-}"
SSH_POLICY_FILE="${SSH_POLICY_FILE:-/etc/ssh/sshd_config.d/40-login-policy.conf}"
SSHD_MAX_AUTH_TRIES="${SSHD_MAX_AUTH_TRIES:-3}"
SSHD_LOGIN_GRACE_TIME="${SSHD_LOGIN_GRACE_TIME:-30}"
SSHD_ALLOW_TCP_FORWARDING="${SSHD_ALLOW_TCP_FORWARDING:-no}"
SSHD_ALLOW_AGENT_FORWARDING="${SSHD_ALLOW_AGENT_FORWARDING:-no}"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: run as root"; exit 1; }

. /etc/os-release
[[ "${ID}" == "debian" ]] || { echo "ERROR: Debian only"; exit 1; }

export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

normalize_allow_users() {
  local raw="${SSH_ALLOW_USERS//,/ }"
  local normalized=""
  local user=""

  for user in ${raw}; do
    [[ "${user}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || {
      echo "ERROR: invalid SSH_ALLOW_USERS entry: ${user}" >&2
      exit 1
    }
    [[ "${user}" != "root" ]] || {
      echo "ERROR: root must not be listed in SSH_ALLOW_USERS" >&2
      exit 1
    }
    id "${user}" >/dev/null 2>&1 || {
      echo "ERROR: SSH_ALLOW_USERS contains missing local user: ${user}" >&2
      exit 1
    }
    normalized="${normalized}${normalized:+ }${user}"
  done

  [[ -n "${normalized}" ]] || {
    echo "ERROR: SSH_ALLOW_USERS is required; pass the management user list, e.g. SSH_ALLOW_USERS=admin" >&2
    exit 1
  }

  printf '%s\n' "${normalized}"
}

has_llmnr_listener() {
  ss -H -tuln | awk '$5 ~ /:5355$/ {found=1} END {exit found ? 0 : 1}'
}

echo "[security] Install required fail2ban package"
apt-get update
apt-get install -y fail2ban

if [[ "${DISABLE_LLMNR}" == "1" ]]; then
  echo "[security] Disable LLMNR"
  install -d -m 0755 /etc/systemd/resolved.conf.d
  cat >/etc/systemd/resolved.conf.d/20-disable-llmnr.conf <<'EOF'
[Resolve]
LLMNR=no
EOF

  if systemctl cat systemd-resolved.service >/dev/null 2>&1; then
    systemctl restart systemd-resolved
  fi

  if has_llmnr_listener; then
    echo "ERROR: LLMNR port 5355 is still listening after disabling LLMNR" >&2
    exit 1
  fi
fi

if [[ "${REQUIRE_SSH_ALLOW_USERS}" == "1" ]]; then
  echo "[security] Configure SSH login allow-list and hardening"
  SSH_ALLOW_USERS_NORMALIZED="$(normalize_allow_users)"
  install -d -m 0755 "$(dirname "${SSH_POLICY_FILE}")"

  cat >"${SSH_POLICY_FILE}" <<EOF
# Managed by deploy_security.sh.
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PubkeyAuthentication yes
MaxAuthTries ${SSHD_MAX_AUTH_TRIES}
LoginGraceTime ${SSHD_LOGIN_GRACE_TIME}
X11Forwarding no
PermitTunnel no
AllowAgentForwarding ${SSHD_ALLOW_AGENT_FORWARDING}
AllowTcpForwarding ${SSHD_ALLOW_TCP_FORWARDING}
AllowUsers ${SSH_ALLOW_USERS_NORMALIZED}
EOF

  chmod 0644 "${SSH_POLICY_FILE}"
  sshd -t
  systemctl reload ssh
fi

echo "[security] Configure fail2ban sshd jail"
install -d -m 0755 /etc/fail2ban/jail.d

{
  echo "[sshd]"
  echo "enabled = true"
  echo "backend = ${FAIL2BAN_BACKEND}"
  echo "port = ${FAIL2BAN_SSHD_PORT}"
  echo "maxretry = ${FAIL2BAN_MAXRETRY}"
  echo "findtime = ${FAIL2BAN_FINDTIME}"
  echo "bantime = ${FAIL2BAN_BANTIME}"
  if [[ -n "${FAIL2BAN_IGNOREIP}" ]]; then
    echo "ignoreip = ${FAIL2BAN_IGNOREIP}"
  fi
} >/etc/fail2ban/jail.d/sshd.local

chmod 0644 /etc/fail2ban/jail.d/sshd.local

echo "[security] Verify fail2ban configuration"
fail2ban-client -t

echo "[security] Enable and start fail2ban"
systemctl enable --now fail2ban
systemctl restart fail2ban

echo "[security] Verify fail2ban sshd jail"
systemctl is-active --quiet fail2ban
for _ in $(seq 1 20); do
  if fail2ban-client ping >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
fail2ban-client ping >/dev/null
fail2ban-client status
fail2ban-client status sshd

echo "DONE security baseline: fail2ban sshd jail active"
