#!/usr/bin/env python3
"""Host-agnostic PR/MR submission for the self-evolution subagent.

NEVER hardcodes a vendor. Detects github / gitlab / other from the remote URL, then picks the
matching mechanism with graceful fallback, always ending by pushing the branch + surfacing a URL:

  github → `gh pr create` (if gh present)   | else push + https://HOST/owner/repo/pull/new/<branch>
  gitlab → `glab mr create` (if glab present)| else `git push -o merge_request.create` (push-option,
                                               creates the MR with NO CLI) | else web MR URL
  other  → push branch + print best-effort web URL (open PR/MR manually)

The one thing it ALWAYS does is `git push` the branch, so a self-hosted / unknown host never
hard-fails — the human can always open the PR/MR from the surfaced URL.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys


def sh(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def remote_info(remote: str):
    url = sh(f"git remote get-url {remote}").stdout.strip()
    m = re.match(r"(?:git@|ssh://git@|https?://)([^/:]+)[:/](.+?)(?:\.git)?$", url)
    host = m.group(1) if m else ""
    path = m.group(2) if m else ""
    if re.search(r"github", host):
        vendor = "github"
    elif re.search(r"gitlab", host):
        vendor = "gitlab"
    else:
        vendor = "unknown"  # self-hosted GitLab often has no 'gitlab' in host → handled by fallback
    return url, host, path, vendor


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--target", default="main")
    ap.add_argument("--remote", default="origin")
    a = ap.parse_args()

    _url, host, path, vendor = remote_info(a.remote)

    # GitLab can open the MR purely via push-options — no CLI required. Attach them to the push.
    pushopts = ""
    if vendor in ("gitlab", "unknown") and not shutil.which("glab"):
        # harmless on a non-GitLab remote (ignored), so safe to attempt for 'unknown' too.
        title = a.title.replace('"', "'")
        pushopts = (f' -o merge_request.create -o merge_request.target={a.target}'
                    f' -o merge_request.title="{title}"')

    push = sh(f"git push -u {a.remote} {a.branch}{pushopts}")
    if push.returncode != 0:
        sys.stderr.write(push.stderr)
        print(f"ERROR: push of '{a.branch}' to {a.remote} failed — fix auth/remote, then retry.")
        return 1
    sys.stderr.write(push.stderr)  # push prints the compare/MR URL here

    # Preferred: vendor CLI when present.
    if vendor == "github" and shutil.which("gh"):
        r = sh(f'gh pr create --base {a.target} --head {a.branch} '
               f'--title "{a.title}" --body "{a.body}"')
        print(r.stdout.strip() or r.stderr.strip())
        return 0 if r.returncode == 0 else 1
    if vendor == "gitlab" and shutil.which("glab"):
        r = sh(f'glab mr create --source-branch {a.branch} --target-branch {a.target} '
               f'--title "{a.title}" --description "{a.body}"')
        print(r.stdout.strip() or r.stderr.strip())
        return 0 if r.returncode == 0 else 1

    # Fallback: branch is pushed; surface the URL to open the PR/MR.
    if vendor == "github":
        print(f"PR ready (no gh): https://{host}/{path}/pull/new/{a.branch}")
    elif vendor == "gitlab":
        print(f"MR via push-option attempted. If absent: "
              f"https://{host}/{path}/-/merge_requests/new?merge_request%5Bsource_branch%5D={a.branch}")
    else:
        print(f"Branch '{a.branch}' pushed to {a.remote} ({host}). "
              f"Open a PR/MR against '{a.target}' manually.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
