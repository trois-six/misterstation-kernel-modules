#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Open (or comment on) the issue tracking a failure, or close it on success.
#
# usage: report-issue.sh open  TITLE BODY_FILE LABEL
#        report-issue.sh close TITLE COMMENT
# Needs GH_TOKEN (issues: write) and GH_REPO.
set -euo pipefail
action=$1 title=$2
existing=$(gh issue list --state open --limit 200 --json number,title \
  --jq ".[] | select(.title == \"$title\") | .number" | head -n1)
case $action in
  open)
    body=$3 label=$4
    gh label create "$label" --color d73a4a --description "Raised by the build workflow" 2>/dev/null || true
    if [ -n "$existing" ]; then
      gh issue comment "$existing" --body-file "$body"
    else
      gh issue create --title "$title" --body-file "$body" --label "$label"
    fi ;;
  close)
    [ -z "$existing" ] || gh issue close "$existing" --reason completed --comment "$3" ;;
  *) echo "unknown action $action" >&2; exit 2 ;;
esac
