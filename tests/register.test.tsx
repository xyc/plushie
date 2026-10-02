import type { On, RenderElement } from 'claude-code'
import { describe, expect, mock, test, tier } from 'claude-code/testing'
import type { Mounted } from 'claude-code/testing'

tier('user')

// The clips the bake produces, as blender/plush.py lists them.
const CLIPS: Record<string, [number, boolean]> = {
  idle: [48, true],
  'idle-plump': [48, true],
  'idle-stuffed': [48, true],
  working: [24, true],
  'working-magnifier': [24, true],
  'working-needles': [24, true],
  'working-keyboard': [24, true],
  'working-binoculars': [24, true],
  'working-plump': [24, true],
  'working-stuffed': [24, true],
  happy: [32, false],
  sleepy: [64, true],
  oops: [36, false],
  held: [24, true],
  drop: [16, false],
  deflate: [24, false],
  blush: [32, false],
  pat: [28, false],
  'fidget-look': [36, false],
  'fidget-scratch': [32, false],
  'fidget-yawn': [40, false],
  'fidget-hop': [20, false],
}

const MANIFEST = JSON.stringify({
  fps: 24,
  columns: 16,
  rows: 6,
  clips: Object.fromEntries(Object.entries(CLIPS).map(([name, [frames, loop]]) => [name, { frames, loop }])),
})

const BAND = {
  plugin: 'plushie',
  component: 'AbovePrompt',
  requestId: 'band',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 20,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const

const START = { surface: 'terminal', isInteractive: true, cwd: '/work' } as const
const COMMAND = { origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } } as const

/**
 * What the session beneath the plugin answers: a clock, the manifest,
 * commands, blits, turns, the context's fill, and an empty band, which is
 * what the engine draws there.
 */
