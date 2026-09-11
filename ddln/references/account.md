# Account provisioning and safe re-entry

## Connection & credential model
- `<profile>` names a credential dir `~/.ssh/<profile>/` (e.g. `nigeria`) holding `dpt.conf` (non-secret), the ops key `<user>_ed25519`, and `<user>.sudo` (the ops-user password, plaintext, 600).
- **目录名是唯一真源 / 可随意改名**:`dpt.conf` 只存"服务器侧事实"(`DPT_HOST/PORT/USER/DROPIN`);本地路径与 profile 名(`DPT_PROFILE/DIR/KEY/PWFILE/CTRL`)一律由 `dpt_load` 按 profile **目录**推导,`list_profiles` 也报目录 basename。所以 `mv ~/.ssh/foo ~/.ssh/bar` 后 `bar` 直接可用——`dpt.conf` 不记自己的目录名/路径,绝不把目录名耦合进文件。
- `connect.sh` opens ONE root-password SSH master; the password is typed by the user in their terminal and NEVER stored. All later scripts reuse the socket — no further password.
- The ops-user password is generated locally, set on the server (server keeps only the salted hash), and saved to `~/.ssh/<profile>/<user>.sudo`. Deploy-time sudo uses NOPASSWD, so scripts never read that file; it exists for sudo AFTER the final step revokes NOPASSWD.

## Re-entrancy model (same server, re-run safe) — drives Phase 0
A profile persists in `~/.ssh/<profile>/dpt.conf` (host/user/port/key paths), so a re-run REUSES it instead of re-asking. The channel is split by capability, and this split is a HARD constraint, not a preference:
- **Verify over cert (no root needed).** `test_login.sh` and `close_check.sh` log in as the ops user with the cert key (close_check via `DPT_BOOT=sudo`, routed to the cert+sudo branch in `common.sh`). Checking an existing box is cert-only.
- **Mutate over root (root master required).** `provision_user.sh`/`harden.sh` need the root ControlMaster; `harden.sh` hardcodes `DPT_BOOT=root` and relies on that master as a *reload-surviving rollback lifeline*. NEVER run hardening over the cert path — a bad reload could lock you out with no lifeline.
- **Consequence.** Once hardened, root login is locked (`permitrootlogin no` + `passwordauthentication no` + `allowusers`). Such a box can be VERIFIED on re-entry but not safely RE-hardened without re-opening a privileged lifeline. If re-hardening is needed and root is already locked, SURFACE it — do not force an unsafe cert-harden.

