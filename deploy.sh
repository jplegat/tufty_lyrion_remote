#!/bin/sh
# Copy the app onto the badge, then eject so the badge reboots into it.
#
#   ./deploy.sh          badge already in disk mode (double-tap RESET)
#   ./deploy.sh --disk   switch the badge into disk mode over USB first
set -e

VOLUME=/Volumes/TUFTY
SRC="$(cd "$(dirname "$0")" && pwd)/lyrion_remote"

if [ "$1" = "--disk" ] && [ ! -d "$VOLUME/apps" ]; then
  echo "Switching the badge to disk mode..."
  mpremote exec "import powman; powman.reset_into_msc()" >/dev/null 2>&1 || true
  i=0
  while [ ! -d "$VOLUME/apps" ] && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done
fi

if [ ! -d "$VOLUME/apps" ]; then
  echo "TUFTY isn't mounted: double-tap RESET on the badge, or run with --disk" >&2
  exit 1
fi

COPYFILE_DISABLE=1 rsync -rt --delete \
  --exclude '__pycache__' --exclude '.DS_Store' --exclude '._*' \
  "$SRC/" "$VOLUME/apps/lyrion_remote/"
sync
echo "Copied $(ls "$VOLUME/apps/lyrion_remote" | wc -l | tr -d ' ') files to $VOLUME/apps/lyrion_remote"

diskutil eject "$VOLUME" >/dev/null
echo "Ejected, the badge is rebooting"
