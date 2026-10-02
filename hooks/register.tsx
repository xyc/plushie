/* @jsxRuntime classic */
/* @jsx h */
/* @jsxFrag Fragment */
import type { EngineInterface, On, PluginOptions, RenderElement } from 'claude-code'

import type { GrabMessage, GrabProps } from './grab'
import { FEATURES, LEAVE_FRAMES, PROP_FOR_TOOL, Pet, isManifest, moodOf, sizeFor } from './pet'
import type { Feature, Manifest } from './pet'

/**
 * The plush Clawd above the prompt: frames baked by blender/plush.py, played
 * by swapping one Image's source on a timer, the clip picked by what the
 * main conversation is doing (pet.ts).
 *
 * Only the terminal draws pixels; elsewhere, or in a terminal without an
 * image protocol, the band is left as it was. Every reaction beyond the base
 * moods is a `userConfig` switch, on unless turned off.
 */

type Host = {
  blit: (requestId: string, key: string, file: string) => Promise<{ deny?: string }>
  invalidate: () => void
  now: () => Promise<number>
  sound: (name: string) => void
}

/** Everything one load of the plugin keeps between events. */
type Plushie = {
  isOn: (feature: Feature) => boolean
  host: Host | null
  manifest: Manifest | null
  pet: Pet | null
  root: string
  starting: Promise<void> | null
  requestId: string | null
  isShown: boolean
  // Set when the terminal draws the Image's alt instead of pixels: the pet
  // stops drawing for the rest of the session.
  isUnsupported: boolean
  // The band column of the pet's left edge; null keeps it at the right end.
  left: number | null
  bandColumns: number
  // The size the pet is drawn at: the manifest's, or less when the band is short.
  petColumns: number
  // The pet Image's key, which changes with its size: an Image drawn again at
  // another size keeps its old placement in the terminal and is clipped, so a
  // new size gets a new Image.
  petKey: string
  // A press on the pet: where in it the pointer took hold, and whether it has
  // moved yet (a press that never moves is a pat).
  grab: { offset: number; downColumn: number; isMoved: boolean } | null
}

const KEY = 'plush'
// A turn shorter than this ends without a celebration: quick answers would
// otherwise make it jump after every message.
const HAPPY_AFTER_MS = 4000
const KIND_WORDS =
  /\b(thanks|thank you|thx|good job|great job|nice work|well done|love it|love you|awesome|you rock)\b/i

// The moods with a sound, by the name of their file in assets/sounds; the
// rest (idle, working, the fidgets) stay quiet, or Clawd would never stop.
const SOUNDS = new Set(['pat', 'happy', 'oops', 'blush', 'held', 'drop', 'deflate', 'sleepy'])
const SOUND_GAIN = 0.6
// Below this many rows Clawd is too small to read and isn't drawn at all.
const MIN_ROWS = 4

const clamp = (value: number, low: number, high: number) =>
  Math.max(low, Math.min(high, Math.round(value)))

const fileOf = (s: Plushie, clip: string, frame: number) =>
  `${s.root}/assets/frames/${clip}/${String(frame).padStart(3, '0')}.png`

/** The pet's left column in a band this wide: where it was left, or the right end. */
const leftIn = (s: Plushie, columns: number, petColumns: number) =>
  clamp(s.left ?? columns - petColumns, 0, Math.max(0, columns - petColumns))

/**
 * Binds to the engine once per load. A session start does it; so does the
 * first drawing, since a plugin reloaded by a settings change sees no
 * session start.
 */
