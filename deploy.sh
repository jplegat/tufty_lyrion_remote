#!/bin/sh
# Copy the app onto the badge, then eject so the badge reboots into it.
#
#   ./deploy.sh          badge already in disk mode (double-tap RESET)
#   ./deploy.sh --disk   switch the badge into disk mode over USB first
set -e

VOLUME=/Volumes/TUFTY
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/lyrion_remote"
MENU="$VOLUME/apps/menu/app.py"
# sha1 of firmware v3.1.1's menu/app.py, which badge_menu/app.py is based on
STOCK_MENU=189adb35af4a667e3a88d87267ca7410875ad967

if [ "$1" = "--disk" ] && [ ! -d "$VOLUME/apps" ]; then
  echo "Switching the badge to disk mode..."
  # The request can be lost if the serial port was only just released by an
  # earlier mpremote, so try a few times
  attempt=0
  while [ ! -d "$VOLUME/apps" ] && [ $attempt -lt 3 ]; do
    attempt=$((attempt + 1))
    mpremote exec "import powman; powman.reset_into_msc()" >/dev/null 2>&1 || true
    i=0
    while [ ! -d "$VOLUME/apps" ] && [ $i -lt 15 ]; do sleep 1; i=$((i + 1)); done
  done
fi

if [ ! -d "$VOLUME/apps" ]; then
  echo "TUFTY isn't mounted: double-tap RESET on the badge, or run with --disk" >&2
  exit 1
fi

COPYFILE_DISABLE=1 rsync -rt --delete \
  --exclude '__pycache__' --exclude '.DS_Store' --exclude '._*' \
  "$SRC/" "$VOLUME/apps/lyrion_remote/"

# The badge menu lists apps alphabetically; ours puts this app first. Only
# replace the stock v3.1.1 menu or an earlier copy of ours, so a firmware
# update that changes the menu doesn't get an old one put back over it
if [ -f "$MENU" ] && { [ "$(shasum "$MENU" | cut -d ' ' -f 1)" = "$STOCK_MENU" ] || grep -q '^PINNED = ' "$MENU"; }; then
  COPYFILE_DISABLE=1 cp "$ROOT/badge_menu/app.py" "$MENU"
  echo "Installed the badge menu that lists Lyrion Remote first"
else
  echo "Left the badge menu alone: it isn't the v3.1.1 one badge_menu/app.py is based on" >&2
fi

# macOS still leaves AppleDouble ._ files on the FAT volume, and --exclude
# shields them from --delete, so clear them out explicitly
find "$VOLUME/apps/lyrion_remote" "$VOLUME/apps/menu" -name '._*' -delete
sync
echo "Copied $(ls "$VOLUME/apps/lyrion_remote" | wc -l | tr -d ' ') files to $VOLUME/apps/lyrion_remote"

diskutil eject "$VOLUME" >/dev/null
echo "Ejected, the badge is rebooting"
