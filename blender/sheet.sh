#!/bin/zsh
# Renders one still per mood:frame and lays them side by side on the
# terminal's dark background: build/sheet.png.
set -e
cd "${0:A:h}/.."
rm -rf build/stills && mkdir -p build/stills
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P blender/plush.py -- stills build/stills "${SCALE:-1}" "$@" >/dev/null
tiles=()
for spec in "$@"; do
  f="build/stills/${spec/:/-}.png"
  magick "$f" -background '#1e1e1e' -flatten -bordercolor '#444' -border 1 "$f.tile.png"
  tiles+=("$f.tile.png")
done
magick "${tiles[@]}" +append build/sheet.png
echo build/sheet.png
