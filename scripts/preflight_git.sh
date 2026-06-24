#!/usr/bin/env bash
# preflight_git.sh — git health check for the OntologyResearch daily auto-run.
#
# Run this FIRST (Step 0). It decides whether the run actually needs file-delete
# permission (the Cowork `allow_cowork_file_delete` tool) to repair git state.
#
# The mounted Working folder blocks deletes by default. We only need that
# permission to clear leftovers from a CRASHED prior run:
#   - a stale  .git/index.lock
#   - a corrupt/unreadable  .git/index
#   - leftover .git/objects/tmp_obj_*  files
# Normal CRLF working-tree modifications NEVER require it, so a clean run should
# skip the permission prompt entirely.
#
# Verdict (final line):
#   "PREFLIGHT: CLEAN"           exit 0  -> do NOT request delete permission; proceed
#   "PREFLIGHT: NEEDS_DELETE …"  exit 1  -> grant permission, then re-run with --fix
#   "PREFLIGHT: FIXED"           exit 0  -> repair done (after --fix)
#   "PREFLIGHT: FIX_FAILED …"    exit 1  -> permission still missing / manual look
#
# Usage:
#   bash scripts/preflight_git.sh          # report only
#   bash scripts/preflight_git.sh --fix    # AFTER permission granted: remove lock,
#                                           # rebuild corrupt index, clear temp objs
set -u
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)" || exit 2   # -> implementation/

FIX=0; [ "${1:-}" = "--fix" ] && FIX=1
reasons=(); paths=()

# 1) stale index.lock (no git process runs in this sandbox => any lock is stale)
if [ -e .git/index.lock ]; then
  reasons+=("stale .git/index.lock"); paths+=(".git/index.lock")
fi
# 2) corrupt / unreadable index (git ls-files reads the index without the lock)
if ! git ls-files >/dev/null 2>&1; then
  reasons+=("unreadable/corrupt .git/index"); paths+=(".git/index")
fi
# 3) leftover temp objects from an interrupted object write
if [ -n "$(find .git/objects -name 'tmp_obj_*' -print -quit 2>/dev/null)" ]; then
  reasons+=("leftover .git/objects/tmp_obj_*"); paths+=(".git/objects/tmp_obj_*")
fi

if [ "${#reasons[@]}" -eq 0 ]; then
  echo "PREFLIGHT: CLEAN"
  exit 0
fi
for r in "${reasons[@]}"; do echo "  - $r"; done

if [ "$FIX" -eq 1 ]; then
  rm -f .git/index.lock
  find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null
  if ! git ls-files >/dev/null 2>&1; then rm -f .git/index && git reset -q; fi
  if git ls-files >/dev/null 2>&1 && [ ! -e .git/index.lock ]; then
    echo "PREFLIGHT: FIXED"; exit 0
  fi
  echo "PREFLIGHT: FIX_FAILED (file-delete permission still needed)"; exit 1
fi

printf 'PREFLIGHT: NEEDS_DELETE'
for p in "${paths[@]}"; do printf ' | %s' "$p"; done
echo
exit 1
