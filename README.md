# plushie

A plush Clawd that lives above the Claude Code prompt and reacts to what
Claude is doing: idles and blinks, wiggles while a turn runs, wobbles when a
tool fails or you interrupt, jumps after a long turn, dozes off when left
alone.

It is a Claude Code mod: frames baked in Blender, played in the terminal by
swapping an `Image`'s source with `$.ui.blit`. Terminals with an image
protocol (Ghostty, kitty) only; elsewhere it stays out of the way.

## Run it

```bash
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir ~/projects/plushie
```

The variable turns mods on where they are still off for the account
(Claude Code before 2.1.287).

- `/plushie` hides or shows it.
- `/plushie idle|working|happy|sleepy|oops` plays a mood.

## Rebake the frames

```bash
blender/sheet.sh idle:0 happy:16          # contact sheet: build/sheet.png
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
  -P blender/plush.py -- render assets/frames
```

`blender/plush.py` holds the model, the fur, the lights and every mood's
motion. Frame counts live in both `MOODS` there and
`assets/frames/manifest.json`; change them together.

## Test

```bash
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin test .
```
