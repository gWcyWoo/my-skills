#!/usr/bin/env python3
"""Render deployment assets for a /srv/docker-env PHP app."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")
    if not cleaned:
        raise SystemExit("app name must contain letters, numbers, '_' or '-'")
    return cleaned.lower().replace("_", "-")


def write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def compose_snippet(app: str, php_version: str, fpm_port: int) -> str:
    image = f"local/{app}-php{php_version.replace('.', '')}:latest"
    return f"""# Merge these services into /srv/docker-env/docker-compose.yaml
# Also add the app volume and public port to nginx-gateway.

  {app}-php:
    build:
      context: /srv/docker-env/deploy/php/{php_version}
      dockerfile: Dockerfile
    image: {image}
    container_name: {app}-php
    restart: unless-stopped
    volumes:
      - /srv/docker-env/apps/{app}/src:/var/www/{app}
    ports:
      - "127.0.0.1:{fpm_port}:9000"
    healthcheck:
      test: ["CMD-SHELL", "SCRIPT_NAME=/ping SCRIPT_FILENAME=/ping REQUEST_METHOD=GET cgi-fcgi -bind -connect 127.0.0.1:9000 | grep -q pong"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - app-proxy-net

  {app}-composer:
    image: {image}
    working_dir: /var/www/{app}
    volumes:
      - /srv/docker-env/apps/{app}/src:/var/www/{app}
    entrypoint: ["composer"]
    networks:
      - app-proxy-net

# Add to nginx-gateway.ports:
#      - "0.0.0.0:<public-port>:<public-port>"
#
# Add to nginx-gateway.volumes:
#      - /srv/docker-env/apps/{app}/src:/var/www/{app}:ro
"""


def nginx_conf(app: str, public_port: int) -> str:
    return f"""server {{
    listen {public_port};
    server_name _;

    root /var/www/{app}/public;
    index index.php index.html;

    client_max_body_size 20m;

    location = /nginx-health {{
        return 200 "ok\\n";
    }}

    location / {{
        try_files $uri $uri/ @{app};
    }}

    location @{app} {{
        include fastcgi_params;
        fastcgi_pass {app}-php:9000;
        fastcgi_param SCRIPT_FILENAME /var/www/{app}/public/index.php;
        fastcgi_param SCRIPT_NAME /index.php;
    }}

    location = /index.php {{
        include fastcgi_params;
        fastcgi_pass {app}-php:9000;
        fastcgi_param SCRIPT_FILENAME /var/www/{app}/public/index.php;
        fastcgi_param SCRIPT_NAME /index.php;
    }}

    location ~ /\\.(?!well-known).* {{
        deny all;
    }}
}}
"""


def deploy_script(app: str, branch: str) -> str:
    return f"""#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/srv/docker-env/apps/{app}"
SRC_DIR="${{APP_DIR}}/src"
COMPOSE="/usr/local/sbin/api-compose"
BRANCH="{branch}"

usage() {{
  echo "Usage: deploy-{app}-{branch} {{build|deploy|status|all}}" >&2
  exit 2
}}

ACTION="${{1:-status}}"

run_build() {{
  echo "[build] update source code"
  if [[ ! -d "${{SRC_DIR}}/.git" ]]; then
    echo "ERROR: ${{SRC_DIR}} is not a git repository" >&2
    exit 1
  fi

  /usr/local/sbin/sopt git -C apps/{app}/src fetch origin
  /usr/local/sbin/sopt git -C apps/{app}/src checkout "${{BRANCH}}"
  /usr/local/sbin/sopt git -C apps/{app}/src reset --hard "origin/${{BRANCH}}"
  /usr/local/sbin/sopt git -C apps/{app}/src clean -fd

  echo "[build] build php-fpm image"
  "${{COMPOSE}}" build {app}-php

  echo "[build] composer install"
  "${{COMPOSE}}" run --rm --no-deps {app}-composer install \\
    --no-dev \\
    --prefer-dist \\
    --no-interaction \\
    --optimize-autoloader
}}

run_deploy() {{
  echo "[deploy] start {app}-php"
  "${{COMPOSE}}" up -d {app}-php

  echo "[deploy] restart php-fpm"
  "${{COMPOSE}}" restart {app}-php

  echo "[deploy] status"
  "${{COMPOSE}}" ps {app}-php
}}

run_status() {{
  if [[ -d "${{SRC_DIR}}/.git" ]]; then
    /usr/local/sbin/sopt git -C apps/{app}/src status --short --branch
  fi

  "${{COMPOSE}}" ps
}}

case "${{ACTION}}" in
  build) run_build ;;
  deploy) run_deploy ;;
  status) run_status ;;
  all)
    run_build
    run_deploy
    ;;
  *) usage ;;
