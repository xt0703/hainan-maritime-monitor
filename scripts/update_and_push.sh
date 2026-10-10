#!/usr/bin/env bash
set -euo pipefail

REPO="$HOME/hainan-maritime-monitor"
LOG_DIR="$REPO/logs"
LOG_FILE="$LOG_DIR/crawler.log"

mkdir -p "$LOG_DIR"
cd "$REPO"

echo "===== $(date --iso-8601=seconds) =====" | tee -a "$LOG_FILE"

# Đồng bộ thay đổi từ GitHub trước khi cào.
git pull --rebase origin main 2>&1 | tee -a "$LOG_FILE"

# Kích hoạt môi trường Python.
source "$REPO/.venv/bin/activate"

# Chạy crawler.
python "$REPO/crawler/main.py" 2>&1 | tee -a "$LOG_FILE"

# Chỉ commit nếu dữ liệu thực sự thay đổi.
git add data/notices.json docs/data/notices.json

if git diff --cached --quiet; then
  echo "Không có dữ liệu mới." | tee -a "$LOG_FILE"
  exit 0
fi

git config user.name "hainan-warning-bot"
git config user.email "actions@users.noreply.github.com"

git commit -m "data: update maritime warnings $(date '+%Y-%m-%d %H:%M %Z')" 2>&1 | tee -a "$LOG_FILE"

# Push; nếu remote vừa có thay đổi thì rebase rồi thử lại một lần.
if ! git push origin main 2>&1 | tee -a "$LOG_FILE"; then
  echo "Push lần đầu thất bại, đang pull --rebase và thử lại..." | tee -a "$LOG_FILE"
  git pull --rebase origin main 2>&1 | tee -a "$LOG_FILE"
  git push origin main 2>&1 | tee -a "$LOG_FILE"
fi

echo "Hoàn tất." | tee -a "$LOG_FILE"
