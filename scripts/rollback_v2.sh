#!/usr/bin/env bash
set -euo pipefail
REPO="${SCS_REPO:-$HOME/hainan-maritime-monitor}"
BACKUP="${1:-}"
if [[ -z "$BACKUP" ]]; then
  BACKUP="$(find "$REPO/backups" -mindepth 1 -maxdepth 1 -type d -name 'scs-v2-*' -print 2>/dev/null | sort -r | head -1)"
fi
if [[ -z "$BACKUP" || ! -f "$BACKUP/docs/app.js" || ! -f "$BACKUP/docs/index.html" ]]; then
  echo 'Không tìm thấy backup v2 hợp lệ. Truyền đường dẫn thư mục backup vào lệnh.' >&2
  exit 2
fi
if [[ ! -f "$BACKUP/systemd/hainan-monitor.service" ]]; then
  echo 'Backup thiếu hainan-monitor.service; không tự động phục hồi để tránh cấu hình sai.' >&2
  exit 2
fi
systemctl --user disable --now hainan-monitor.timer scs-backfill.timer 2>/dev/null || true
systemctl --user stop hainan-monitor.service scs-backfill.service 2>/dev/null || true
cp "$BACKUP/docs/index.html" "$BACKUP/docs/app.js" "$BACKUP/docs/style.css" "$REPO/docs/"
if [[ -f "$BACKUP/update_and_push.sh" ]]; then
  cp "$BACKUP/update_and_push.sh" "$REPO/scripts/update_and_push.sh"
  chmod +x "$REPO/scripts/update_and_push.sh"
fi
cp "$BACKUP/systemd/hainan-monitor.service" "$HOME/.config/systemd/user/hainan-monitor.service"
systemctl --user daemon-reload
systemctl --user enable --now hainan-monitor.timer
printf '\nĐã khôi phục giao diện và timer v1 từ: %s\n' "$BACKUP"
printf '%s\n' 'Không xóa dữ liệu gốc hay SQLite. Nếu đã push giao diện v2, commit + push các file docs đã khôi phục để đưa web công khai về v1.'
