#!/bin/zsh
# Renders one still per clip:frame, lays Clawd over its shadow, and puts them
# side by side on the terminal's dark background: build/sheet.png.
set -e
cd "${0:A:h}/.."
rm -rf build/stills && mkdir -p build/stills
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P blender/plush.py -- stills build/stills "${SCALE:-1}" "$@" >/dev/null
tiles=()
for spec in "$@"; do
  f="build/stills/${spec/:/-}"
  python3 blender/composite.py --still "$f.plush.png" "$f.shadow.png" "$f.png"
  magick "$f.png" -background '#1e1e1e' -flatten -bordercolor '#444' -border 1 "$f.tile.png"
  tiles+=("$f.tile.png")
done
magick "${tiles[@]}" +append build/sheet.png
echo build/sheet.png
