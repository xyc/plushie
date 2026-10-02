/* @jsxRuntime classic */
/* @jsx h */
/* @jsxFrag Fragment */
import type { On, PluginOptions, Timer } from 'claude-code'

import type { GrabMessage, GrabProps } from './grab'

/**
 * The plush Clawd above the prompt: frames baked by blender/plush.py, played
 * by swapping one Image's source on a timer, the mood picked by what the
 * main conversation is doing.
 *
 * Only the terminal draws pixels; elsewhere, or in a terminal without an
 * image protocol, the band is left as it was.
 */

const MOODS = ['idle', 'working', 'happy', 'sleepy', 'oops'] as const
type Mood = (typeof MOODS)[number]

type Manifest = {
  fps: number
  columns: number
  rows: number
  moods: Record<Mood, { frames: number; loop: boolean }>
}

type Host = {
  every: (ms: number, fn: () => void) => Timer
  blit: (requestId: string, file: string) => Promise<{ deny?: string }>
  invalidate: () => void
  now: () => Promise<number>
}

const KEY = 'plush'
// A turn shorter than this ends without a celebration: quick answers would
// otherwise make it jump after every message.
const HAPPY_AFTER_MS = 4000
const SLEEP_AFTER_MS = 2 * 60 * 1000

const clamp = (value: number, low: number, high: number) =>
  Math.max(low, Math.min(high, Math.round(value)))