function start($: EngineInterface, s: Plushie) {
  s.starting ??= (async () => {
    s.root = $.plugin.root
    const host: Host = {
      blit: (id, key, file) => $.ui.blit({ requestId: id, key, source: { file, format: 'png' } }),
      invalidate: () => $.ui.invalidate('ui.render'),
      now: () => $.clock.now(),
      sound: name => {
        if (s.isOn('sounds')) {
          void $.audio.play({ asset: `assets/sounds/${name}.wav` }, { gain: SOUND_GAIN }).catch(() => undefined)
        }
      },
    }
    s.host = host

    let parsed: unknown
    try {
      parsed = JSON.parse(await $.fs.read(`${s.root}/assets/frames/manifest.json`))
    } catch {
      return
    }
    if (!isManifest(parsed)) {
      $.ui.log('plushie: assets/frames/manifest.json is not a manifest this version can play; rebake the frames')
      return
    }
    const manifest: Manifest = parsed
    s.manifest = manifest
    s.pet = new Pet(manifest, s.isOn, clip => {
      const mood = moodOf(clip)
      if (SOUNDS.has(mood)) {
        host.sound(mood)
      }
    })
    s.pet.lastActivityMs = await host.now()

    const saved = await $.store.get('left').catch(() => undefined)
    s.left = typeof saved === 'number' ? saved : null

    await $.command
      .register({
        name: 'plushie',
        description: 'Show or hide the plush Clawd, play one of its reactions, or turn a switch on or off',
        argumentHint: '[happy | oops | pat | blush | sleepy | … | list | on <switch> | off <switch>]',
      })
      .catch(() => undefined)

    $.clock.every(Math.round(1000 / manifest.fps), () => {
      void tick(s).catch(() => undefined)
    })
  })()
  return s.starting
}

async function tick(s: Plushie) {
  const { host, pet, requestId } = s
  if (!host || !pet || !requestId || !s.isShown || s.isUnsupported) {
    return
  }
  pet.sync(await host.now())

  const blits = [host.blit(requestId, s.petKey, fileOf(s, pet.clip, pet.fileFrame()))]
  const working = pet.framesOf('working')
  for (const mini of pet.minis) {
    blits.push(host.blit(requestId, `mini-${mini.id}`, fileOf(s, 'working', mini.frame % working)))
  }
  const [main] = await Promise.all(blits)

  if (main?.deny && /alt/i.test(main.deny)) {
    s.isUnsupported = true
    host.invalidate()
    return
  }
  if (pet.advance()) {
    host.invalidate()
  }
}

async function noteActivity($: EngineInterface, s: Plushie) {
  if (s.pet) {
    s.pet.lastActivityMs = await $.clock.now()
  }
}

