#!/bin/bash
set -euo pipefail

SYNC_SCRIPT="/Users/lucas/working/claude-vector-memory/sync-all-memory.sh"
CRON_LINE="*/10 * * * * ${SYNC_SCRIPT} >/tmp/all-memory-sync.log 2>&1"

chmod +x "$SYNC_SCRIPT"

( crontab -l 2>/dev/null | grep -Fv "$SYNC_SCRIPT" ; echo "$CRON_LINE" ) | crontab -

echo "Installed cron job:"
echo "$CRON_LINE"
echo
echo "Current crontab:"
crontab -l
