#!/usr/bin/env bash
# batch_supervisor.sh — keep the STEPFORGE batch alive until every song in the
# folder is charted. The batch itself is resumable (skips songs whose .ssc
# already exists) and catches per-song EXCEPTIONS, but a hard interpreter crash
# (OOM/segfault on a pathological song) is not caught — so we supervise it.
#
# Guard: if the count of completed songs doesn't advance across MAX_STALL
# consecutive restarts, we stop (a song is hard-crashing the process every time;
# babysitting won't help and we'd loop forever).
set -u

SRC="/Users/fterry/Downloads/fofo-stepmania"
DEST="/Users/fterry/Library/Application Support/ITGmania/Songs"
PACK="FoFoSongs"
MAN="$DEST/$PACK/_batch_manifest.json"
LOG="/tmp/fofo_batch.log"
REPO="/Users/fterry/.foreman/worktrees/FRM-1041"
MAX_RESTARTS=60
MAX_STALL=4

cd "$REPO" || exit 1

done_count() {
  python3 -c "
import json,sys
try:
    d=json.load(open('$MAN'))
    print(sum(1 for v in d.values() if v.get('status')=='done'))
except Exception:
    print(0)
" 2>/dev/null
}

total_songs() {
  ls -1 "$SRC" 2>/dev/null | grep -iE '\.(wav|mp3|ogg|flac|m4a|aac)$' | wc -l | tr -d ' '
}

TOTAL=$(total_songs)
prev=$(done_count)
stall=0
for i in $(seq 1 $MAX_RESTARTS); do
  cur=$(done_count)
  echo "[supervisor] pass $i: $cur/$TOTAL done" >> "$LOG"
  if [ "$cur" -ge "$TOTAL" ]; then
    echo "[supervisor] all $TOTAL songs charted — done." >> "$LOG"
    break
  fi
  if [ "$i" -gt 1 ]; then
    if [ "$cur" -le "$prev" ]; then
      stall=$((stall+1))
      echo "[supervisor] no progress ($prev -> $cur); stall $stall/$MAX_STALL" >> "$LOG"
      if [ "$stall" -ge "$MAX_STALL" ]; then
        echo "[supervisor] STALLED — a song keeps crashing the process. Stopping." >> "$LOG"
        break
      fi
    else
      stall=0
    fi
  fi
  prev=$cur
  BEATFORGE_LLM_MIN_INTERVAL=6 PYTHONPATH=tools python3 -u -m beatforge.batch_stepforge \
     --src "$SRC" --pack "$PACK" --dest "$DEST" >> "$LOG" 2>&1
  echo "[supervisor] batch exited with code $? (pass $i)" >> "$LOG"
done
echo "[supervisor] supervisor loop finished." >> "$LOG"
