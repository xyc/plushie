#!/bin/zsh
# Renders the given mood:frame stills and stacks them on the terminal's dark
# background over a mid grey, where a shadow's shape is easiest to judge:
# build/compare.png.
set -e
cd "${0:A:h}/.."
SCALE=${SCALE:-2} blender/sheet.sh "$@" >/dev/null
greys=()
for spec in "$@"; do
  f="build/stills/${spec/:/-}.png"
  magick "$f" -background '#8a8a8a' -flatten -bordercolor '#444' -border 1 "$f.grey.png"
  greys+=("$f.grey.png")
done
magick "${greys[@]}" +append build/sheet-grey.png
magick build/sheet.png build/sheet-grey.png -append build/compare.png
echo build/compare.png
