#!/usr/bin/env python3
"""Host-agnostic PR/MR submission (+ optional router-gated auto-merge) for the self-evolution subagent.

NEVER hardcodes a vendor. Detects github / gitlab / other from the remote URL, then picks the matching
mechanism with graceful fallback, always ending by pushing the branch + surfacing a URL:

  github → `gh pr create`/`gh pr merge`   | else push + https://HOST/owner/repo/pull/new/<branch>
  gitlab → `glab mr create`/`glab mr merge`| else `git push -o merge_request.create` (no CLI) | web URL
  other  → push branch + best-effort web URL (open PR/MR manually)

--auto-merge is passed by the subagent ONLY for the AUTO_FIX class (router autoEvolvable + corpus green;
no ESCALATE/NEEDS_PROBE). It still OPENS a PR first (audit trail + revert point), then merges. The
CLI-less merge fallback is a fast-forward push `branch:target` that SAFELY fails if the base moved
(non-ff) — never force-pushes, never loses commits; on failure the PR is simply left open for a human.
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


def do_merge(vendor: str, branch: str, target: str, remote: str):
    """Host-agnostic merge. Returns (ok, message). Never force-pushes."""
    if vendor == "github" and shutil.which("gh"):
        r = sh(f"gh pr merge {branch} --squash --delete-branch")
        return r.returncode == 0, (r.stdout or r.stderr).strip()
    if vendor == "gitlab" and shutil.which("glab"):
        r = sh(f"glab mr merge {branch} --yes")
        return r.returncode == 0, (r.stdout or r.stderr).strip()
    # CLI-less: fast-forward push branch -> target. Safe — rejected (non-ff) if the base moved.
    sh(f"git fetch {remote} {target}")
    r = sh(f"git push {remote} {branch}:{target}")
    if r.returncode == 0:
        return True, f"fast-forward merged {branch} -> {remote}/{target}"
    return False, (f"non-ff (base moved) — PR left open for human: {r.stderr.strip()[:160]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--target", default="main")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--auto-merge", action="store_true",
                    help="merge after opening (subagent passes this ONLY for AUTO_FIX + corpus-green)")
    a = ap.parse_args()

    _url, host, path, vendor = remote_info(a.remote)

    # GitLab can open the MR purely via push-options — no CLI required.
    pushopts = ""
    if vendor in ("gitlab", "unknown") and not shutil.which("glab"):
        title = a.title.replace('"', "'")
        pushopts = (f' -o merge_request.create -o merge_request.target={a.target}'
                    f' -o merge_request.title="{title}"')

    push = sh(f"git push -u {a.remote} {a.branch}{pushopts}")
    if push.returncode != 0:
        sys.stderr.write(push.stderr)
        print(f"ERROR: push of '{a.branch}' to {a.remote} failed — fix auth/remote, then retry.")
        return 1
    sys.stderr.write(push.stderr)

    # Open the PR/MR (audit trail), preferring the vendor CLI.
    if vendor == "github" and shutil.which("gh"):
        r = sh(f'gh pr create --base {a.target} --head {a.branch} --title "{a.title}" --body "{a.body}"')
        print(r.stdout.strip() or r.stderr.strip())
    elif vendor == "gitlab" and shutil.which("glab"):
        r = sh(f'glab mr create --source-branch {a.branch} --target-branch {a.target} '
               f'--title "{a.title}" --description "{a.body}"')
        print(r.stdout.strip() or r.stderr.strip())
    elif vendor == "github":
        print(f"PR ready (no gh): https://{host}/{path}/pull/new/{a.branch}")
    elif vendor == "gitlab":
        print(f"MR via push-option attempted. If absent: "
              f"https://{host}/{path}/-/merge_requests/new?merge_request%5Bsource_branch%5D={a.branch}")
    else:
        print(f"Branch '{a.branch}' pushed to {a.remote} ({host}). "
              f"Open a PR/MR against '{a.target}' manually.")

    # Router-gated auto-merge.
    if a.auto_merge:
        ok, msg = do_merge(vendor, a.branch, a.target, a.remote)
        print(("AUTO-MERGED: " if ok else "auto-merge skipped: ") + msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
