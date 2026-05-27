#!/usr/bin/env bash
set -Eeuo pipefail

ADMIN_USER="${ADMIN_USER:-}"
ADMIN_GROUP="${ADMIN_GROUP:-}"
ADMIN_HOME="${ADMIN_HOME:-}"
ADMIN_SHELL="${ADMIN_SHELL:-/bin/bash}"
ADMIN_SUDO="${ADMIN_SUDO:-1}"
ADMIN_PASSWORDLESS_SUDO="${ADMIN_PASSWORDLESS_SUDO:-1}"
AUTHORIZED_KEYS_FILE="${AUTHORIZED_KEYS_FILE:-}"
TRUSTED_USER_CA_FILE="${TRUSTED_USER_CA_FILE:-}"
ADMIN_PRINCIPALS="${ADMIN_PRINCIPALS:-}"
SSH_PORT="${SSH_PORT:-}"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: run as root"; exit 1; }

. /etc/os-release
[[ "${ID}" == "debian" ]] || { echo "ERROR: Debian only"; exit 1; }

[[ -n "${ADMIN_USER}" ]] || { echo "ERROR: ADMIN_USER is required"; exit 1; }
[[ "${ADMIN_USER}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || { echo "ERROR: invalid ADMIN_USER"; exit 1; }

ADMIN_GROUP="${ADMIN_GROUP:-${ADMIN_USER}}"
ADMIN_HOME="${ADMIN_HOME:-/home/${ADMIN_USER}}"

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

write_principals() {
  local dest="$1"

  : >"${dest}"
  printf '%s\n' "${ADMIN_PRINCIPALS}" \
    | tr ',' '\n' \
    | while IFS= read -r principal; do
        principal="${principal#"${principal%%[![:space:]]*}"}"
        principal="${principal%"${principal##*[![:space:]]}"}"
        [[ -n "${principal}" ]] && printf '%s\n' "${principal}" >>"${dest}"
      done
}

echo "[admin] Create management user ${ADMIN_USER}"
getent group "${ADMIN_GROUP}" >/dev/null || groupadd "${ADMIN_GROUP}"

if id "${ADMIN_USER}" >/dev/null 2>&1; then
  usermod -d "${ADMIN_HOME}" -g "${ADMIN_GROUP}" -s "${ADMIN_SHELL}" "${ADMIN_USER}"
else
  useradd -m -d "${ADMIN_HOME}" -s "${ADMIN_SHELL}" -g "${ADMIN_GROUP}" "${ADMIN_USER}"
fi

install -d -o "${ADMIN_USER}" -g "${ADMIN_GROUP}" -m 0700 "${ADMIN_HOME}/.ssh"
touch "${ADMIN_HOME}/.ssh/authorized_keys"
chown "${ADMIN_USER}:${ADMIN_GROUP}" "${ADMIN_HOME}/.ssh/authorized_keys"
chmod 0600 "${ADMIN_HOME}/.ssh/authorized_keys"

if [[ -n "${AUTHORIZED_KEYS_FILE}" ]]; then
  [[ -f "${AUTHORIZED_KEYS_FILE}" ]] || { echo "ERROR: missing AUTHORIZED_KEYS_FILE=${AUTHORIZED_KEYS_FILE}"; exit 1; }
  reject_private_material "${AUTHORIZED_KEYS_FILE}"
  append_unique_keys "${AUTHORIZED_KEYS_FILE}" "${ADMIN_HOME}/.ssh/authorized_keys"
  chown "${ADMIN_USER}:${ADMIN_GROUP}" "${ADMIN_HOME}/.ssh/authorized_keys"
  chmod 0600 "${ADMIN_HOME}/.ssh/authorized_keys"
fi

if [[ "${ADMIN_SUDO}" == "1" ]]; then
  echo "[admin] Configure sudo for ${ADMIN_USER}"
  export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"
  command -v sudo >/dev/null 2>&1 || {
    apt-get update
    apt-get install -y sudo
  }

  usermod -aG sudo "${ADMIN_USER}"
  if [[ "${ADMIN_PASSWORDLESS_SUDO}" == "1" ]]; then
    echo "${ADMIN_USER} ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/90-admin-"${ADMIN_USER}"
  else
    echo "${ADMIN_USER} ALL=(ALL) ALL" >/etc/sudoers.d/90-admin-"${ADMIN_USER}"
  fi
  chmod 0440 /etc/sudoers.d/90-admin-"${ADMIN_USER}"
  visudo -cf /etc/sudoers.d/90-admin-"${ADMIN_USER}" >/dev/null
fi

echo "[admin] Configure SSH access"
install -d -m 0755 /etc/ssh/sshd_config.d

if [[ -n "${TRUSTED_USER_CA_FILE}" ]]; then
  [[ -f "${TRUSTED_USER_CA_FILE}" ]] || { echo "ERROR: missing TRUSTED_USER_CA_FILE=${TRUSTED_USER_CA_FILE}"; exit 1; }
  reject_private_material "${TRUSTED_USER_CA_FILE}"
  install -m 0644 -o root -g root "${TRUSTED_USER_CA_FILE}" /etc/ssh/trusted_user_ca_keys.pem

  if [[ -n "${ADMIN_PRINCIPALS}" ]]; then
    write_principals "${ADMIN_HOME}/.ssh/authorized_principals"
    chown "${ADMIN_USER}:${ADMIN_GROUP}" "${ADMIN_HOME}/.ssh/authorized_principals"
    chmod 0600 "${ADMIN_HOME}/.ssh/authorized_principals"
  fi
fi

{
  echo "PubkeyAuthentication yes"
  echo "AuthorizedKeysFile .ssh/authorized_keys"
  if [[ -n "${TRUSTED_USER_CA_FILE}" ]]; then
    echo "TrustedUserCAKeys /etc/ssh/trusted_user_ca_keys.pem"
    if [[ -n "${ADMIN_PRINCIPALS}" ]]; then
      echo "AuthorizedPrincipalsFile .ssh/authorized_principals"
    fi
  fi
  if [[ -n "${SSH_PORT}" ]]; then
    [[ "${SSH_PORT}" =~ ^[0-9]+$ && "${SSH_PORT}" -ge 1 && "${SSH_PORT}" -le 65535 ]] || {
      echo "ERROR: invalid SSH_PORT=${SSH_PORT}" >&2
      exit 1
    }
    echo "Port ${SSH_PORT}"
  fi
} >/etc/ssh/sshd_config.d/20-admin-access.conf

chmod 0644 /etc/ssh/sshd_config.d/20-admin-access.conf

sshd -t
systemctl reload ssh

echo "DONE admin user: ${ADMIN_USER}"
echo "Notes:"
echo "  - SSH private key material was not accepted or installed."
echo "  - If SSH_PORT was set, verify the new port before closing the old one."
