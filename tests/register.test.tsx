import type { On, RenderElement } from 'claude-code'
import { describe, expect, mock, test, tier } from 'claude-code/testing'

tier('user')

const MANIFEST = JSON.stringify({
  fps: 24,
  columns: 16,
  rows: 6,
  moods: {
    idle: { frames: 48, loop: true },
    working: { frames: 24, loop: true },
    happy: { frames: 32, loop: false },
    sleepy: { frames: 64, loop: true },
    oops: { frames: 20, loop: false },
  },
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

/**
 * What the session beneath the plugin answers: a clock, the manifest,
 * commands, and an empty band, which is what the engine draws there.
 */
function answerTheWorld(on: On) {
  mock.clock(on)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('fs.read', () => ({ value: MANIFEST }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('ui.render', () => h(Fragment, null) as RenderElement)
}

describe('register', () => {
  test('the terminal band draws the pet, the desktop band is left alone', async ($, on) => {
    answerTheWorld(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

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
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    const narrow = await $.ui.mount({
      ...BAND,
      surface: 'terminal',
      props: { ...BAND.props, bodyColumns: 30 },
    })
    expect(await narrow.find({ key: 'plush' })).toBeUndefined()
    await narrow.unmount()

    const survey = await $.ui.mount({
      ...BAND,
      surface: 'terminal',
      props: { ...BAND.props, hasSurvey: true },
    })
    expect(await survey.find({ key: 'plush' })).toBeUndefined()
    await survey.unmount()
  })

  test('/plushie hides the pet and brings it back', async ($, on) => {
    answerTheWorld(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    const run = () =>
      $.command.run({
        command: 'plushie',
        args: '',
        origin: { kind: 'composer' },
        presentation: { isFullscreen: false, columns: 100 },
      })

    expect((await run()).text).toContain('out of sight')
    const hidden = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await hidden.find({ key: 'plush' })).toBeUndefined()
    await hidden.unmount()

    expect((await run()).text).toContain('back')
    const shown = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await shown.find({ key: 'plush' })).toBeDefined()
    await shown.unmount()
  })

  test('turns and tool calls pick the mood the pet plays', async ($, on) => {
    answerTheWorld(on)
    on('turn.start', ($, e) => ({ turnId: e.turnId }))
    on('turn.complete', () => ({ text: '' }))
    on('tool.call', () => ({ isError: true as const, result: 'boom', text: 'boom' }))
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    const shownMood = async () => {
      await band.redraw()
      const pet = await band.find({ key: 'plush' })
      return (pet?.props.source as { file: string }).file.match(/frames\/(\w+)\//)?.[1]
    }
    const complete = (turnId: string, durationMs: number, reason: 'answer' | 'aborted') =>
      $.turn.complete({
        answer: '',
        durationMs,
        isAborted: reason === 'aborted',
        turnId,
        reason,
      })

    expect(await shownMood()).toBe('idle')

    await $.turn.start({ text: 'hi', turnId: 't1' })
    expect(await shownMood()).toBe('working')

    await $.tool.call({ tool: 'Bash', command: 'false' })
    expect(await shownMood()).toBe('oops')

    await complete('t1', 9000, 'answer')
    expect(await shownMood()).toBe('happy')

    await $.turn.start({ text: 'quick', turnId: 't2' })
    await complete('t2', 500, 'answer')
    expect(await shownMood()).toBe('idle')

    await $.turn.start({ text: 'stop', turnId: 't3' })
    await complete('t3', 2000, 'aborted')
    expect(await shownMood()).toBe('oops')

    await band.unmount()
  })

  test('/plushie <mood> plays that mood', async ($, on) => {
    answerTheWorld(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    const { text } = await $.command.run({
      command: 'plushie',
      args: 'sleepy',
      origin: { kind: 'composer' },
      presentation: { isFullscreen: false, columns: 100 },
    })
    expect(text).toBe('Plush Clawd is sleepy')

    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    const pet = await band.find({ key: 'plush' })
    expect((pet?.props.source as { file: string }).file).toMatch(/frames\/sleepy\/000\.png$/)
    await band.unmount()
  })

  test('dragging the grab region moves the pet along the band', async ($, on) => {
    answerTheWorld(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    const petLeft = async () => (await band.find({ key: 'pet' }))?.props.left

    // 100 columns wide, a 16-column pet: it starts at the right end.
    expect(await petLeft()).toBe(84)

    // Take hold 4 columns into the pet and carry it 30 columns left. The
    // region moves with the pet, so the release under the same screen
    // column is 4 columns into it again.
    await band.pointer({ type: 'down', x: 4, y: 2, button: 'left', in: 'grab' })
    await band.pointer({ type: 'move', x: -26, y: 2, button: 'left', in: 'grab' })
    await band.pointer({ type: 'up', x: 4, y: 2, button: 'left', in: 'grab' })
    expect(await petLeft()).toBe(54)

    // A drag past the edge stops at the band's left end.
    await band.pointer({ type: 'down', x: 1, y: 0, button: 'left', in: 'grab' })
    await band.pointer({ type: 'move', x: -500, y: 0, button: 'left', in: 'grab' })
    await band.pointer({ type: 'up', x: -446, y: 0, button: 'left', in: 'grab' })
    expect(await petLeft()).toBe(0)

    await band.unmount()
  })
})
