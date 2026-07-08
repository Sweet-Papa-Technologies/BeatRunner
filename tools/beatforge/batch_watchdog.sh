#!/usr/bin/env bash
# batch_watchdog.sh — kill a HUNG batch so the supervisor restarts it.
#
# The supervisor recovers from a batch that EXITS (crash/error) but not from one
# that HANGS (a dead half-open socket after a network drop / laptop sleep blocks
# recv() forever, so the process never exits and no CPU/network moves). This
# watchdog watches the log's modification time: if it hasn't advanced for
# STALL_LIMIT seconds while a batch process is alive, the batch is wedged — kill
# it, and the supervisor's loop will relaunch the next resumable pass.
#
# STALL_LIMIT (900s) is set safely above the worst legitimate quiet stretch: one
# heavy Vertex call (600s timeout) plus the full backoff ladder (5+15+40+90s).
set -u
LOG="/tmp/fofo_batch.log"
STALL_LIMIT=900
CHECK_EVERY=60

while true; do
  sleep "$CHECK_EVERY"
  # stop the watchdog once the supervisor is gone (batch finished/stalled-out)
  pgrep -f batch_supervisor >/dev/null || { echo "[watchdog] supervisor gone; exiting." >> "$LOG"; break; }
  BATCH=$(pgrep -f batch_stepforge | head -1)
  [ -z "$BATCH" ] && continue                      # between passes; nothing to watch
  if [ -f "$LOG" ]; then
    now=$(date +%s)
    mtime=$(stat -f %m "$LOG")
    idle=$(( now - mtime ))
    if [ "$idle" -ge "$STALL_LIMIT" ]; then
      echo "[watchdog] log idle ${idle}s (>= ${STALL_LIMIT}s); batch $BATCH is hung — killing so supervisor restarts." >> "$LOG"
      kill -9 "$BATCH" 2>/dev/null
    fi
  fi
done
