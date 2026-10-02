# Plushie: ideas and queue

Plush Clawd today has five baked moods (idle, working, happy, sleepy, oops)
picked by turn and tool events, plus `/plushie` to hide it or play a mood.
This doc collects what would make it more fun, the order to build it in, and
how every reaction is switched on and off.

Numbers are stable IDs: chat used 1–13 for the brainstorm, and drag and the
oops fix were added as 14 and 15. Every numbered idea has a section below.

## Queue

| Order | Idea | Needs | Status |
| :-- | :-- | :-- | :-- |
| 1 | [14 · Drag](#14--drag) — sideways; spike passed, now held and drop clips + remembered position | code + 2 clips | queued |
| 2 | [15 · A readable oops](#15--a-readable-oops) | `pose()` change + sweat drop prop, ~36 frames | queued |
| 3 | [2 · Eyes that follow you](#2--eyes-that-follow-you) | 2 eye-direction variants of idle | queued |
| 4 | [4 · Tool props](#4--tool-props) | 4 props, a working variant each | queued |
| 5 | [5 · Subagents as mini Clawds](#5--subagents-as-mini-clawds) | code only | queued |
| 6 | [6 · Stuffed as the context fills](#6--stuffed-as-the-context-fills) | 2 body sizes + a deflate clip | queued |
| 7 | [8 · Kind words make it blush](#8--kind-words-make-it-blush) | blush clip | queued |
| 8 | [1 · Random idle fidgets](#1--random-idle-fidgets) | 4–5 short clips, ~100 frames | queued |

Bake cost is about 6 seconds a frame at 256×192 on the M2 Max, so a 24-frame
clip is ~2.5 minutes.

## Every reaction can be turned off

Each reaction feature is a boolean in the plugin's `userConfig`, default on.
The engine stores it in settings.json, hands it to `register(on, options)`,
and `/config` draws it as a switch. `/plushie on <name>` and
`/plushie off <name>` flip the same setting with `$.config.set`, so there is
one source of truth and two ways to reach it.

What the person writes:

```
/plushie off blush        # stop blushing
/plushie on blush
/plushie features         # list every switch and its state
```

What the manifest declares (one entry per feature):

```json
"userConfig": {
  "blush": {
    "type": "boolean",
    "title": "Blush at kind words",
    "description": "Thanks or praise in a prompt makes Clawd blush.",
    "required": false,
    "default": true
  }
}
```

What the mod reads:

```ts
export function register(on: On, options: PluginOptions) {
  const isOn = (name: Feature) => options[name] !== false
  // ...
  if (isOn('blush') && KIND_WORDS.test(e.text)) setMood('blush')
}
```

A changed option reloads the plugin and `register` runs again, so a toggle
also resets the current mood to idle. That is fine for a pet; anything that
must survive a reload (drag position) lives in `$.store`.

| Switch | Idea |
| :-- | :-- |
| `drag` | [14 · Drag](#14--drag) |
| `eyes` | [2 · Eyes that follow you](#2--eyes-that-follow-you) |
| `toolProps` | [4 · Tool props](#4--tool-props) |
| `miniClawds` | [5 · Subagents as mini Clawds](#5--subagents-as-mini-clawds) |
| `stuffing` | [6 · Stuffed as the context fills](#6--stuffed-as-the-context-fills) |
| `blush` | [8 · Kind words make it blush](#8--kind-words-make-it-blush) |
| `fidgets` | [1 · Random idle fidgets](#1--random-idle-fidgets) |

The five base moods and the oops fix are not switches: they are the pet.
`/plushie` alone still hides the whole thing.

## Queued

### 14 · Drag

Press on Clawd and drag it along the band above the prompt; it dangles while
held, lands with a squash when let go, and stays where it was left, across
sessions. A press without movement is a pat (idea 3, later).

**Why it needs a spike.** The `Image` that shows Clawd takes no pointer
events. The only element that does is `Client`: a region drawn by a module of
the plugin's own, which receives press, move and release (with sub-cell
positions in Ghostty and kitty, and every move after a press, past its edges
too). But a `Client` cannot draw an `Image` — its element table leaves
`Image` and `Raster` out — and it must draw something. So the pointer has to
come from a `Client` laid *over* the picture, and nobody knows yet whether
blank cells drawn over a terminal image hide it.

**The spike answers one question:** with a `Client` stacked on the `Image`
(`position: "absolute"` on a `Box`), does Ghostty still show Clawd, and do
press and move arrive?

- **S1. Overlay.** An absolutely positioned `Box` holding a `Client` the size
  of the pet, drawing one blank `Text` row per cell row. The module forwards
  pointer events to the hooks module with `surface.post`; the hooks module
  moves the pet's column offset and redraws.
- **S2. Grab handle (fallback).** If S1 blanks the picture: a narrow `Client`
  strip beside or under Clawd (`⠿` handle) that drags it. Works anywhere, but
  you grab the handle, not the toy.

How the spike is checked:

1. `claude plugin test`: the tree with the overlay validates on the terminal
   surface, `ui.pointer` drives the `Client`, and a drag moves the pet's
   offset. This proves the plumbing, not the pixels.
2. In a Tart VM, Ghostty running Claude Code with the plugin: capture over VNC
   with and without the overlay, and drag with `vm-input.py --drag`. This is
   the only proof that the picture survives.

**Outcome: S1 works.** Tried by hand in a real terminal (2026-10-02): the
picture stays visible under the grab region and a drag moves Clawd along the
band. The test kit drives the same path (press, move, release, clamped at the
band's ends). Open: Clawd only moves sideways — see
[Vertical room](#vertical-room).

#### Vertical room

The pet's strip is exactly as tall as the pet, so a drag can only slide it
along the bottom. The band above the prompt is the only place a mod draws
that stays on screen; it can't float over the transcript. Ways to give it
height:

- **V1. Lift within the band.** Dragging up raises Clawd and the strip grows
  to hold it, up to the band's limit (`maxRows`: in fullscreen, half the
  terminal less the prompt). Costs transcript rows while lifted; dropping it
  back to the floor gives them back.
- **V2. A pane of its own.** Clawd moves into a `Pane` docked beside the
  transcript (fullscreen, 110+ columns), and roams it freely in both
  directions. The pane takes a column of the screen for as long as it's open,
  and on a narrow terminal it falls back to the band.
- **V3. Sit on a message.** Drop Clawd onto the transcript and it sits on the
  latest message, drawn through that message's `ui.render`, scrolling away
  with it. A message is a separate drawing, so this is a drop target, not a
  drag across the screen.

**Deferred (2026-10-02): sideways only for now.** None of V1–V3 is built;
V1 with Clawd falling back to the floor on release is the likely first pick
when this comes back.

Once it works: two baked clips, **held** (~24 frames: legs dangling, a slight
swing) and **drop** (~16 frames: fall, squash, settle), and the offset kept
in `$.store` under `position`.

### 15 · A readable oops

Today's oops twists Clawd ±14° around its vertical axis for 0.8 s with an 8%
squash and eyes 25% taller. From the three-quarter camera a twist barely
changes the silhouette, and at 16×6 cells the silhouette is all that reads, so
it looks like a frame of idle.

The replacement, ~1.5 s, 36 frames:

| Beat | Time | What happens |
| :-- | :-- | :-- |
| startle | 0–0.25 s | hops back a little, stretches tall, arms fly up |
| wince | 0.25–0.5 s | eyes squeeze almost shut, hard squash (~20%) |
| wobble | 0.5–1.2 s | tips side to side, rolling around the front-back axis, ±18° decaying: a silhouette change |
| settle | 1.2–1.5 s | sags, small sigh |

Plus a **blue sweat drop** beside the head through the wobble: a new shape on
screen reads at this size where a pose tweak doesn't. Frame count changes in
both `MOODS` (blender/plush.py) and the manifest.

### 2 · Eyes that follow you

While you type, Clawd glances down at the prompt; while Claude answers, it
looks up at the transcript. Two eye-direction variants of idle (pupils down,
pupils up), the beads moved rather than redrawn.

Triggers to verify against the declarations: whether `prompt.edit` fires per
keystroke (look down while it does, back to centre after a pause), and
`turn.step` while an answer streams (look up). Switch: `eyes`.

### 4 · Tool props

During a tool call Clawd holds a prop matching the tool, set in `tool.call`
before `next(e)` and cleared after it returns:

| Tools | Prop |
| :-- | :-- |
| `Read`, `Grep`, `Glob` | magnifying glass |
| `Edit`, `Write`, `NotebookEdit` | knitting needles |
| `Bash` | tiny keyboard |
| `WebFetch`, `WebSearch` | binoculars |

Four props modelled in Blender, each a variant of the working clip
(4 × 24 = 96 frames). Calls under 300 ms skip the prop, or Clawd would flicker
through props on a burst of reads. Switch: `toolProps`.

### 5 · Subagents as mini Clawds

Each running subagent gets a half-size Clawd beside the main one, playing the
working clip; when its agent finishes it waddles off and disappears. One
`Image` per agent, keyed by agent id, in a box half the size (8×3 cells), the
same frames — nothing to bake. At most three on screen; a fourth agent shows
as `+1` text.

Start: `agent.spawn`. End: `turn.complete` carrying that `agentId`.
Switch: `miniClawds`.

### 6 · Stuffed as the context fills

Clawd gets rounder as the context window fills, read from
`$.session.usage()` after each turn: normal under 50%, **plump** 50–80%,
**stuffed** above 80%. Compaction (`session.compact`) plays a **deflate** clip
— a sigh down to normal size.

Bake: idle and working at the two bigger sizes, (48 + 24) × 2 = 144 frames,
plus deflate ~24. The other moods stay normal size: a stuffed Clawd that
jumps at normal size for a second reads as a squash, not a bug.
Switch: `stuffing`.

### 8 · Kind words make it blush

"thanks", "thank you", "good job", "nice", "love it" in a submitted prompt
(`prompt.submit`) makes Clawd blush: pink felt cheeks fade in, a shy wiggle,
~32 frames. Matched on whole words, case-insensitive. Switch: `blush`.

### 1 · Random idle fidgets

Every 15–40 s idle plays a short random clip instead of the breathing loop:
look around, scratch, yawn, hop, glance at the prompt. The biggest single gain
in seeming alive — a two-second loop is how a pet starts reading as a GIF.

## Later

Kept for when the queue is done; not designed yet.

### 3 · Pats

A press without movement is a pat: hearts and a wiggle. Shares the pointer
path with drag.

### 7 · Mood streaks

Three failures in a row and it faceplants; tests passing again after
failures (a test command's exit code) earn a victory dance.

### 9 · Speech bubbles

A short line beside it per event ("nope.md isn't real", "zzz"), hand-written.
A line written by a small model is possible but costs a call each, so it
would be opt-in.

### 10 · Sounds

A squeak on a pat, a boing on the happy jump, a snore while asleep, with
`$.audio.play`. Off by default.

### 11 · It eats commits

Munches when a `git commit` succeeds through Bash; looks hungry when work has
sat uncommitted a long time. Kept across sessions in `$.store`.

### 12 · Release party

Confetti on a successful `make release`, the oops wobble on a failed one.

### 13 · Hats by date

Pumpkin hat until Halloween, Santa hat in December, nightcap after 11 pm, a
stretch on the day's first session. One model change per hat, then a rebake.
