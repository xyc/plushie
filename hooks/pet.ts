/**
 * What Clawd is doing and which frame it shows: the mood picked from what is
 * under way, the one-off clips that play over it, the variant of a clip a
 * reaction asks for, and the mini Clawds standing in for subagents.
 *
 * No engine here: register.tsx feeds it events and the time, and draws and
 * blits what it says.
 */

export const FEATURES = ['drag', 'pats', 'toolProps', 'miniClawds', 'stuffing', 'blush', 'fidgets', 'sounds'] as const
export type Feature = (typeof FEATURES)[number]

export type Manifest = {
  fps: number
  columns: number
  rows: number
  clips: Record<string, { frames: number; loop: boolean }>
}

/** Whether parsed JSON is a manifest this mod can play: a frames folder from
 * an older bake has another shape, and drawing from it would throw on every
 * render. */
export function isManifest(value: unknown): value is Manifest {
  if (typeof value !== 'object' || value === null) {
    return false
  }
  const m = value as Record<string, unknown>
  if (typeof m.fps !== 'number' || typeof m.columns !== 'number' || typeof m.rows !== 'number') {
    return false
  }
  if (typeof m.clips !== 'object' || m.clips === null || !('idle' in m.clips)) {
    return false
  }
  return Object.values(m.clips as Record<string, unknown>).every(c => {
    const clip = c as Record<string, unknown> | null
    return typeof clip?.frames === 'number' && clip.frames > 0 && typeof clip.loop === 'boolean'
  })
}

export type Prop = 'magnifier' | 'needles' | 'keyboard' | 'binoculars'
export type Size = 'normal' | 'plump' | 'stuffed'

export const PROP_FOR_TOOL: Record<string, Prop> = {
  Read: 'magnifier',
  Grep: 'magnifier',
  Glob: 'magnifier',
  Edit: 'needles',
  Write: 'needles',
  NotebookEdit: 'needles',
  Bash: 'keyboard',
  WebFetch: 'binoculars',
  WebSearch: 'binoculars',
}

export const sizeFor = (percent: number): Size =>
  percent >= 80 ? 'stuffed' : percent >= 50 ? 'plump' : 'normal'

const SLEEP_AFTER_MS = 2 * 60 * 1000
// Every call shows its prop at least this long: reads and edits finish in
// milliseconds and would otherwise never show one, and a burst of them shows
// one steady prop instead of a flicker.
const PROP_HOLD_MS = 1500
const MAX_MINIS = 3
// Frames a finished subagent's mini spends walking off before it goes.
export const LEAVE_FRAMES = 16
// How long Clawd idles between fidgets, picked fresh each time.
const FIDGET_MIN_MS = 15_000
const FIDGET_MAX_MS = 40_000

// Which one-off clip may cut another short: a higher number wins, an equal
// one restarts. A clip played by hand outranks them all.
const PRIORITY: Record<string, number> = {
  fidget: 0,
  pat: 1,
  blush: 1,
  happy: 2,
  drop: 2,
  deflate: 2,
  oops: 3,
}
const BY_HAND = 10

/** The mood a clip belongs to: `idle-stuffed` is idle, stuffed. */
export const moodOf = (clip: string) => clip.split('-')[0] ?? clip

type OneOff = { clip: string; serial: number; length: number; priority: number }

export type Mini = { id: string; frame: number; leaving: number | null }

export class Pet {
  readonly runningTurns = new Set<string>()
  lastActivityMs = 0
  isHeld = false
  size: Size = 'normal'

  clip = 'idle'
  frame = 0
  readonly minis: Mini[] = []
  extraMinis = 0

  private readonly tools = new Map<string, { prop: Prop; startMs: number; isDone: boolean }>()
  private oneOff: OneOff | null = null
  private serial = 0
  private playing = ''
  private nextFidgetMs: number | null = null

  constructor(
    private readonly manifest: Manifest,
    private readonly isOn: (feature: Feature) => boolean,
    // Told each time a different clip starts (not when a variant of the same
    // mood takes over mid-loop): where the sounds hang off.
    private readonly onStart: (clip: string) => void = () => {},
  ) {}

  has(clip: string) {
    return clip in this.manifest.clips
  }

  /** Every clip there are frames for, the names `/plushie <reaction>` takes. */
  clipNames() {
    return Object.keys(this.manifest.clips)
  }

  framesOf(clip: string) {
    return this.manifest.clips[clip]?.frames ?? 1
  }

  /** The frame of the current clip's files to show. */
  fileFrame() {
    return this.frame % this.framesOf(this.clip)
  }

  /**
   * Plays a clip once over whatever is running, unless a stronger one is
   * playing. By hand, a looping clip runs for at least three seconds so it can
   * be seen.
   */
  play(clip: string, isByHand = false) {
    if (!this.has(clip)) {
      return false
    }
    const priority = isByHand ? BY_HAND : (PRIORITY[moodOf(clip)] ?? 1)
    if (this.oneOff && this.oneOff.priority > priority) {
      return false
    }
    const frames = this.framesOf(clip)
    const length = isByHand && this.manifest.clips[clip]?.loop ? Math.max(frames, 3 * this.manifest.fps) : frames
    this.serial += 1
    this.oneOff = { clip, serial: this.serial, length, priority }
    return true
  }

