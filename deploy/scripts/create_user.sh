#!/usr/bin/env bash
set -Eeuo pipefail

OPT_USER="${OPT_USER:-opt}"
OPT_GROUP="${OPT_GROUP:-opt}"
BASE_DIR="${BASE_DIR:-/srv/docker-env}"
DENY_OPT_SSH="${DENY_OPT_SSH:-1}"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: run as root"; exit 1; }

. /etc/os-release
[[ "${ID}" == "debian" ]] || { echo "ERROR: Debian only"; exit 1; }

echo "[user] Create ${OPT_USER} as non-login restricted user"
getent group "${OPT_GROUP}" >/dev/null || groupadd "${OPT_GROUP}"

if id "${OPT_USER}" >/dev/null 2>&1; then
  usermod -d "${BASE_DIR}" -g "${OPT_GROUP}" -s /usr/sbin/nologin "${OPT_USER}"
else
  useradd -M -d "${BASE_DIR}" -s /usr/sbin/nologin -g "${OPT_GROUP}" "${OPT_USER}"
fi

passwd -l "${OPT_USER}" >/dev/null 2>&1 || true

for g in sudo docker adm systemd-journal; do
  if getent group "$g" >/dev/null; then
    gpasswd -d "${OPT_USER}" "$g" >/dev/null 2>&1 || true
  fi
done

install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0750 "${BASE_DIR}"
install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0750 "${BASE_DIR}/apps" "${BASE_DIR}/data" "${BASE_DIR}/logs"
install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0700 "${BASE_DIR}/.ssh"
: >"${BASE_DIR}/.ssh/authorized_keys"

chown "${OPT_USER}:${OPT_GROUP}" "${BASE_DIR}" \
  "${BASE_DIR}/apps" "${BASE_DIR}/data" "${BASE_DIR}/logs" "${BASE_DIR}/.ssh" \
  "${BASE_DIR}/.ssh/authorized_keys"

chmod 0750 "${BASE_DIR}" "${BASE_DIR}/apps" "${BASE_DIR}/data" "${BASE_DIR}/logs"
chmod 0700 "${BASE_DIR}/.ssh"
chmod 0600 "${BASE_DIR}/.ssh/authorized_keys"

echo "[user] Configure subuid/subgid"
touch /etc/subuid /etc/subgid

if ! grep -q "^${OPT_USER}:" /etc/subuid; then
  s="$(awk -F: 'BEGIN{m=100000}{e=$2+$3;if(e>m)m=e}END{print m}' /etc/subuid 2>/dev/null || echo 100000)"
  usermod --add-subuids "${s}-$((s+65535))" "${OPT_USER}"
fi

if ! grep -q "^${OPT_USER}:" /etc/subgid; then
  s="$(awk -F: 'BEGIN{m=100000}{e=$2+$3;if(e>m)m=e}END{print m}' /etc/subgid 2>/dev/null || echo 100000)"
  usermod --add-subgids "${s}-$((s+65535))" "${OPT_USER}"
fi

if [[ "${DENY_OPT_SSH}" == "1" ]]; then
  echo "[user] Deny direct SSH/login for ${OPT_USER}"
  install -d -m 0755 /etc/ssh/sshd_config.d

  cat >/etc/ssh/sshd_config.d/30-deny-opt.conf <<EOF
DenyUsers ${OPT_USER}
EOF

  sshd -t
  systemctl reload ssh
fi

echo "DONE user: ${OPT_USER}"