esac
"""


def gitlab_ci(app: str, branch: str) -> str:
    script = f"/usr/local/sbin/deploy-{app}-{branch}"
    return f"""stages:
  - build
  - deploy

build_{branch}:
  stage: build
  tags:
    - deploy
  rules:
    - if: '$CI_COMMIT_BRANCH == "{branch}"'
  script:
    - sudo {script} build

deploy_{branch}:
  stage: deploy
  tags:
    - deploy
  rules:
    - if: '$CI_COMMIT_BRANCH == "{branch}"'
  needs:
    - build_{branch}
  script:
    - sudo {script} deploy
"""


def monitor_script(app: str) -> str:
    return f"""#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE="/usr/local/sbin/api-compose"
SERVICE="{app}-php"

if ! "${{COMPOSE}}" ps --services --filter "status=running" | grep -qx "${{SERVICE}}"; then
  echo "${{SERVICE}} container not found; starting"
  "${{COMPOSE}}" up -d "${{SERVICE}}"
  exit 0
fi

if ! "${{COMPOSE}}" exec -T "${{SERVICE}}" true >/dev/null 2>&1; then
  echo "${{SERVICE}} is not responding to exec; restarting"
  "${{COMPOSE}}" restart "${{SERVICE}}"
  exit 0
fi

health="$(/usr/local/sbin/sopt docker inspect -f '{{{{.State.Health.Status}}}}' "${{SERVICE}}" 2>/dev/null || true)"
case "${{health}}" in
  healthy|"")
    echo "${{SERVICE}} health=${{health:-none}}"
    ;;
  *)
    echo "${{SERVICE}} unhealthy; restarting"
    "${{COMPOSE}}" restart "${{SERVICE}}"
    ;;
esac
"""


def systemd_units(app: str) -> tuple[str, str]:
    service = f"""[Unit]
Description=Monitor {app} php-fpm container health

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/monitor-{app}-php
"""
    timer = f"""[Unit]
Description=Run {app} php-fpm health monitor every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=15s

[Install]
WantedBy=timers.target
"""
    return service, timer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, help="short app name, e.g. back")
    parser.add_argument("--repo", required=True, help="Git repository URL")
    parser.add_argument("--branch", default="test")
    parser.add_argument("--php-version", default="7.4")
    parser.add_argument("--public-port", type=int, required=True)
    parser.add_argument("--fpm-port", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    app = slug(args.app)
    branch = slug(args.branch)
    out = Path(args.output)

    write(out / "compose" / f"{app}-services.yaml", compose_snippet(app, args.php_version, args.fpm_port))
    write(out / "nginx" / f"{app}-{args.public_port}.conf", nginx_conf(app, args.public_port))
    write(out / "sbin" / f"deploy-{app}-{branch}", deploy_script(app, branch), 0o750)
    write(out / "sbin" / f"monitor-{app}-php", monitor_script(app), 0o750)
    write(out / "gitlab-ci.yml", gitlab_ci(app, branch))
    service, timer = systemd_units(app)
    write(out / "systemd" / f"monitor-{app}-php.service", service)
    write(out / "systemd" / f"monitor-{app}-php.timer", timer)
    write(out / "sudoers" / f"deploy-{app}-{branch}", f"gitlab-runner ALL=(root) NOPASSWD: /usr/local/sbin/deploy-{app}-{branch}\n", 0o440)

    print(f"Rendered assets for {app} in {out}")
    print(f"Repository: {args.repo}")
    print("Install these after reviewing and merging compose/nginx changes.")


if __name__ == "__main__":
    main()