function answerTheWorld(on: On, contextPercent = 10, manifest = MANIFEST) {
  const clock = mock.clock(on)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('fs.read', () => ({ value: manifest }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('ui.blit', () => ({ value: {} }))
  on('ui.render', () => h(Fragment, null) as RenderElement)
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('session.usage', () => ({
    value: { startedAt: 0, context: { window: 200000, percent: contextPercent }, rateLimits: [] },
  }))
  return clock
}

type Band = Mounted<'terminal', 'AbovePrompt'>

/** The clip the pet shows: the folder of the frame its Image draws. */
async function shownClip(band: Band) {
  await band.redraw()
  const pet = await band.find({ key: 'plush' })
  return (pet?.props.source as { file: string } | undefined)?.file.match(/frames\/([\w-]+)\//)?.[1]
}

const complete = (
  $: { turn: { complete: (e: never) => Promise<unknown> } },
  turnId: string,
  durationMs: number,
  reason: 'answer' | 'aborted' = 'answer',
  agentId?: string,
) =>
  $.turn.complete({ answer: '', durationMs, isAborted: reason === 'aborted', turnId, reason, agentId } as never)

describe('register', () => {
  test('the terminal band draws the pet, the desktop band is left alone', async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)

    const terminal = await $.ui.mount({ ...BAND, surface: 'terminal' })
    const pet = await terminal.find({ key: 'plush' })
    expect(pet?.type).toBe('Image')
    expect(pet?.props.columns).toBe(16)
    expect(String((pet?.props.source as { file: string }).file)).toMatch(/frames\/idle\/000\.png$/)
    await terminal.unmount()

    const desktop = await $.ui.mount({ ...BAND, surface: 'desktop' })
    expect(await desktop.find({ key: 'plush' })).toBeUndefined()
    await desktop.unmount()
  })

  test('a narrow band or a survey keeps the pet out of the way', async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)

    const narrow = await $.ui.mount({ ...BAND, surface: 'terminal', props: { ...BAND.props, bodyColumns: 30 } })
    expect(await narrow.find({ key: 'plush' })).toBeUndefined()
    await narrow.unmount()

    const survey = await $.ui.mount({ ...BAND, surface: 'terminal', props: { ...BAND.props, hasSurvey: true } })
    expect(await survey.find({ key: 'plush' })).toBeUndefined()
    await survey.unmount()
  })

  test('/plushie hides the pet and brings it back', async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)
    const run = () => $.command.run({ ...COMMAND, command: 'plushie', args: '' })

    expect((await run()).text).toContain('out of sight')
    const hidden = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await hidden.find({ key: 'plush' })).toBeUndefined()
    await hidden.unmount()

    expect((await run()).text).toContain('back')
    const shown = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await shown.find({ key: 'plush' })).toBeDefined()
    await shown.unmount()
  })

  test('turns and tool calls pick the clip', async ($, on) => {
    const clock = answerTheWorld(on)
    on('tool.call', () => ({ isError: true as const, result: 'boom', text: 'boom' }))
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

    expect(await shownClip(band)).toBe('idle')

    await $.turn.start({ text: 'hi', turnId: 't1' })
    expect(await shownClip(band)).toBe('working')

    await $.tool.call({ tool: 'Bash', command: 'false' })
    expect(await shownClip(band)).toBe('oops')
    // The wobble plays out, then the turn's work shows again.
    await clock.advance(2000)
    expect(await shownClip(band)).toBe('working')

    await complete($, 't1', 9000)
    expect(await shownClip(band)).toBe('happy')
    await clock.advance(2000)
    expect(await shownClip(band)).toBe('idle')

    await $.turn.start({ text: 'stop', turnId: 't2' })
    await complete($, 't2', 2000, 'aborted')
    expect(await shownClip(band)).toBe('oops')

    await band.unmount()
  })

  test('/plushie <clip> plays it', async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

    const { text } = await $.command.run({ ...COMMAND, command: 'plushie', args: 'working-binoculars' })
    expect(text).toBe('Plush Clawd plays working-binoculars')
    expect(await shownClip(band)).toBe('working-binoculars')

    expect((await $.command.run({ ...COMMAND, command: 'plushie', args: 'nope' })).text).toContain('no "nope" reaction')
    await band.unmount()
  })

  test('dragging moves the pet along the band and drops it there', async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    const petLeft = async () => (await band.find({ key: 'pet' }))?.props.left

    // 100 columns wide, a 16-column pet: it starts at the right end.
    expect(await petLeft()).toBe(84)

    // Take hold 4 columns into the pet and carry it 30 columns left. The
    // region moves with the pet, so the release under the same screen
    // column is 4 columns into it again.
    await band.pointer({ type: 'down', x: 4, y: 2, button: 'left', in: 'grab' })
    await band.pointer({ type: 'move', x: -26, y: 2, button: 'left', in: 'grab' })
    expect(await shownClip(band)).toBe('held')
    await band.pointer({ type: 'up', x: 4, y: 2, button: 'left', in: 'grab' })
    expect(await petLeft()).toBe(54)
    expect(await shownClip(band)).toBe('drop')

    // A drag past the edge stops at the band's left end.
    await band.pointer({ type: 'down', x: 1, y: 0, button: 'left', in: 'grab' })
    await band.pointer({ type: 'move', x: -500, y: 0, button: 'left', in: 'grab' })
    await band.pointer({ type: 'up', x: -446, y: 0, button: 'left', in: 'grab' })
    expect(await petLeft()).toBe(0)

    await band.unmount()
  })

  test('a press without a drag is a pat', async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

    await band.pointer({ type: 'down', x: 8, y: 3, button: 'left', in: 'grab' })
    await band.pointer({ type: 'up', x: 8, y: 3, button: 'left', in: 'grab' })
    expect(await shownClip(band)).toBe('pat')
    expect((await band.find({ key: 'pet' }))?.props.left).toBe(84)
    await band.unmount()
  })

  test('pats off: a press does nothing', { options: { pats: false } }, async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

    await band.pointer({ type: 'down', x: 8, y: 3, button: 'left', in: 'grab' })
    await band.pointer({ type: 'up', x: 8, y: 3, button: 'left', in: 'grab' })
    expect(await shownClip(band)).toBe('idle')
    await band.unmount()
  })

  test('drag and pats both off: no grab region at all', { options: { drag: false, pats: false } }, async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ key: 'grab' })).toBeUndefined()
    await band.unmount()
  })

  for (const isOn of [true, false]) {
    test(`a tool call shows its prop, a quick one for a moment at least (toolProps ${isOn ? 'on' : 'off'})`, { options: { toolProps: isOn } }, async ($, on) => {
      const clock = answerTheWorld(on)
      let finish = () => {}
      on('tool.call', ($, e) =>
        e.tool === 'Bash'
          ? new Promise(resolve => {
              finish = () => resolve({ result: 'ok', text: 'ok' })
            })
          : { result: 'ok', text: 'ok' },
      )
      await $.session.start(START)
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
      await $.turn.start({ text: 'look', turnId: 't1' })

      // A read is over at once, but the magnifier stays up a moment.
      await $.tool.call({ tool: 'Read', file_path: '/work/notes.md' })
      expect(await shownClip(band)).toBe(isOn ? 'working-magnifier' : 'working')
      await clock.advance(1600)
      expect(await shownClip(band)).toBe('working')

      // A long shell command holds the keyboard for as long as it runs.
      const call = $.tool.call({ tool: 'Bash', command: 'sleep 9' })
      await clock.settle()
      await clock.advance(5000)
      expect(await shownClip(band)).toBe(isOn ? 'working-keyboard' : 'working')
      finish()
      await call
      await clock.advance(100)
      expect(await shownClip(band)).toBe('working')
      await band.unmount()
    })
  }

  for (const isOn of [true, false]) {
    test(`kind words make Clawd blush (blush ${isOn ? 'on' : 'off'})`, { options: { blush: isOn } }, async ($, on) => {
      answerTheWorld(on)
      on('prompt.submit', ($, e) => ({ text: e.text }))
      await $.session.start(START)
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
      const submit = (text: string) =>
        $.prompt.submit({ text, wait: false, origin: { kind: 'composer' } } as never)

      await submit('fix the parser please')
      expect(await shownClip(band)).toBe('idle')
      await submit('Thanks, that worked!')
      expect(await shownClip(band)).toBe(isOn ? 'blush' : 'idle')
      await band.unmount()
    })
  }

  for (const isOn of [true, false]) {
    test(`subagents get mini Clawds that walk off (miniClawds ${isOn ? 'on' : 'off'})`, { options: { miniClawds: isOn } }, async ($, on) => {
      const clock = answerTheWorld(on)
      on('agent.spawn', () => ({ model: 'haiku', agentId: 'a1' }))
      await $.session.start(START)
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

      await $.agent.spawn({ tool_use_id: 'u1', prompt: 'look around', description: 'look', subagentType: 'Explore' } as never)
      await band.redraw()
      const mini = await band.find({ key: 'mini-a1' })
      expect(mini === undefined).toBe(!isOn)
      if (isOn) {
        expect(mini?.props.columns).toBe(8)
      }

      await complete($, 'agent-turn', 3000, 'answer', 'a1')
      await clock.advance(1500)
      await band.redraw()
      expect(await band.find({ key: 'mini-a1' })).toBeUndefined()
      await band.unmount()
    })
  }

  test('a full context stuffs Clawd and compaction lets it out', async ($, on) => {
    answerTheWorld(on, 85)
    on('session.compact', ($, e) => ({ messages: e.messages }))
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

    await $.turn.start({ text: 'go', turnId: 't1' })
    expect(await shownClip(band)).toBe('working')
    await complete($, 't1', 1000)
    expect(await shownClip(band)).toBe('idle-stuffed')
    await $.turn.start({ text: 'more', turnId: 't2' })
    expect(await shownClip(band)).toBe('working-stuffed')
    await complete($, 't2', 1000)

    await $.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: 'go', toolUses: [] }] } as never)
    expect(await shownClip(band)).toBe('deflate')
    await band.unmount()
  })

  test('stuffing off: Clawd keeps its size', { options: { stuffing: false } }, async ($, on) => {
    answerTheWorld(on, 85)
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

    await $.turn.start({ text: 'go', turnId: 't1' })
    await complete($, 't1', 1000)
    expect(await shownClip(band)).toBe('idle')
    await band.unmount()
  })

  test('/plushie on|off flips a switch, /plushie list shows reactions and switches', async ($, on) => {
    answerTheWorld(on)
    const sets: unknown[] = []
    on('config.list', () => ({ value: [{ key: 'plushie@inline.blush', label: 'Blush', kind: 'boolean', value: true }] }) as never)
    on('config.set', ($, e) => {
      sets.push(e)
      return { value: e.value }
    })
    await $.session.start(START)
    const run = (args: string) => $.command.run({ ...COMMAND, command: 'plushie', args })

    expect((await run('off blush')).text).toBe("Plush Clawd's blush is off")
    expect(sets).toEqual([expect.objectContaining({ key: 'plushie@inline.blush', value: false })])
    expect((await run('on sparkles')).text).toContain('No switch called "sparkles"')
    const listed = (await run('list')).text
    expect(listed).toContain('happy, ')
    expect(listed).toContain('on   toolProps')
  })

  for (const isOn of [true, false]) {
    test(`left alone, Clawd fidgets now and then (fidgets ${isOn ? 'on' : 'off'})`, { options: { fidgets: isOn } }, async ($, on) => {
      const clock = answerTheWorld(on)
      await $.session.start(START)
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

      // The wait is random but never past 40 s, and a fidget lasts under 2 s.
      const seen = new Set<string>()
      for (let ms = 0; ms < 42_000; ms += 500) {
        await clock.advance(500)
        seen.add((await shownClip(band)) ?? '')
      }
      const fidgeted = [...seen].some(clip => clip.startsWith('fidget-'))
      expect(fidgeted).toBe(isOn)

      // A turn starting cuts any fidget short.
      await $.turn.start({ text: 'go', turnId: 't1' })
      expect(await shownClip(band)).toBe('working')
      await band.unmount()
    })
  }

  for (const isOn of [true, false]) {
    test(`a pat and a jump make their sounds (sounds ${isOn ? 'on' : 'off'})`, { options: { sounds: isOn } }, async ($, on) => {
      answerTheWorld(on)
      const played: string[] = []
      on('audio.play', ($, e) => {
        played.push((e.clip as { asset: string }).asset)
        return { value: undefined }
      })
      await $.session.start(START)
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

      await band.pointer({ type: 'down', x: 8, y: 3, button: 'left', in: 'grab' })
      await band.pointer({ type: 'up', x: 8, y: 3, button: 'left', in: 'grab' })
      await $.turn.start({ text: 'go', turnId: 't1' })
      await complete($, 't1', 9000)
      await shownClip(band)

      // Idle and working are quiet; the pat and the jump are not.
      expect(played).toEqual(isOn ? ['assets/sounds/pat.wav', 'assets/sounds/happy.wav'] : [])
      await band.unmount()
    })
  }

  test('a frames folder from an older bake leaves the band alone', async ($, on) => {
    const older = JSON.stringify({ fps: 24, columns: 16, rows: 6, moods: { idle: { frames: 48, loop: true } } })
    answerTheWorld(on, 10, older)
    on('ui.log', () => ({ value: undefined }))
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await band.find({ key: 'plush' })).toBeUndefined()
    await band.unmount()
  })

  test('a short band gets a smaller Clawd, a very short one none', async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)

    const short = await $.ui.mount({ ...BAND, surface: 'terminal', props: { ...BAND.props, maxRows: 5 } })
    // A new size is a new Image, so the terminal places it afresh.
    expect(await short.find({ key: 'plush' })).toBeUndefined()
    const pet = await short.find({ key: 'plush-5' })
    expect([pet?.props.columns, pet?.props.rows]).toEqual([13, 5])
    await short.unmount()

    const tiny = await $.ui.mount({ ...BAND, surface: 'terminal', props: { ...BAND.props, maxRows: 3 } })
    expect(await tiny.find({ key: 'plush' })).toBeUndefined()
    await tiny.unmount()
  })

  test('a drag whose press the terminal folded into its first move still drags', async ($, on) => {
    answerTheWorld(on)
    await $.session.start(START)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })

    await band.pointer({ type: 'move', x: 4, y: 2, button: 'left', in: 'grab' })
    await band.pointer({ type: 'move', x: -26, y: 2, button: 'left', in: 'grab' })
    expect(await shownClip(band)).toBe('held')
    await band.pointer({ type: 'up', x: 4, y: 2, button: 'left', in: 'grab' })
    expect((await band.find({ key: 'pet' }))?.props.left).toBe(54)
    await band.unmount()
  })
})
