---
name: deploy-starcoach
description: Deploy StarCoach services on the cos-apps live stack. Use when the user asks to deploy StarCoach, cos-apps, live api, assessment, starguide, dashboard, or related Docker Compose services; asks for deployment commands/runbooks; or wants safe production deployment with rootless Docker, Nginx, smoke tests, and rollback. Always ask for the SSH login command and target deployment project before executing.
---

# Deploy StarCoach

## First Response

Before running any remote command, ask the user for exactly these required inputs if missing:

1. SSH login command, for example `ssh cos-apps`.
2. Deployment project: `api`, `assessment`, `starguide`, `dashboard`, or `full-live-stack`.

If the user also provides branch, commit, Mongo URI, or env changes, use them. If not, use the current tracked live branch and only fast-forward when clean.

## Hard Rules

- Do not run migrations, seed, drop, truncate, reset, or manual production data edits.
- Do not print `.env`, AWS credentials, Secret Manager values, Mongo URIs, JWT secrets, or API keys.
- Do not use `/srv/docker-env/compose.yaml` for live deployment; it is not the live stack.
- Use `/srv/docker-env/apps/live`.
- Use the `opt` user's rootless Docker socket. Do not run live Docker Compose with root or the SSH user's default Docker context.
- Stop and ask before overwriting local changes, running `reset --hard`, changing ownership broadly, or changing Nginx.
- Before changing compose, Nginx, or env files, create root-owned backups under `/root/deploy-backups/live-<timestamp>` with mode `600` for copied env files.

## Rootless Docker Template

Use this wrapper for Docker and Docker Compose operations:

```bash
sudo -u opt env \
  XDG_RUNTIME_DIR=/run/user/1006 \
  DOCKER_HOST=unix:///run/user/1006/docker.sock \
  bash -lc 'cd /srv/docker-env/apps/live && docker compose --env-file .env -f compose.yaml ...'
```

The live services are:

```text
api
api-gateway
assessment
dashboard
starguide
```

Current live host ports are expected to be:

```text
assessment    127.0.0.1:15500 -> 5500
api-gateway   127.0.0.1:18001 -> 8001
starguide     127.0.0.1:18042 -> 8042
dashboard     127.0.0.1:18312 -> 4001
```

## Preflight

After the user provides the SSH command and project, run read-only checks first:

```bash
<ssh-command> 'hostname; whoami; sudo -n true'

<ssh-command> 'sudo -u opt env XDG_RUNTIME_DIR=/run/user/1006 DOCKER_HOST=unix:///run/user/1006/docker.sock bash -lc "
  cd /srv/docker-env/apps/live
  docker compose --env-file .env -f compose.yaml ps
  docker compose --env-file .env -f compose.yaml config --services
"'
```

Check the target app git state without changing it:

```bash
<ssh-command> 'sudo -u opt bash -lc "
  cd /srv/docker-env/apps/live/<project>/app
  echo OLD_SHA=$(git rev-parse --short HEAD)
  git status -sb
  git fetch origin
  git rev-parse --abbrev-ref HEAD
  git log --oneline HEAD..@{u} 2>/dev/null || true
"'
```

For `api-gateway`, there is no separate app repo; deploy it only when Nginx gateway config or compose changed.

If `git status -sb` shows local changes or untracked files that could affect deployment, report them and ask before proceeding. Untracked files unrelated to build/runtime may be left untouched, but do not delete them.

## Backups

Create backups before changing env, compose, or Nginx:

```bash
<ssh-command> 'ts=$(date +%F-%H%M%S)
sudo install -d -m 700 -o root -g root /root/deploy-backups/live-$ts
sudo cp -a /srv/docker-env/apps/live/compose.yaml /root/deploy-backups/live-$ts/compose.yaml
sudo cp -a /srv/docker-env/apps/live/.env /root/deploy-backups/live-$ts/live.env
sudo chmod 600 /root/deploy-backups/live-$ts/live.env
echo BACKUP_DIR=/root/deploy-backups/live-$ts'
```

If changing a project env:

```bash
sudo cp -a /srv/docker-env/apps/live/<project>/app/.env "$BACKUP_DIR/<project>.env"
sudo chmod 600 "$BACKUP_DIR/<project>.env"
```

If changing Nginx:

```bash
sudo cp -a /etc/nginx/sites-available/live.dev.starcoach.ai.conf "$BACKUP_DIR/live.dev.starcoach.ai.conf"
sudo cp -a /etc/nginx/sites-available/dashboard.dev.starcoach.ai.conf "$BACKUP_DIR/dashboard.dev.starcoach.ai.conf"
```

## Code Update

Use fast-forward only:

```bash
<ssh-command> 'sudo -u opt bash -lc "
  cd /srv/docker-env/apps/live/<project>/app
  git merge --ff-only @{u}
"'
```

If upstream is not configured, use the current branch explicitly:

```bash
git fetch origin <branch>
git merge --ff-only origin/<branch>
```

Do not use `reset --hard` unless the user explicitly authorizes it after seeing the local status.

## Project Workflows

### api

Deploy only the API container unless the gateway config changed:

```bash
<ssh-command> 'sudo -u opt env XDG_RUNTIME_DIR=/run/user/1006 DOCKER_HOST=unix:///run/user/1006/docker.sock bash -lc "
  cd /srv/docker-env/apps/live
  docker compose --env-file .env -f compose.yaml build api
  docker compose --env-file .env -f compose.yaml up -d api
  docker compose --env-file .env -f compose.yaml ps api
"'
```

