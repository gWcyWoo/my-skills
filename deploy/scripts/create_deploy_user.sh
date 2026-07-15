#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
DEPLOY_GROUP="${DEPLOY_GROUP:-${DEPLOY_USER}}"
DEPLOY_HOME="${DEPLOY_HOME:-/home/${DEPLOY_USER}}"
DEPLOY_SHELL="${DEPLOY_SHELL:-/bin/bash}"
AUTHORIZED_KEYS_FILE="${AUTHORIZED_KEYS_FILE:-}"
SUDOERS_FILE="${SUDOERS_FILE:-/etc/sudoers.d/90-deploy-${DEPLOY_USER}}"
SSH_POLICY_FILE="${SSH_POLICY_FILE:-/etc/ssh/sshd_config.d/40-login-policy.conf}"
RELOAD_SSH="${RELOAD_SSH:-1}"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: run as root"; exit 1; }

. /etc/os-release
[[ "${ID}" == "debian" ]] || { echo "ERROR: Debian only"; exit 1; }

[[ "${DEPLOY_USER}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || {
  echo "ERROR: invalid DEPLOY_USER=${DEPLOY_USER}" >&2
  exit 1
}
[[ "${DEPLOY_USER}" != "root" ]] || { echo "ERROR: DEPLOY_USER must not be root"; exit 1; }

reject_private_material() {
  local path="$1"
  if grep -Eq "BEGIN (OPENSSH |RSA |DSA |EC |PRIVATE )?PRIVATE KEY" "${path}"; then
    echo "ERROR: ${path} appears to contain private key material" >&2
    exit 1
  fi
}

append_unique_keys() {
  local src="$1"
  local dest="$2"

  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -n "${line}" ]] || continue
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    grep -qxF "${line}" "${dest}" 2>/dev/null || printf '%s\n' "${line}" >>"${dest}"
  done <"${src}"
}

managed_allow_users() {
  local existing=""
  local normalized=""
  local user=""

  if [[ -f "${SSH_POLICY_FILE}" ]]; then
    existing="$(awk 'tolower($1) == "allowusers" {$1=""; sub(/^ /, ""); print; exit}' "${SSH_POLICY_FILE}")"
  fi

  for user in ${existing}; do
    [[ "${user}" != "${DEPLOY_USER}" ]] || continue
    normalized="${normalized}${normalized:+ }${user}"
  done

  normalized="${normalized}${normalized:+ }${DEPLOY_USER}"
  printf '%s\n' "${normalized}"
}

echo "[deploy-user] Create login-capable deploy user ${DEPLOY_USER}"
getent group "${DEPLOY_GROUP}" >/dev/null || groupadd "${DEPLOY_GROUP}"

if id "${DEPLOY_USER}" >/dev/null 2>&1; then
  usermod -d "${DEPLOY_HOME}" -g "${DEPLOY_GROUP}" -s "${DEPLOY_SHELL}" "${DEPLOY_USER}"
else
  useradd -m -d "${DEPLOY_HOME}" -s "${DEPLOY_SHELL}" -g "${DEPLOY_GROUP}" "${DEPLOY_USER}"
fi

install -d -o "${DEPLOY_USER}" -g "${DEPLOY_GROUP}" -m 0700 "${DEPLOY_HOME}/.ssh"
touch "${DEPLOY_HOME}/.ssh/authorized_keys"
chown "${DEPLOY_USER}:${DEPLOY_GROUP}" "${DEPLOY_HOME}/.ssh/authorized_keys"
chmod 0600 "${DEPLOY_HOME}/.ssh/authorized_keys"

if [[ -n "${AUTHORIZED_KEYS_FILE}" ]]; then
  [[ -f "${AUTHORIZED_KEYS_FILE}" ]] || {
    echo "ERROR: missing AUTHORIZED_KEYS_FILE=${AUTHORIZED_KEYS_FILE}" >&2
    exit 1
  }
  reject_private_material "${AUTHORIZED_KEYS_FILE}"
  append_unique_keys "${AUTHORIZED_KEYS_FILE}" "${DEPLOY_HOME}/.ssh/authorized_keys"
  chown "${DEPLOY_USER}:${DEPLOY_GROUP}" "${DEPLOY_HOME}/.ssh/authorized_keys"
  chmod 0600 "${DEPLOY_HOME}/.ssh/authorized_keys"
fi

echo "[deploy-user] Configure limited passwordless sudo for opt wrapper"
command -v sudo >/dev/null 2>&1 || {
  export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"
  apt-get update
  apt-get install -y sudo
}

{
  echo "${DEPLOY_USER} ALL=(root) NOPASSWD: /usr/local/sbin/opt *"
  echo "${DEPLOY_USER} ALL=(root) NOPASSWD: /usr/local/bin/opt *"
} >"${SUDOERS_FILE}"
chmod 0440 "${SUDOERS_FILE}"
visudo -cf "${SUDOERS_FILE}" >/dev/null

echo "[deploy-user] Add ${DEPLOY_USER} to SSH AllowUsers"
install -d -m 0755 "$(dirname "${SSH_POLICY_FILE}")"

if [[ -f "${SSH_POLICY_FILE}" ]] && grep -Eqi '^[[:space:]]*AllowUsers[[:space:]]+' "${SSH_POLICY_FILE}"; then
  allow_users="$(managed_allow_users)"
  tmp_file="$(mktemp)"
  awk -v allow_users="${allow_users}" '
    BEGIN { done=0 }
    tolower($1) == "allowusers" {
      if (!done) {
        print "AllowUsers " allow_users
        done=1
      }
      next
    }
    { print }
    END {
      if (!done) {
        print "AllowUsers " allow_users
      }
    }
  ' "${SSH_POLICY_FILE}" >"${tmp_file}"
  cat "${tmp_file}" >"${SSH_POLICY_FILE}"
  rm -f "${tmp_file}"
else
  existing="$(sshd -T 2>/dev/null | awk '$1 == "allowusers" {$1=""; sub(/^ /, ""); print; exit}' || true)"
  allow_users=""
  for user in ${existing}; do
    [[ "${user}" != "${DEPLOY_USER}" ]] || continue
    allow_users="${allow_users}${allow_users:+ }${user}"
  done
  allow_users="${allow_users}${allow_users:+ }${DEPLOY_USER}"
  {
    echo "# Managed by create_deploy_user.sh."
    echo "AllowUsers ${allow_users}"
  } >"${SSH_POLICY_FILE}"
fi

chmod 0644 "${SSH_POLICY_FILE}"
sshd -t
if [[ "${RELOAD_SSH}" == "1" ]]; then
  systemctl reload ssh
fi

echo "[deploy-user] Verify"
id "${DEPLOY_USER}"
sudo -l -U "${DEPLOY_USER}" | grep -E '/usr/local/(sbin|bin)/opt' >/dev/null
sshd -T | awk '$1 == "allowusers" {print}'

echo "DONE deploy user: ${DEPLOY_USER}"
