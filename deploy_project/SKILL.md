---
name: deploy-project
description: Use when deploying PHP services on the ntest /srv/docker-env host, adding apps under apps/, creating GitLab CI deploy wrappers, or modeling a new service after the existing api deployment.
---

# Deploy Project

## Scope

Use this for the ntest deployment pattern:

- rootless Docker runs as `opt` with `HOME=/srv/docker-env`.
- service code lives under `/srv/docker-env/apps/<app>/src`.
- shared PHP runtimes live under `/srv/docker-env/deploy/php/<version>`.
- `/usr/local/sbin/sopt` runs commands as `opt`.
- `/usr/local/sbin/api-compose` wraps `docker compose -f /srv/docker-env/docker-compose.yaml`.
- GitLab CI calls a root-owned deploy wrapper such as `/usr/local/sbin/deploy-api-test`.

## Safety Rules

- Do not read or print secrets: `/srv/docker-env/.git-credentials`, private keys, `.env`, tokenized URLs, or full privileged wrapper bodies.
- Before changing compose or nginx files, create timestamped backups.
- Prefer adding a project-specific wrapper over giving CI broad `sopt *` access.
- Confirm Git access before deployment. Server-side wrappers use `git fetch` from `apps/<app>/src`; they need working credentials or SSH deploy keys.
- Do not run `reset --hard` or `clean -fd` unless the user accepts that local changes in `apps/<app>/src` will be discarded.

## Existing API Pattern

Current API uses:

```text
/srv/docker-env/apps/api/src
/srv/docker-env/deploy/php/7.4
/srv/docker-env/nginx/conf.d/api-8081.conf
/usr/local/sbin/deploy-api-test
/usr/local/sbin/api-compose
```

`deploy-api-test build` performs:

```text
git fetch origin
git checkout test
git reset --hard origin/test
git clean -fd
api-compose build api-php
api-compose run --rm --no-deps api-composer install --no-dev --prefer-dist --no-interaction --optimize-autoloader
```

`deploy-api-test deploy` performs:

```text
api-compose up -d api-php
api-compose restart api-php
api-compose ps api-php
```

## New PHP App Checklist

1. Pick values:

```text
app name: back
repo: http://gitlab.example.internal/team/project/app_back.git
branch: test
public port: 8082
host fpm port: 9075
php runtime: /srv/docker-env/deploy/php/7.4
```

2. Generate assets locally:

```bash
python3 ~/.agents/skills/deploy_project/scripts/render_php_app_assets.py \
  --app back \
  --repo http://gitlab.example.internal/team/project/app_back.git \
  --branch test \
  --public-port 8082 \
  --fpm-port 9075 \
  --output /tmp/back-deploy-assets
```

3. On the server, create the app directory and clone source as `opt`:

```bash
sudo install -d -o opt -g opt -m 0750 /srv/docker-env/apps/back
sudo /usr/local/sbin/sopt git clone http://gitlab.example.internal/team/project/app_back.git apps/back/src
sudo /usr/local/sbin/sopt git -C apps/back/src checkout test
```

4. Merge the generated compose snippet into `/srv/docker-env/docker-compose.yaml`:

- add `<app>-php`
- add `<app>-composer`
- add the app source volume to `nginx-gateway`
- add the public port to `nginx-gateway`

5. Install generated files:

```text
nginx/<app>-<port>.conf -> /srv/docker-env/nginx/conf.d/
deploy-<app>-<branch>  -> /usr/local/sbin/
gitlab-ci.yml          -> app repository .gitlab-ci.yml
```

6. Validate before first deployment:

```bash
sudo /usr/local/sbin/api-compose config
sudo /usr/local/sbin/deploy-<app>-<branch> build
sudo /usr/local/sbin/deploy-<app>-<branch> deploy
sudo /usr/local/sbin/deploy-<app>-<branch> status
curl -I http://127.0.0.1:<public-port>/nginx-health
```

## Common Mistakes

- Confusing CI permission with server Git permission. CI can call the deploy wrapper, but the wrapper still runs server-side `git fetch`.
- Forgetting nginx must mount the new app source read-only.
- Adding only the PHP service and forgetting the composer helper service.
- Reusing `api-php` names. Each app needs unique service, image, container, port, and nginx config names.
- Leaving `james NOPASSWD: ALL` enabled after maintenance.