## Diagnosis reasoning (when test_login fails) — YOUR job
Run `collect_diag.sh`, read the evidence, and pick the targeted `apply_fix` — do NOT blind-apply every fix. The `[authlog]` block (sshd's own rejection reason) is the most authoritative; read it first.

| evidence | apply_fix |
|---|---|
| authlog: "bad ownership or modes for directory" / "Authentication refused" | the specific perms fix below that `[perms]` shows out of spec |
| `[perms]` ~/.ssh not 700 | `ssh_dir_perms` |
| `[perms]` authorized_keys not 600 | `authkeys_perms` |
| `[perms]` owner ≠ ops user | `ownership` |
| `[perms]` home dir group/other-writable | `home_writable` |
| `[sshd]` pubkeyauthentication no | `pubkey_auth` |
| `[sshd]` allowusers set but missing the ops user | `allowusers_add` |
| `[selinux]` Enforcing + authlog hints context | `selinux` |
| `[account]` passwd -S shows `L` (locked) | `unlock` |
| `[account]` shell is nologin/false | `set_shell` |

After each fix, re-run `test_login.sh`. Cap at ~3 rounds; if still failing once the evidence shows no remaining applicable fix, STOP and report unrecoverable with the evidence — never loop blindly.

## Security model (hard boundary)
- No server password (root or ops) ever enters this conversation. `connect.sh` takes the root password in the user's terminal; the ops password lives only in the `~/.ssh/<profile>/` file. You never read those files' contents back to the user.
- `connect.sh` is the ONLY script you must NOT run via the terminal command tool. All others you DO run via the terminal command tool.
- NOPASSWD sudo granted here is deploy-time scaffolding; revoking it is the FINAL deploy module's job (not built). Always surface this on completion.

## Reference (audit rule provenance)
`ssh_hardening.rules` derives from CIS Linux Benchmark §5.2 (SSH Server) and Mozilla's OpenSSH modern guidelines; each rule cites its source.



**Phase 0 — preflight, profile selection & inputs.**
1. Run `bash ~/.agents/skills/ddln/account/script/preflight.sh` to confirm all stage files exist. If it exits non-zero, STOP and report the `MISSING` line(s). Do NOT improvise an inline file-existence check (inline shell runs under the user's shell, which may not word-split as expected).
2. Run `bash ~/.agents/skills/ddln/lib/list_profiles.sh` to enumerate saved profiles.
   - Output is the single line `NONE` → no saved profile; skip to step 4.
   - Otherwise each line is `<profile>\t<host>\t<user>\t<port>`. Reuse an explicitly selected profile. Otherwise present the available profiles and a new-profile option, then ask for the target; accept an unambiguous natural-language answer.
3. EXISTING profile picked → take its host/user/port straight from that menu line; do NOT re-ask them (re-entrancy: reuse saved config). Go to Phase 0.5.
4. NEW profile (`新添加 profile`, or output was `NONE`) → collect only missing inputs, batching related questions: (a) `profile` (credential dir under `~/.ssh/`, e.g. `nigeria`), (b) server host, (c) ops username, (d) SSH port (default 22). Do NOT ask for any password, and do NOT ask "already configured" — a new profile is fresh.
   4a. **证书:新建 or 复用。** 复用已明确的决定；否则在创建凭据前确认新建或复用及对应路径。
       - **新建** → 不做额外动作;`provision_user.sh` 之后会生成。
       - **复用** → 再问**现有私钥的本地路径**,然后跑 `bash ~/.agents/skills/ddln/account/script/import_key.sh <profile> <user> <私钥路径>` —— 把私钥+公钥拷进 `~/.ssh/<profile>/`(600/644;源无 `.pub` 则从私钥派生)。之后 `provision_user.sh` 见 key 已存在 → **复用、不再新建**(只把公钥装进服务器 authorized_keys)。
       - ⚠️ 复用=多机共用一把 key,泄露则一起暴露;关键机建议各自新建。
   然后 → Phase 1。

**Phase 0.5 — re-entry routing (existing profile only; you run + reason).**
5. Probe cert: run `bash ~/.agents/skills/ddln/account/script/test_login.sh <profile>` (ops-user cert login on the saved port; no root master needed).
6. Cert exits 0 (works) → run `bash ~/.agents/skills/ddln/account/close/close_check.sh <profile>`:
   - ends `收尾检查全部通过 ✅` → module is ALREADY complete on this server. Report that account is already complete; no root connection or disconnect is needed. Continue only into later modules already requested by the user.
   - ends `❌` → hardening is incomplete/drifted; (re)hardening MUST go over root → go to Phase 1 (root connect), then JUMP to Phase 4 (harden) → Phase 5; SKIP provision (the ops user already works). If `connect.sh` fails because root is already locked, STOP and report: partially hardened with root locked, safe re-hardening needs a privileged lifeline that isn't available — quote the `❌` lines and the `connect.sh` failure.
7. Cert exits 1 (fails) → ops user is unprovisioned or its login is broken → go to Phase 1 (root connect) → Phase 2: re-run `provision_user.sh` (idempotent — reuses the existing key/password, dedup-installs the pubkey, and re-applies `.ssh` perms/owner, so it repairs most broken logins) → Phase 3 `test_login`; if still failing, run the diagnosis loop for causes provision can't fix (AllowUsers, SELinux, locked account, nologin shell).

**Phase 1 — connect (USER runs; you do NOT).**
8. Give the user this exact command to run in their terminal: `bash ~/.agents/skills/ddln/account/script/connect.sh <profile> <host> <user> <port>`, substituting the profile's saved-or-collected values. Tell them ssh will prompt for the root password once.
9. STOP. Wait until the user confirms `建立 root 连接... done`. Do not proceed without it (later scripts need the socket).

**Phase 2 — provision (you run via the terminal command tool).**
10. Provision for a new profile, or when Phase 0.5 routed here on a cert-FAIL: run `bash ~/.agents/skills/ddln/account/script/provision_user.sh <profile>` and report failures and the final result. It is idempotent — reuses an existing key/password, dedup-installs the pubkey, re-applies `.ssh` perms/owner. SKIP it only when Phase 0.5's cert probe already PASSED (nothing to provision).

**Phase 3 — login + diagnosis loop (you run + reason).**
11. Run `bash ~/.agents/skills/ddln/account/script/test_login.sh <profile>`.
12. If it exits 0 → certificate login works; go to Phase 4.
13. If it fails: run `bash ~/.agents/skills/ddln/account/script/collect_diag.sh <profile>`, READ the evidence using the evidence table above, run `bash ~/.agents/skills/ddln/account/script/apply_fix.sh <profile> <chosen-fix>` for the targeted fix, then re-run `test_login.sh`. Repeat ≤3 rounds.
14. If still failing with no applicable fix left → STOP, report unrecoverable, and quote the `[authlog]` + `[perms]` evidence verbatim.

**Phase 4 — hardening (you run via the terminal command tool).**
15. **先把当前 SSH 端口(`DPT_PORT`)显示给用户**,再问是否改 / 改成什么;默认保持当前。(同"展示现状再让用户决定"原则——不要只问"改成什么"而不亮出现状。)
16. Run `bash ~/.agents/skills/ddln/account/script/harden.sh <profile> [newport]`.
    16a. Success (ends `加固完成`) → continue.
    16b. Rollback (`已回滚 drop-in`) → STOP; report that hardening was rolled back, cert login still works on the old port, and reason about the likely cause (cloud security group not allowing the new port, or AllowUsers). Advise the fix (open the SG, re-run) and quote the rollback line.

**Phase 5 — close & finish.**
17. Run `bash ~/.agents/skills/ddln/account/close/close_check.sh <profile>`; if it ends `❌`, list the FAILED audit lines verbatim.
18. Run `bash ~/.agents/skills/ddln/account/script/disconnect.sh <profile>` to close the root channel.
19. Report per the requested module scope: key path, password-file path, and the NOPASSWD-revoke reminder.


