#!/usr/bin/env bash
set -Eeuo pipefail

OPT_USER="${OPT_USER:-opt}"
OPT_GROUP="${OPT_GROUP:-opt}"
BASE_DIR="${BASE_DIR:-/srv/docker-env}"
DISABLE_ROOTFUL_DOCKER="${DISABLE_ROOTFUL_DOCKER:-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: run as root"; exit 1; }

. /etc/os-release
[[ "${ID}" == "debian" ]] || { echo "ERROR: Debian only"; exit 1; }

export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

echo "[1/8] Ensure deploy user"
"${SCRIPT_DIR}/create_user.sh"

echo "[2/8] Install Docker rootless dependencies"
apt-get update
apt-get install -y ca-certificates curl gnupg uidmap dbus-user-session \
  fuse-overlayfs slirp4netns systemd-container util-linux

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: ${VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
  docker-compose-plugin docker-ce-rootless-extras

echo "[3/8] Disable rootful Docker socket"
if [[ "${DISABLE_ROOTFUL_DOCKER}" == "1" ]]; then
  systemctl disable --now docker.service docker.socket 2>/dev/null || true
  systemctl mask docker.service docker.socket 2>/dev/null || true
  rm -f /var/run/docker.sock
fi

echo "[4/8] Configure rootless Docker daemon under ${BASE_DIR}"
install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0700 "${BASE_DIR}/.config"
install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0700 "${BASE_DIR}/.config/docker"
install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0700 "${BASE_DIR}/.config/systemd"
install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0700 "${BASE_DIR}/.config/systemd/user"
install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0700 "${BASE_DIR}/.local"
install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0700 "${BASE_DIR}/.local/share"

cat >"${BASE_DIR}/.config/docker/daemon.json" <<EOF
{
  "data-root": "${BASE_DIR}/.local/share/docker",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF

chown "${OPT_USER}:${OPT_GROUP}" "${BASE_DIR}/.config/docker/daemon.json"
chmod 0600 "${BASE_DIR}/.config/docker/daemon.json"

echo "[5/8] Enable ${OPT_USER} user service manager"
loginctl enable-linger "${OPT_USER}"

OPT_UID="$(id -u "${OPT_USER}")"
OPT_GID="$(id -g "${OPT_USER}")"
RUNTIME_DIR="/run/user/${OPT_UID}"

systemctl start "user@${OPT_UID}.service" 2>/dev/null || loginctl start-user "${OPT_USER}" || true

for _ in $(seq 1 30); do
  [[ -d "${RUNTIME_DIR}" && -S "${RUNTIME_DIR}/bus" ]] && break
  sleep 1
done

[[ -d "${RUNTIME_DIR}" ]] || { echo "ERROR: ${RUNTIME_DIR} was not created"; exit 1; }
[[ -S "${RUNTIME_DIR}/bus" ]] || { echo "ERROR: ${RUNTIME_DIR}/bus was not created"; exit 1; }

run_opt() {
  setpriv --reuid="${OPT_UID}" --regid="${OPT_GID}" --init-groups -- \
    env -i \
    HOME="${BASE_DIR}" \
    USER="${OPT_USER}" \
    LOGNAME="${OPT_USER}" \
    SHELL="/bin/bash" \
    XDG_RUNTIME_DIR="${RUNTIME_DIR}" \
    XDG_CONFIG_HOME="${BASE_DIR}/.config" \
    XDG_DATA_HOME="${BASE_DIR}/.local/share" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=${RUNTIME_DIR}/bus" \
    DOCKER_HOST="unix://${RUNTIME_DIR}/docker.sock" \
    PATH="/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin" \
    "$@"
}

echo "[6/8] Install and start rootless Docker"
run_opt dockerd-rootless-setuptool.sh install --force
run_opt systemctl --user daemon-reload
run_opt systemctl --user enable --now docker.service

if [[ ! -f "${BASE_DIR}/compose.yaml" ]]; then
  cat >"${BASE_DIR}/compose.yaml" <<'EOF'
services:
  hello:
    image: hello-world
EOF
  chown "${OPT_USER}:${OPT_GROUP}" "${BASE_DIR}/compose.yaml"
  chmod 0640 "${BASE_DIR}/compose.yaml"
fi

echo "[7/8] Create controlled compose wrapper"
cat >/usr/local/sbin/opt-compose <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

BASE_DIR="/srv/docker-env"
OPT_USER="opt"
OPT_UID="$(id -u "${OPT_USER}")"
OPT_GID="$(id -g "${OPT_USER}")"
RUNTIME_DIR="/run/user/${OPT_UID}"
COMPOSE_FILE="${BASE_DIR}/compose.yaml"

cmd="${1:-}"

case "${cmd}" in
  up|down|restart|pull|ps|logs|config|images|version) shift ;;
  *)
    echo "Allowed: up down restart pull ps logs config images version" >&2
    exit 2
    ;;
esac

[[ -f "${COMPOSE_FILE}" ]] || { echo "ERROR: missing ${COMPOSE_FILE}" >&2; exit 1; }
[[ -S "${RUNTIME_DIR}/docker.sock" ]] || { echo "ERROR: rootless Docker socket not found" >&2; exit 1; }

cd "${BASE_DIR}"

exec /usr/bin/setpriv --reuid="${OPT_UID}" --regid="${OPT_GID}" --init-groups -- \
  env -i \
  HOME="${BASE_DIR}" \
  USER="${OPT_USER}" \
  LOGNAME="${OPT_USER}" \
  SHELL="/bin/bash" \
  XDG_RUNTIME_DIR="${RUNTIME_DIR}" \
  XDG_CONFIG_HOME="${BASE_DIR}/.config" \
  XDG_DATA_HOME="${BASE_DIR}/.local/share" \
  DOCKER_HOST="unix://${RUNTIME_DIR}/docker.sock" \
  PATH="/usr/local/bin:/usr/bin:/bin" \
  /usr/bin/docker compose --project-directory "${BASE_DIR}" -f "${COMPOSE_FILE}" "${cmd}" "$@"
EOF

chmod 0750 /usr/local/sbin/opt-compose
chown root:root /usr/local/sbin/opt-compose

echo "[8/8] Verify rootless Docker"
run_opt docker info --format 'SecurityOptions={{json .SecurityOptions}}'
/usr/local/sbin/opt-compose version

echo "DONE"
echo "Use:"
echo "  sudo /usr/local/sbin/opt-compose up -d"
echo "  sudo /usr/local/sbin/opt-compose ps"
echo "  sudo /usr/local/sbin/opt-compose logs"
