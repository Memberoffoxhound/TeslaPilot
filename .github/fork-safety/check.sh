#!/usr/bin/env bash
# TeslaPilot fork-safety allowlist: every file that differs from comma's base under the given paths
# must be listed with its exact base and head blob, so only the reviewed MADS diff passes.
#   check.sh check BASE ALLOWLIST PATH...   fail on any unlisted change
#   check.sh print BASE PATH...             print the allowlist for the current HEAD
set -euo pipefail
mode=$1 base=$2; shift 2
list=""
if [ "$mode" = check ]; then list=$1; shift; fi
bad=0
while read -r f; do
  b=$(git rev-parse -q --verify "$base:$f" || echo -)
  h=$(git rev-parse -q --verify "HEAD:$f" || echo -)
  if [ "$mode" = print ]; then
    echo "$f $b $h"
  elif ! grep -qxF "$f $b $h" "$list"; then
    echo "not allowlisted: $f ($b -> $h)"
    bad=1
  fi
done < <(git diff --name-only "$base" HEAD -- "$@")
exit $bad
