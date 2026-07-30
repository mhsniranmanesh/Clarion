#!/usr/bin/env bash
#
# Regenerates the screenshots in docs/media/ from the running app.
#
# The README's screenshots are captured from the real app, not mocked, which
# means they go stale the moment the UI changes and nothing tells you. Run this
# after any visible change to src/App.svelte and commit the result.
#
#   npm run tauri:dev &          # in one terminal, wait for the window
#   ./scripts/capture-screenshots.sh
#
# Requires: macOS, and Screen Recording + Accessibility permission for whichever
# terminal you run it from (System Settings → Privacy & Security). Without them
# screencapture silently returns a desktop image instead of the window, and the
# clicks below do nothing — check the output before committing it.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_ROOT/docs/media"
PROCESS="clarion"

# The settings view scrolls. Rather than drive a scrollbar, the window is grown
# tall enough to show the whole pane in one frame, then restored.
# TALL_H is a request, not a guarantee — macOS clamps it to the usable screen
# height, so the settings shot is as tall as the display allows.
NORMAL_W=400 NORMAL_H=500
TALL_H=900
ORIGIN_X=556 ORIGIN_Y=80

mkdir -p "$OUT"

if ! pgrep -qf "target/debug/$PROCESS" && ! pgrep -qx "$PROCESS"; then
  echo "Clarion is not running. Start it with: npm run tauri:dev" >&2
  exit 1
fi

app () { osascript -e "tell application \"System Events\" to tell process \"$PROCESS\" to $1"; }

geometry () { app "get {item 1 of (get position of window 1), item 2 of (get position of window 1), item 1 of (get size of window 1), item 2 of (get size of window 1)}" | tr -d ' ' | tr ',' ' '; }

# Nav is three equal buttons along the bottom bar: 0=Record 1=History 2=Settings
nav () {
  read -r x y w h < <(geometry)
  app "click at {$(( x + w/6 + (w/3) * $1 )), $(( y + h - 27 ))}" >/dev/null
  sleep 1.5
}

capture () {
  read -r x y w h < <(geometry)
  screencapture -x -R"${x},${y},${w},${h}" "$OUT/$1.png"
  echo "  wrote docs/media/$1.png (${w}x${h} points)"
}

app "set frontmost to true" >/dev/null
sleep 1
app "set position of window 1 to {$ORIGIN_X, $ORIGIN_Y}" >/dev/null
app "set size of window 1 to {$NORMAL_W, $NORMAL_H}" >/dev/null
sleep 0.5

# The first click after focusing is swallowed by window activation, so the nav
# helper is called once before it matters.
nav 0

echo "Capturing..."
nav 0 && capture record
nav 1 && capture history

nav 2
app "set size of window 1 to {$NORMAL_W, $TALL_H}" >/dev/null
sleep 1
capture settings
app "set size of window 1 to {$NORMAL_W, $NORMAL_H}" >/dev/null

echo "Done. Review the images before committing — a permissions failure looks"
echo "like a successful run but produces the wrong picture."
