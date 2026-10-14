#!/usr/bin/env bash
set -euo pipefail
REPO="${SCS_REPO:-$HOME/hainan-maritime-monitor}"
mkdir -p "$REPO/logs"
cd "$REPO"
exec 9>"$REPO/logs/scs-monitor.lock"
if ! flock -n 9; then echo 'SCS monitor: another run in progress'; exit 0; fi
LOG="$REPO/logs/scs-update.log"
{
  echo "===== $(date --iso-8601=seconds) live update ====="
  git pull --rebase origin main
  source "$REPO/.venv/bin/activate"
  # Keep original Hainan MSA fallback and existing historical notices.
  if ! python crawler/main.py; then
    echo 'WARNING: legacy Hainan crawler failed. Continuing with v2 sources.'
  fi
  python -m scs_monitor.cli update --per-source 22
  git add data/notices.json docs/data/notices.json docs/data/events-*.json \
          docs/data/events-index.json docs/data/stats.json docs/data/health.json \
          docs/data/backfill-progress.json
  if git diff --cached --quiet; then
    echo 'Không có thay đổi dữ liệu.'
    exit 0
  fi
  git config user.name 'hainan-warning-bot'
  git config user.email 'actions@users.noreply.github.com'
  git commit -m "data: SCS monitor update $(date '+%F %H:%M %Z')"
  if ! git push origin main; then
    git pull --rebase origin main
    git push origin main
  fi
  echo 'Đã cập nhật và push dữ liệu lên GitHub.'
} 2>&1 | tee -a "$LOG"