  toolStarted(id: string, prop: Prop, nowMs: number) {
    this.tools.set(id, { prop, startMs: nowMs, isDone: false })
  }

  toolEnded(id: string) {
    const call = this.tools.get(id)
    if (call) {
      call.isDone = true
    }
  }

  spawnMini(id: string) {
    if (this.minis.filter(m => m.leaving === null).length >= MAX_MINIS) {
      this.extraMinis += 1
      return
    }
    this.minis.push({ id, frame: this.minis.length * 7, leaving: null })
  }

  finishMini(id: string) {
    const mini = this.minis.find(m => m.id === id)
    if (mini) {
      mini.leaving = 0
    } else if (this.extraMinis > 0) {
      this.extraMinis -= 1
    }
  }

  /** Settles which clip shows now; a change of mood starts it from its first frame. */
  sync(nowMs: number) {
    this.fidget(nowMs)
    let key: string
    let clip: string
    if (this.isHeld && this.has('held')) {
      key = 'held'
      clip = 'held'
    } else if (this.oneOff) {
      key = `once:${this.oneOff.serial}`
      clip = this.oneOff.clip
    } else {
      key =
        this.runningTurns.size > 0
          ? 'working'
          : nowMs - this.lastActivityMs > SLEEP_AFTER_MS
            ? 'sleepy'
            : 'idle'
      clip = this.variantOf(key, nowMs)
    }

    if (!this.has(clip)) {
      clip = this.has(moodOf(clip)) ? moodOf(clip) : 'idle'
    }
    // Variants of one mood share a length, so switching between them (idle to
    // idle-stuffed) carries on from the same frame instead of jumping back.
    const isSameMood = key === this.playing && this.framesOf(clip) === this.framesOf(this.clip)
    if (!isSameMood) {
      this.frame = 0
    }
    if (key !== this.playing) {
      this.onStart(clip)
    }
    this.playing = key
    this.clip = clip
  }

  /** Steps one frame on; returns whether the band must be drawn again. */
  advance() {
    this.frame += 1
    if (this.oneOff && this.playing === `once:${this.oneOff.serial}` && this.frame >= this.oneOff.length) {
      this.oneOff = null
    }

    let isRedrawn = false
    for (const mini of this.minis) {
      mini.frame += 1
      if (mini.leaving !== null) {
        mini.leaving += 1
        isRedrawn = true
      }
    }
    const before = this.minis.length
    this.minis.splice(0, this.minis.length, ...this.minis.filter(m => m.leaving === null || m.leaving < LEAVE_FRAMES))
    return isRedrawn || this.minis.length !== before
  }

  /**
   * Now and then an idle Clawd plays a random fidget. Anything else under way
   * (a turn, a hold, sleep) cuts a fidget short and puts the next one off.
   */
  private fidget(nowMs: number) {
    const isIdle =
      !this.isHeld && this.runningTurns.size === 0 && nowMs - this.lastActivityMs <= SLEEP_AFTER_MS
    if (this.oneOff && moodOf(this.oneOff.clip) === 'fidget' && !isIdle) {
      this.oneOff = null
    }
    if (!this.isOn('fidgets') || !isIdle || this.oneOff) {
      this.nextFidgetMs = null
      return
    }
    if (this.nextFidgetMs === null) {
      this.nextFidgetMs = nowMs + FIDGET_MIN_MS + Math.random() * (FIDGET_MAX_MS - FIDGET_MIN_MS)
      return
    }
    if (nowMs >= this.nextFidgetMs) {
      const fidgets = Object.keys(this.manifest.clips).filter(clip => moodOf(clip) === 'fidget')
      const picked = fidgets[Math.floor(Math.random() * fidgets.length)]
      if (picked) {
        this.play(picked)
      }
      this.nextFidgetMs = null
    }
  }

  private variantOf(mood: string, nowMs: number) {
    if (mood === 'working') {
      if (this.isOn('toolProps')) {
        let latest: { prop: Prop; startMs: number } | null = null
        for (const [id, call] of this.tools) {
          if (call.isDone && nowMs - call.startMs >= PROP_HOLD_MS) {
            this.tools.delete(id)
          } else if (!latest || call.startMs > latest.startMs) {
            latest = call
          }
        }
        if (latest) {
          return `working-${latest.prop}`
        }
      }
      if (this.isOn('stuffing') && this.size !== 'normal') {
        return `working-${this.size}`
      }
    }
    if (mood === 'idle') {
      if (this.isOn('stuffing') && this.size !== 'normal') {
        return `idle-${this.size}`
      }
    }
    return mood
  }
}
