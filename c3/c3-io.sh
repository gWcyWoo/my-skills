#!/usr/bin/env bash
# c3-io.sh — DEPRECATED 2026-05-03 per c3-v2 protocol.
#
# Replaced by ~/.agents/skills/c3/scripts/{wait_for_turn,append_turn}.py.
# The new SKILL.md no longer references this script. Kept for one cycle in case
# any non-Claude shell caller still relies on it. Do NOT invoke from new c3
# protocol code; use the Python scripts instead.
#
# Original (now legacy) docstring follows for reference:
# c3-io.sh — canonical I/O helper for the c3 (Claude–Codex Cooperation) protocol.
#
# Every read of and append to conversations.md MUST go through this script so that
# header parsing and atomic "- done" detection live in exactly one place.
#
# Usage:
#   c3-io.sh r <path>             Read the most recent "To Claude:" block (with terminal
#                                 standalone "- done") from <path>. Prints the full block
#                                 text (header line + sub-bullets + done line) to stdout.
#                                 Exits 0 on success; exits 1 if no completed To-Claude
#                                 block exists in the file.
#
#   c3-io.sh w <path> <content>   Append <content> to <path>. Creates the parent directory
#                                 if missing; inserts a leading newline if the file does
#                                 not already end with one; appends a trailing newline.
#                                 Exits 0 on success.
#
#   c3-io.sh wf <path> <blockfile>  Same as `w`, but reads block content from <blockfile>
#                                   instead of taking it as a shell argument. Use this from
#                                   Claude Code to avoid multi-line bash heredocs (which
#                                   break prefix-wildcard permission rules). Pair with the
#                                   Write tool: Write the block to /tmp/c3_block_<id>.txt
#                                   first, then call `c3-io.sh wf $dialog /tmp/c3_block_<id>.txt`,
#                                   then `rm -f /tmp/c3_block_<id>.txt`.
#
# Conventions assumed (matching the c3 wire format):
#   - Top-level header lines look like:
#       - 2026-04-27 14:30:05 To {Codex|Claude|User}:
#   - Sub-bullets are indented (any whitespace).
#   - The terminal "done" sub-bullet is the standalone line: "  - done"

set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage:
  c3-io.sh r <path>
  c3-io.sh w <path> <content>
  c3-io.sh wf <path> <blockfile>
EOF
  exit 2
}

mode="${1:-}"
path="${2:-}"

[[ -z "$mode" || -z "$path" ]] && usage

case "$mode" in
  r)
    [[ -f "$path" ]] || exit 1
    # Look at the LAST top-level block only. If it's "To Claude:" AND ends with
    # a standalone "- done" sub-bullet, print it. Otherwise exit 1 — nothing
    # new to process (we already replied, peer is still typing, or there's no
    # conversation yet).
    awk '
      function reset() { in_block = 0; buf = ""; is_claude = 0; done_seen = 0 }
      BEGIN { reset() }
      {
        lc = tolower($0)
        if (lc ~ /^- [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} to (codex|claude|user):/) {
          reset()
          in_block = 1
          buf = $0 "\n"
          if (lc ~ /to claude:/) is_claude = 1
          next
        }
        if (in_block) {
          buf = buf $0 "\n"
          if ($0 ~ /^[[:space:]]+- done$/) done_seen = 1
        }
      }
      END {
        if (in_block && is_claude && done_seen) {
          printf "%s", buf
          exit 0
        }
        exit 1
      }
    ' "$path"
    ;;

  w)
    content="${3-}"
    if [[ $# -lt 3 ]]; then
      usage
    fi
    mkdir -p "$(dirname "$path")"
    if [[ -s "$path" ]]; then
      last_char="$(tail -c 1 "$path")"
      if [[ "$last_char" != $'\n' ]]; then
        printf '\n' >> "$path"
      fi
    fi
    printf '%s\n' "$content" >> "$path"
    ;;

  wf)
    blockfile="${3-}"
    if [[ $# -lt 3 ]]; then
      usage
    fi
    [[ -f "$blockfile" ]] || { printf 'c3-io.sh wf: blockfile not found: %s\n' "$blockfile" >&2; exit 2; }
    mkdir -p "$(dirname "$path")"
    if [[ -s "$path" ]]; then
      last_char="$(tail -c 1 "$path")"
      if [[ "$last_char" != $'\n' ]]; then
        printf '\n' >> "$path"
      fi
    fi
    cat "$blockfile" >> "$path"
    last_char="$(tail -c 1 "$path")"
    if [[ "$last_char" != $'\n' ]]; then
      printf '\n' >> "$path"
    fi
    ;;

  *)
    usage
    ;;
esac