export function register(on: On, options: PluginOptions) {
  const isDragOn = options.drag !== false

  let host: Host | null = null
  let manifest: Manifest | null = null
  let root = ''
  let timer: Timer | null = null

  let requestId: string | null = null
  let isShown = true
  // Set when the terminal draws the Image's alt instead of pixels: the pet
  // stops drawing for the rest of the session.
  let isUnsupported = false

  let mood: Mood = 'idle'
  let frame = 0
  // Turns under way, the main conversation's and its subagents', by turnId.
  const runningTurns = new Set<string>()
  let lastActivityMs = 0

  // The band column of the pet's left edge; null keeps it at the right end.
  let left: number | null = null
  // Where in the pet the pointer took hold, while a drag is under way.
  let grabOffset: number | null = null
  let bandColumns = 0

  const fileOf = (m: Mood, f: number) =>
    `${root}/assets/frames/${m}/${String(f).padStart(3, '0')}.png`

  /** The pet's left column in a band this wide: where it was left, or the right end. */
  const leftIn = (columns: number, petColumns: number) =>
    clamp(left ?? columns - petColumns, 0, Math.max(0, columns - petColumns))

  /** The mood to fall back to once a one-shot mood has played out. */
  const restingMood = (): Mood => (runningTurns.size > 0 ? 'working' : 'idle')

  function setMood(next: Mood) {
    if (next === mood && manifest?.moods[next].loop) {
      return
    }
    mood = next
    frame = 0
  }

  async function tick(nowMs: number) {
    if (!host || !manifest || !requestId || !isShown || isUnsupported) {
      return
    }

    if (mood === 'idle' && nowMs - lastActivityMs > SLEEP_AFTER_MS) {
      setMood('sleepy')
    }

    const { frames, loop } = manifest.moods[mood]
    if (frame >= frames) {
      if (loop) {
        frame = 0
      } else {
        setMood(restingMood())
      }
    }

    const result = await host.blit(requestId, fileOf(mood, frame))
    frame += 1

    if (result.deny && /alt/i.test(result.deny)) {
      isUnsupported = true
      host.invalidate()
    }
  }

  function noteActivity(nowMs: number) {
    lastActivityMs = nowMs
    if (mood === 'sleepy') {
      setMood(restingMood())
    }
  }

  on('session.start', async ($, e, next) => {
    root = $.plugin.root
    const bound: Host = {
      every: (ms, fn) => $.clock.every(ms, fn),
      blit: (id, file) =>
        $.ui.blit({ requestId: id, key: KEY, source: { file, format: 'png' } }),
      invalidate: () => $.ui.invalidate('ui.render'),
      now: () => $.clock.now(),
    }
    host = bound

    try {
      manifest = JSON.parse(
        await $.fs.read(`${root}/assets/frames/manifest.json`),
      ) as Manifest
    } catch {
      manifest = null
    }

    await $.command.register({
      name: 'plushie',
      description: 'Show or hide the plush Clawd above the prompt, or play one of its moods',
      argumentHint: `[${MOODS.join('|')}]`,
    })

    if (manifest && !timer) {
      lastActivityMs = await bound.now()
      const ms = Math.round(1000 / manifest.fps)
      timer = bound.every(ms, () => {
        void bound
          .now()
          .then(tick)
          .catch(() => undefined)
      })
    }

    return next(e)
  })

  on('command.run', { command: 'plushie' }, async ($, e) => {
    const asked = e.args.trim()
    if (asked === '') {
      isShown = !isShown
      host?.invalidate()
      return { text: isShown ? 'Plush Clawd is back' : 'Plush Clawd is napping out of sight' }
    }

    const picked = MOODS.find(m => m === asked)
    if (!picked) {
      return { text: `Plush Clawd knows ${MOODS.join(', ')}` }
    }
    isShown = true
    setMood(picked)
    host?.invalidate()
    return { text: `Plush Clawd is ${picked}` }
  })

  on('turn.start', async ($, e, next) => {
    // The start doesn't say whose turn it is; any turn means work is under way.
    runningTurns.add(e.turnId)
    noteActivity(await $.clock.now())
    setMood('working')
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    runningTurns.delete(e.turnId)
    if (!e.agentId) {
      noteActivity(await $.clock.now())
      if (e.isAborted || e.reason === 'error') {
        setMood('oops')
      } else if (e.durationMs >= HAPPY_AFTER_MS) {
        setMood('happy')
      } else {
        setMood('idle')
      }
    }
    return result
  })

  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    // A refused or failed call in the main conversation gets a wobble; a
    // subagent's stumbles are its own business.
    if (!e.agentId && (result.deny !== undefined || result.isError)) {
      setMood('oops')
    }
    return result
  })

  on('ui.message', { element: 'grab' }, async ($, e, next) => {
    const message = e.data as GrabMessage
    if (!manifest || typeof message?.column !== 'number') {
      return next(e)
    }
    const shownLeft = leftIn(bandColumns, manifest.columns)
    if (message.phase === 'down') {
      grabOffset = message.column - shownLeft
    } else if (grabOffset !== null) {
      left = clamp(message.column - grabOffset, 0, bandColumns - manifest.columns)
      if (message.phase === 'up') {
        grabOffset = null
      }
      $.ui.invalidate('ui.render')
    }
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const below = await next(e)

    const isDrawable =
      e.surface === 'terminal' &&
      manifest !== null &&
      isShown &&
      !isUnsupported &&
      !e.props.hasSurvey &&
      e.props.maxRows >= manifest.rows &&
      e.props.bodyColumns >= manifest.columns + 20

    if (!isDrawable || !manifest) {
      return below
    }

    requestId = e.requestId
    bandColumns = e.props.bodyColumns
    const { Box, Image, Client } = await $.ui.resolve(e)
    const shown = Math.min(frame, manifest.moods[mood].frames - 1)
    const petLeft = leftIn(bandColumns, manifest.columns)
    const grab: GrabProps = {
      left: petLeft,
      columns: manifest.columns,
      rows: manifest.rows,
    }

    // The pet has its own strip; inside it the picture and, on top, the
    // invisible grab region sit at the same column.
    return (
      <Box flexDirection="column">
        {below}
        <Box width={bandColumns} height={manifest.rows}>
          <Box key="pet" position="absolute" left={petLeft} top={0}>
            <Image
              key={KEY}
              source={{ file: fileOf(mood, shown), format: 'png' }}
              columns={manifest.columns}
              rows={manifest.rows}
              alt=" "
            />
          </Box>
          {isDragOn ? (
            <Box position="absolute" left={petLeft} top={0}>
              <Client key="grab" module="./grab.tsx" props={grab} />
            </Box>
          ) : null}
        </Box>
      </Box>
    )
  })
}
