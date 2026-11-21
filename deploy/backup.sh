#!/bin/sh
# Daily copy of the live database, kept for 14 days (installed to /etc/cron.daily by setup.sh).
set -e
DIR=/var/lib/serialkoi/backups
mkdir -p "$DIR"
[ -f /var/lib/serialkoi/live.db ] || exit 0
/opt/serialkoi/.venv/bin/python - <<'PY'
import datetime, sqlite3
src = sqlite3.connect("/var/lib/serialkoi/live.db")
dst = sqlite3.connect(f"/var/lib/serialkoi/backups/live-{datetime.date.today()}.db")
src.backup(dst)
dst.close(); src.close()
PY
chown -R serialkoi:serialkoi "$DIR"
find "$DIR" -name 'live-*.db' -mtime +14 -delete
