---
name: deploy
description: "Bootstrap a fresh Debian server deployment environment. Use when Codex is asked to 初始部署, 全新部署, 初始化服务器, 部署 docker 环境, create /srv/docker-env, set up opt, rootless Docker, PHP or Node runtime, or optional Nginx during first-time deployment. Not for incremental application releases."
---

# Deploy

<role>Fresh-server deployment coordinator. Follow the user's staged bootstrap design, use bundled scripts where they exist, and stop for confirmation before SSH, user, Docker, or runtime changes.</role>

<scope>
This skill is for first-time deployment/bootstrap only.
For incremental releases of an existing application, do not use this workflow; ask for or create a separate incremental deployment skill.
</scope>

<bundled_scripts>
- `scripts/create_admin_user.sh`: create the login-capable management user, configure SSH public key or certificate authority login, optional sudo, and optional additional SSH port.
- `scripts/create_user.sh`: create and harden the non-login `opt` runtime user and `/srv/docker-env` directory ownership.
- `scripts/deploy_docker.sh`: install Docker/Compose, configure rootless Docker for `opt`, create `opt-compose`, and verify rootless Docker.
</bundled_scripts>

<workflow>
1. Choose execution target.
   - Ask first: deploy on the local machine or a remote server?
   - Local: run commands only after confirming the local machine is the intended target.
   - Remote: require one connection method before planning remote commands:
     - SSH config alias, preferred: `target`.
     - Explicit SSH fields: `host`, `user`, `port`, `identity_file`, optional `certificate_file`, optional `jump_host`.
     - Manual mode: generate upload/run commands for the user to execute; do not connect.
   - Never ask for or accept private key contents, passwords, tokens, or certificate private material.

2. Collect required deployment inputs.
   - Target server connection method from step 1.
   - Management user: username, SSH public key or certificate source, and whether this user should get sudo.
   - SSH policy: ask whether to change the SSH port.
   - Runtime: ask whether to deploy `php`, `node`, or `go`.
   - PHP runtime: if `php`, ask for `version`.
   - Nginx: ask whether to deploy Nginx.

3. Confirm current support.
   - Debian server only.
   - Management-user creation and SSH key/certificate-login setup are supported through `scripts/create_admin_user.sh`.
   - Docker environment is supported through bundled scripts.
   - `opt` runtime user is supported through `scripts/create_user.sh`.
   - PHP and Node are the only intended runtime choices for now.
   - Go is not supported yet; stop if the user chooses Go.

4. Verify target access.
   - Local: confirm `id -u`, hostname, and `/etc/os-release`.
   - Remote SSH alias: verify with `ssh <target> 'id -u && hostname && . /etc/os-release && echo "$ID $VERSION_CODENAME"'`.
   - Remote explicit fields: build `ssh`/`scp` options from paths and host fields, then run the same verification command.
   - Manual mode: output the verification command and stop until the user provides the result.
   - Stop unless the target is Debian and the effective user is root or can run passwordless sudo for root-required steps.

5. Plan the deployment phases.
   - Phase A: create management user with `scripts/create_admin_user.sh`, configure SSH key/certificate login, upload public key or CA material, set permissions, optionally add the new SSH port.
   - Phase B: update system and apply baseline security hardening.
   - Phase C: create the Docker environment under `/srv/docker-env` by running `scripts/deploy_docker.sh`.
   - Phase D: create runtime environment.
     - PHP: create `/srv/docker-env/deploy/php/{version}`, copy the specified PHP config files to the server, then generate the PHP Docker configuration.
     - Node: keep as placeholder until the Node runtime script is defined.
   - Phase E: optionally deploy Nginx by running the corresponding Nginx script when it exists.

6. Safety gate before execution.
   - Show the target server, SSH port plan, management user, `opt` user, Docker rootless plan, whether rootful Docker will be disabled, runtime choice, PHP version if any, and Nginx choice.
   - Show the connection method without printing secret contents.
   - Ask for explicit confirmation before running remote commands.
   - If changing SSH port, require a test plan that keeps the existing SSH session open until the new port is verified.
   - Treat `scripts/create_admin_user.sh` as adding/verifying an SSH port; do not close the old port until a later verified hardening step.
   - If `DISABLE_ROOTFUL_DOCKER=1`, warn that rootful Docker service/socket will be disabled and masked.

7. Execute Docker environment phase.
   - Upload `scripts/create_user.sh` and `scripts/deploy_docker.sh` to the target server.
   - Run `scripts/deploy_docker.sh` as root on the target server.
   - Treat `scripts/deploy_docker.sh` as the public entrypoint; it calls `scripts/create_user.sh`.
   - Do not separately run `scripts/create_user.sh` unless the user only asks for the `opt` user phase.

8. Verify Docker environment.
   - Confirm `/srv/docker-env` exists.
   - Confirm `opt` exists, is non-login, and is denied SSH.
   - Confirm rootless Docker socket exists under `/run/user/<opt_uid>/docker.sock`.
   - Confirm `/usr/local/sbin/opt-compose version` succeeds.
   - Confirm `sudo /usr/local/sbin/opt-compose ps` or an equivalent safe status command succeeds.

9. Runtime and Nginx phases.
   - For PHP, stop if the PHP config source directory or PHP version is missing.
   - For Node, stop and report that the Node runtime script is not defined yet.
   - For Nginx, stop unless the Nginx script path and required domain/port/certificate inputs are defined.

10. Report.
   - Target server and SSH access state.
   - Users created or verified.
   - Docker/rootless status.
   - Runtime selected and what was created.
   - Nginx selected and what was created.
   - Commands run and verification results.
   - Blockers or scripts still missing.
</workflow>

<hard_rules>
P0 - Do not claim management-user or SSH certificate automation is complete until a script or explicit command plan exists.
P0 - Do not run remote deployment commands without explicit user confirmation.
P0 - Do not print private keys, tokens, cookies, passwords, or certificate private material.
P0 - Do not invent PHP, Node, or Nginx scripts. Use bundled scripts or user-provided script paths.
P0 - Do not proceed with Go runtime; it is unsupported for now.
P1 - Preserve existing SSH access while changing SSH config or ports.
P1 - Treat rootless Docker low-port binding as a design question before putting Nginx on ports 80/443.
</hard_rules>

<output_format>
Status: plan-ready | executed | verified | blocked | failed
Target: server, OS, SSH port
Users: management user status, opt user status
Docker: rootless status, opt-compose status
Runtime: php/node/go choice and result
Nginx: choice and result
Commands: commands run or planned
Verification: checks and results
Blockers: missing input, missing script, or failed command
</output_format>
