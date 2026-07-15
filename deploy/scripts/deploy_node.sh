#!/usr/bin/env bash
set -Eeuo pipefail

OPT_USER="${OPT_USER:-opt}"
OPT_GROUP="${OPT_GROUP:-opt}"
BASE_DIR="${BASE_DIR:-/srv/docker-env}"
NODE_MAJOR="${NODE_MAJOR:-24}"
ENABLE_COREPACK="${ENABLE_COREPACK:-1}"
INSTALL_BUILD_TOOLS="${INSTALL_BUILD_TOOLS:-1}"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: run as root"; exit 1; }

. /etc/os-release
[[ "${ID}" == "debian" ]] || { echo "ERROR: Debian only"; exit 1; }
[[ "${NODE_MAJOR}" =~ ^[0-9]+$ ]] || { echo "ERROR: NODE_MAJOR must be numeric"; exit 1; }

export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

echo "[node] Verify runtime user and base directory"
id "${OPT_USER}" >/dev/null 2>&1 || {
  echo "ERROR: missing ${OPT_USER}; run deploy_docker.sh first" >&2
  exit 1
}
getent group "${OPT_GROUP}" >/dev/null || {
  echo "ERROR: missing group ${OPT_GROUP}; run deploy_docker.sh first" >&2
  exit 1
}
[[ -d "${BASE_DIR}" ]] || {
  echo "ERROR: missing ${BASE_DIR}; run deploy_docker.sh first" >&2
  exit 1
}

echo "[node] Install NodeSource repository for Node.js ${NODE_MAJOR}.x"
apt-get update
apt-get install -y ca-certificates curl gnupg

if [[ "${INSTALL_BUILD_TOOLS}" == "1" ]]; then
  apt-get install -y build-essential git python3 make g++
fi

install -m 0755 -d /usr/share/keyrings
rm -f /usr/share/keyrings/nodesource.gpg \
  /etc/apt/sources.list.d/nodesource.list \
  /etc/apt/sources.list.d/nodesource.sources

curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
  | gpg --dearmor -o /usr/share/keyrings/nodesource.gpg
chmod 0644 /usr/share/keyrings/nodesource.gpg

ARCH="$(dpkg --print-architecture)"
case "${ARCH}" in
  amd64|arm64) ;;
  *)
    echo "ERROR: unsupported architecture ${ARCH}; NodeSource supports amd64/arm64 here" >&2
    exit 1
    ;;
esac

cat >/etc/apt/sources.list.d/nodesource.sources <<EOF
Types: deb
URIs: https://deb.nodesource.com/node_${NODE_MAJOR}.x
Suites: nodistro
Components: main
Architectures: ${ARCH}
Signed-By: /usr/share/keyrings/nodesource.gpg
EOF

cat >/etc/apt/preferences.d/nodejs <<'EOF'
Package: nodejs
Pin: origin deb.nodesource.com
Pin-Priority: 600
EOF

apt-get update
apt-get install -y nodejs

echo "[node] Prepare opt-owned Node workspace"
install -d -o "${OPT_USER}" -g "${OPT_GROUP}" -m 0750 \
  "${BASE_DIR}/deploy" \
  "${BASE_DIR}/deploy/node" \
  "${BASE_DIR}/apps" \
  "${BASE_DIR}/.npm" \
  "${BASE_DIR}/.cache"

echo "[node] Create controlled opt runtime wrapper"
cat >/usr/local/sbin/opt <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

BASE_DIR="${BASE_DIR}"
OPT_USER="${OPT_USER}"
OPT_UID="\$(id -u "\${OPT_USER}")"
OPT_GID="\$(id -g "\${OPT_USER}")"
RUNTIME_DIR="/run/user/\${OPT_UID}"

if [[ "\${#}" -eq 0 ]]; then
  echo "Usage: sudo opt <command> [args...]" >&2
  echo "Example: sudo opt npm install" >&2
  exit 2
fi

if [[ "\${EUID}" -ne 0 ]]; then
  echo "ERROR: run as root, e.g. sudo opt <command> [args...]" >&2
  exit 1
fi

exec /usr/bin/setpriv --reuid="\${OPT_UID}" --regid="\${OPT_GID}" --init-groups -- \\
  env -i \\
  HOME="\${BASE_DIR}" \\
  USER="\${OPT_USER}" \\
  LOGNAME="\${OPT_USER}" \\
  SHELL="/bin/bash" \\
  XDG_RUNTIME_DIR="\${RUNTIME_DIR}" \\
  XDG_CONFIG_HOME="\${BASE_DIR}/.config" \\
  XDG_DATA_HOME="\${BASE_DIR}/.local/share" \\
  DBUS_SESSION_BUS_ADDRESS="unix:path=\${RUNTIME_DIR}/bus" \\
  DOCKER_HOST="unix://\${RUNTIME_DIR}/docker.sock" \\
  NPM_CONFIG_CACHE="\${BASE_DIR}/.npm" \\
  COREPACK_HOME="\${BASE_DIR}/.cache/corepack" \\
  PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \\
  "\$@"
EOF

chmod 0755 /usr/local/sbin/opt
chown root:root /usr/local/sbin/opt
ln -sf /usr/local/sbin/opt /usr/local/bin/opt
rm -f /usr/local/sbin/opt-node \
  /usr/local/sbin/opt-npm \
  /usr/local/sbin/opt-npx \
  /usr/local/sbin/opt-corepack

if [[ "${ENABLE_COREPACK}" == "1" ]]; then
  echo "[node] Enable Corepack"
  if command -v corepack >/dev/null 2>&1; then
    corepack enable
  else
    echo "WARN: corepack command not found; skipping Corepack enable" >&2
  fi
fi

chown -R "${OPT_USER}:${OPT_GROUP}" \
  "${BASE_DIR}/deploy/node" \
  "${BASE_DIR}/.npm" \
  "${BASE_DIR}/.cache"

echo "[node] Verify Node runtime"
node --version
npm --version
/usr/local/sbin/opt node --version
/usr/local/sbin/opt npm --version
if command -v corepack >/dev/null 2>&1; then
  corepack --version
fi

echo "DONE node runtime: Node.js ${NODE_MAJOR}.x"
echo "Use:"
echo "  sudo opt node --version"
echo "  sudo opt npm --version"
echo "  sudo opt npm install"