Smoke:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18001/api/sse/
curl -sS -i --max-time 8 http://127.0.0.1:18001/api/health
curl -sk --resolve live.dev.starcoach.ai:443:127.0.0.1 -o /dev/null -w "%{http_code}\n" https://live.dev.starcoach.ai/lpr/api/sse/
```

Expected: SSE may return `401` when unauthenticated. `/api/health` may return `503` while Mongo still points at an unavailable host; report that as a known data-link blocker, not as a deployment failure, unless it changed unexpectedly.

### assessment

If a Mongo Atlas URI is provided, add `MONGODB_URI=...` to `/srv/docker-env/apps/live/assessment/app/.env`; keep old `DATABASE_*` values for rollback reference. Preserve permissions:

```bash
sudo chown opt:opt /srv/docker-env/apps/live/assessment/app/.env
sudo chmod 600 /srv/docker-env/apps/live/assessment/app/.env
```

Then build and restart:

```bash
docker compose --env-file .env -f compose.yaml build assessment
docker compose --env-file .env -f compose.yaml up -d assessment
docker compose --env-file .env -f compose.yaml ps assessment
```

Smoke with local Nginx:

```bash
curl -sk --resolve live.dev.starcoach.ai:443:127.0.0.1 -o /dev/null -w "%{http_code} %{redirect_url}\n" https://live.dev.starcoach.ai/
curl -sk --resolve live.dev.starcoach.ai:443:127.0.0.1 -o /dev/null -w "%{http_code} %{redirect_url}\n" https://live.dev.starcoach.ai/teacher
curl -sk --resolve live.dev.starcoach.ai:443:127.0.0.1 -o /dev/null -w "%{http_code} %{redirect_url}\n" https://live.dev.starcoach.ai/student
```

### starguide

Starguide is built to static `dist` and served by its Nginx container. Updating Vite env values requires rebuilding `dist`.

Update code, then build the frontend on the host as `opt`:

```bash
<ssh-command> 'sudo -u opt bash -lc "
  cd /srv/docker-env/apps/live/starguide/app
  npm ci
  npm run build
"'
```

Restart the service:

```bash
<ssh-command> 'sudo -u opt env XDG_RUNTIME_DIR=/run/user/1006 DOCKER_HOST=unix:///run/user/1006/docker.sock bash -lc "
  cd /srv/docker-env/apps/live
  docker compose --env-file .env -f compose.yaml up -d starguide
  docker compose --env-file .env -f compose.yaml ps starguide
"'
```

If `starguide/Dockerfile` or `starguide/nginx/conf.d/starguide.conf` changed, include a compose build:

```bash
docker compose --env-file .env -f compose.yaml build starguide
docker compose --env-file .env -f compose.yaml up -d starguide
```

Smoke:

```bash
curl -sk --resolve live.dev.starcoach.ai:443:127.0.0.1 -o /dev/null -w "%{http_code}\n" https://live.dev.starcoach.ai/starguide/
curl -sk --resolve live.dev.starcoach.ai:443:127.0.0.1 -o /dev/null -w "%{http_code}\n" https://live.dev.starcoach.ai/mini-lesson/
curl -sk --resolve live.dev.starcoach.ai:443:127.0.0.1 -o /dev/null -w "%{http_code}\n" https://live.dev.starcoach.ai/starcamp/
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18042/starguide/
```

### dashboard

Dashboard is a Next app on `dashboard.dev.starcoach.ai`, served through host port `18312`.

```bash
docker compose --env-file .env -f compose.yaml build dashboard
docker compose --env-file .env -f compose.yaml up -d dashboard
docker compose --env-file .env -f compose.yaml ps dashboard
```

Smoke:

```bash
curl -sk --resolve dashboard.dev.starcoach.ai:443:127.0.0.1 -o /dev/null -w "%{http_code} %{redirect_url}\n" https://dashboard.dev.starcoach.ai/
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18312/
```

### full-live-stack

Only use when the user explicitly asks for a full stack redeploy:

```bash
docker compose --env-file .env -f compose.yaml build api api-gateway assessment dashboard starguide
docker compose --env-file .env -f compose.yaml up -d api api-gateway assessment dashboard starguide
docker compose --env-file .env -f compose.yaml ps
```

## Nginx

Mongo/env-only changes do not require Nginx changes.

The host Nginx files are:

```text
/etc/nginx/sites-available/live.dev.starcoach.ai.conf
/etc/nginx/sites-available/dashboard.dev.starcoach.ai.conf
```

If Nginx must change, back up first, then:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Use `--resolve <domain>:443:127.0.0.1` for local validation because public DNS may point at another load balancer or instance.

## Logs

After any deployment, check logs:

```bash
<ssh-command> 'sudo -u opt env XDG_RUNTIME_DIR=/run/user/1006 DOCKER_HOST=unix:///run/user/1006/docker.sock bash -lc "
  cd /srv/docker-env/apps/live
  docker compose --env-file .env -f compose.yaml logs --tail=120 <service>
"'
```

Look for restarts, build errors, Mongo/Redis/AWS/SSM errors, 502/504, static asset 404s, and upload size failures.

## Rollback

Record the old commit before deployment:

```bash
sudo -u opt git -C /srv/docker-env/apps/live/<project>/app rev-parse --short HEAD
```

Rollback code:

```bash
OLD_SHA=<old-sha>
sudo -u opt bash -lc "
  cd /srv/docker-env/apps/live/<project>/app
  git switch --detach $OLD_SHA
"
```

Restore project env only if it was changed:

```bash
sudo cp -a "$BACKUP_DIR/<project>.env" /srv/docker-env/apps/live/<project>/app/.env
sudo chown opt:opt /srv/docker-env/apps/live/<project>/app/.env
sudo chmod 600 /srv/docker-env/apps/live/<project>/app/.env
```

Rebuild/restart the affected service. If users have written data to Atlas or another new database after deployment, do not switch the app back to an old database without explicit confirmation; that can create data divergence.
