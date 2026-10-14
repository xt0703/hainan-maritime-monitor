#!/usr/bin/env bash
set -euo pipefail
REPO="${SCS_REPO:-$HOME/hainan-maritime-monitor}"
cd "$REPO"
mkdir -p logs
exec 9>"$REPO/logs/scs-monitor.lock"
if ! flock -n 9; then echo 'SCS monitor: another run in progress'; exit 0; fi
{
  echo "===== $(date --iso-8601=seconds) historical backfill ====="
  git pull --rebase origin main
  source "$REPO/.venv/bin/activate"
  python -m scs_monitor.cli backfill --batch 3 --per-source 15
  git add docs/data/events-*.json docs/data/events-index.json docs/data/stats.json \
          docs/data/health.json docs/data/backfill-progress.json
  if git diff --cached --quiet; then echo 'Không có thay đổi dữ liệu lịch sử.'; exit 0; fi
  git config user.name 'hainan-warning-bot'
  git config user.email 'actions@users.noreply.github.com'
  git commit -m "data: SCS historical backfill $(date '+%F')"
  git push origin main || { git pull --rebase origin main; git push origin main; }
} 2>&1 | tee -a "$REPO/logs/scs-backfill.log"