export function register(on: On, options: PluginOptions) {
  const s: Plushie = {
    isOn: feature => options[feature] !== false,
    host: null,
    manifest: null,
    pet: null,
    root: '',
    starting: null,
    requestId: null,
    isShown: true,
    isUnsupported: false,
    left: null,
    bandColumns: 0,
    petColumns: 0,
    petKey: KEY,
    grab: null,
  }

  on('session.start', async ($, e, next) => {
    await start($, s)
    return next(e)
  })

  on('command.run', { command: 'plushie' }, async ($, e) => {
    const [verb = '', name = ''] = e.args.trim().split(/\s+/)

    if (verb === '') {
      s.isShown = !s.isShown
      s.host?.invalidate()
      return { text: s.isShown ? 'Plush Clawd is back' : 'Plush Clawd is napping out of sight' }
    }

    if (verb === 'list') {
      const reactions = s.pet?.clipNames().join(', ') ?? 'none yet: the frames are missing'
      const switches = FEATURES.map(f => `${s.isOn(f) ? 'on ' : 'off'}  ${f}`).join('\n')
      return {
        text: `Reactions to play with /plushie <reaction>:\n${reactions}\n\nSwitches (/plushie on|off <switch>):\n${switches}`,
      }
    }

    if (verb === 'on' || verb === 'off') {
      const feature = FEATURES.find(f => f.toLowerCase() === name.toLowerCase())
      if (!feature) {
        return { text: `No switch called "${name}". There are: ${FEATURES.join(', ')}` }
      }
      // The switch is the plugin's userConfig field; its key carries however
      // the engine names this plugin (a --plugin-dir load adds @inline).
      const rows = await $.config.list()
      const row = rows.find(r => r.key.endsWith(`.${feature}`) && r.key.startsWith($.plugin.name))
      if (!row) {
        return { text: `Couldn't find the ${feature} setting` }
      }
      const { deny } = await $.config.set({ key: row.key, value: verb === 'on' })
      return { text: deny ?? `Plush Clawd's ${feature} is ${verb}` }
    }

    if (!s.pet?.play(verb, true)) {
      return { text: `Plush Clawd has no "${verb}" reaction; /plushie list shows them all` }
    }
    s.isShown = true
    s.host?.invalidate()
    return { text: `Plush Clawd plays ${verb}` }
  })

  on('turn.start', async ($, e, next) => {
    // The start doesn't say whose turn it is; any turn means work is under way.
    s.pet?.runningTurns.add(e.turnId)
    await noteActivity($, s)
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    const { pet } = s
    if (!pet) {
      return result
    }
    pet.runningTurns.delete(e.turnId)
    if (e.agentId) {
      pet.finishMini(e.agentId)
      return result
    }

    await noteActivity($, s)
    if (e.isAborted || e.reason === 'error') {
      pet.play('oops')
    } else if (e.durationMs >= HAPPY_AFTER_MS) {
      pet.play('happy')
    }
    if (s.isOn('stuffing')) {
      try {
        const { context } = await $.session.usage()
        pet.size = sizeFor(context.percent ?? 0)
      } catch {
        // No reading this time; the size stays as it was.
      }
    }
    return result
  })

  on('tool.call', async ($, e, next) => {
    const { pet } = s
    // A subagent's tool calls are its own business: no prop, no wobble.
    if (e.agentId || !pet) {
      return next(e)
    }
    const prop = PROP_FOR_TOOL[e.tool]
    if (prop) {
      pet.toolStarted(e.tool_use_id, prop, await $.clock.now())
    }
    try {
      const result = await next(e)
      if (result.deny !== undefined || result.isError) {
        pet.play('oops')
      }
      return result
    } finally {
      pet.toolEnded(e.tool_use_id)
    }
  })

  on('prompt.submit', async ($, e, next) => {
    await noteActivity($, s)
    if (s.pet && s.isOn('blush') && KIND_WORDS.test(e.text)) {
      s.pet.play('blush')
    }
    return next(e)
  })

  on('agent.spawn', async ($, e, next) => {
    const result = await next(e)
    if (s.pet && s.isOn('miniClawds') && result.agentId) {
      s.pet.spawnMini(result.agentId)
      s.host?.sound('mini')
      $.ui.invalidate('ui.render')
    }
    return result
  })

  on('session.compact', async ($, e, next) => {
    const result = await next(e)
    // Only a stuffed or plump Clawd has anything to let out.
    if (s.pet && !e.agentId && s.isOn('stuffing') && s.pet.size !== 'normal') {
      s.pet.play('deflate')
      s.pet.size = 'normal'
    }
    return result
  })

  on('ui.message', { element: 'grab' }, async ($, e, next) => {
    const message = e.data as GrabMessage
    const { pet, manifest } = s
    if (!pet || !manifest || typeof message?.column !== 'number') {
      return next(e)
    }
    const shownLeft = leftIn(s, s.bandColumns, s.petColumns)

    // A held move with no press before it starts the grab too: a terminal can
    // fold the press into the first move of a quick drag.
    if (message.phase === 'down' || (message.phase === 'move' && !s.grab)) {
      s.grab = { offset: message.column - shownLeft, downColumn: message.column, isMoved: false }
      await noteActivity($, s)
    }
    if (message.phase !== 'down' && s.grab) {
      const { grab } = s
      // It takes a column of travel to turn a press into a drag.
      if (!grab.isMoved && s.isOn('drag') && Math.abs(message.column - grab.downColumn) >= 1) {
        grab.isMoved = true
        pet.isHeld = true
      }
      if (grab.isMoved) {
        s.left = clamp(message.column - grab.offset, 0, s.bandColumns - s.petColumns)
      }
      if (message.phase === 'up') {
        if (grab.isMoved) {
          pet.isHeld = false
          pet.play('drop')
          await $.store.set('left', s.left).catch(() => undefined)
        } else if (s.isOn('pats')) {
          pet.play('pat')
        }
        s.grab = null
      }
      $.ui.invalidate('ui.render')
    }
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const below = await next(e)
    if (e.surface !== 'terminal') {
      return below
    }
    await start($, s)

    const { manifest, pet } = s
    const isDrawable =
      s.isShown &&
      !s.isUnsupported &&
      !e.props.hasSurvey &&
      manifest !== null &&
      e.props.maxRows >= MIN_ROWS &&
      e.props.bodyColumns >= manifest.columns + 20
    if (!isDrawable || !manifest || !pet) {
      return below
    }

    s.requestId = e.requestId
    s.bandColumns = e.props.bodyColumns
    pet.sync(await $.clock.now())

    const { Box, Image, Client, Text } = await $.ui.resolve(e)
    // A short band (agents listed under the prompt take its rows) gets a
    // smaller Clawd, same shape, rather than none.
    const rows = Math.min(manifest.rows, e.props.maxRows)
    const columns = Math.round((manifest.columns * rows) / manifest.rows)
    s.petColumns = columns
    s.petKey = rows === manifest.rows ? KEY : `${KEY}-${rows}`
    const petLeft = leftIn(s, s.bandColumns, columns)

    // Mini Clawds stand to the pet's left, or to its right when there's no
    // room; a leaving one walks off a column every other frame.
    const miniColumns = Math.floor(columns / 2)
    const miniRows = Math.floor(rows / 2)
    const working = pet.framesOf('working')
    const minis: RenderElement[] = []
    pet.minis.forEach((mini, i) => {
      const slot = (i + 1) * (miniColumns + 1)
      const home = petLeft - slot >= 0 ? petLeft - slot : petLeft + columns + 1 + i * (miniColumns + 1)
      const x = home - (mini.leaving === null ? 0 : Math.floor(mini.leaving / 2))
      if (x < 0 || x + miniColumns > s.bandColumns || (mini.leaving ?? 0) >= LEAVE_FRAMES) {
        return
      }
      minis.push(
        <Box key={`mini-slot-${mini.id}`} position="absolute" left={x} top={rows - miniRows}>
          <Image
            key={`mini-${mini.id}`}
            source={{ file: fileOf(s, 'working', mini.frame % working), format: 'png' }}
            columns={miniColumns}
            rows={miniRows}
            alt=" "
          />
        </Box>,
      )
    })

    const isGrabbable = s.isOn('drag') || s.isOn('pats')
    const grabProps: GrabProps = { left: petLeft, columns, rows }

    // The pet has its own strip; inside it the picture and, on top, the
    // invisible grab region sit at the same column.
    return (
      <Box flexDirection="column">
        {below}
        <Box width={s.bandColumns} height={rows}>
          {minis}
          {pet.extraMinis > 0 ? (
            <Box key="extra-minis" position="absolute" left={Math.max(0, petLeft - 4)} top={0}>
              <Text dimColor>+{pet.extraMinis}</Text>
            </Box>
          ) : null}
          <Box key="pet" position="absolute" left={petLeft} top={0}>
            <Image
              key={s.petKey}
              source={{ file: fileOf(s, pet.clip, pet.fileFrame()), format: 'png' }}
              columns={columns}
              rows={rows}
              alt=" "
            />
          </Box>
          {isGrabbable ? (
            <Box position="absolute" left={petLeft} top={0}>
              <Client key="grab" module="./grab.tsx" props={grabProps} />
            </Box>
          ) : null}
        </Box>
      </Box>
    )
  })
}
